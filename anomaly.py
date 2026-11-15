"""Anomaly detection following the Biomedical Alert Threshold Specification.

Two layers run in parallel and the more severe result wins:
  1. Personal baseline  -> AMBER (early warning)
  2. Absolute safety net (NEWS2-based fixed limits) -> RED / AMBER
plus: persistence in SECONDS, advisories (not official alerts), multi-signal rules
(MS-01, MS-02, MS-04, MS-05), baseline phases by mission day, and a GRAY state for
unreliable data. All numbers live in config/thresholds_v1.json.

Not implemented yet (needs data this prototype does not have): MS-03 (multi-day trend:
HRV + sleep), MS-06 (acknowledgement timers), MS-07 and exercise mode (needs exercise
logs and the rate-pressure product), skin-temperature and HRV trend alerts.
"""

import math
import statistics
from datetime import datetime, timezone

from baselines import BaselineCalculator
from thresholds import load_thresholds

NORMAL, ADVISORY, AMBER, RED = 0, 1, 2, 3
LEVEL_NAME = {NORMAL: "NORMAL", ADVISORY: "ADVISORY", AMBER: "AMBER", RED: "RED"}
LABEL = {"heart_rate": "Heart rate", "spo2": "SpO2", "respiratory_rate": "Respiratory rate",
         "systolic_bp": "Systolic BP", "temperature_core": "Core temperature"}
NEWS2_SIGNALS = ("heart_rate", "respiratory_rate", "spo2", "systolic_bp", "temperature_core")


def _parse_ts(ts):
    """Parse an ISO timestamp. Returns an aware datetime or None."""
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _band_score(bands, v):
    for lo, hi, score in bands:
        if (lo is None or v >= lo) and (hi is None or v <= hi):
            return score
    return 0


class AnomalyDetector:
    def __init__(self, baseline_calculator, config=None):
        self.baseline_calc = baseline_calculator
        self.cfg = config or load_thresholds()

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    @staticmethod
    def phase_for(mission_day, cfg):
        if mission_day is None:
            return "unspecified"
        ph = cfg["baseline"]["phases"]
        if mission_day <= ph["calibrating_until_day"]:
            return "calibrating"
        if mission_day <= ph["provisional_until_day"]:
            return "provisional"
        return "stable"

    @staticmethod
    def _r(signal, v):
        """Bands are defined on whole numbers (0.1 for temperature), like device displays."""
        return round(v, 1) if signal == "temperature_core" else round(v)

    def _signal_cfg(self, signal, mission_day):
        sc = self.cfg["signals"][signal]
        if signal == "temperature_core":
            inflight = mission_day is not None and mission_day >= 8
            table = sc["inflight_from_day_8"] if inflight else sc["ground"]
            return {**sc, **table}
        return sc

    # ------------------------------------------------------------------
    # Layer 1: data quality gate
    # ------------------------------------------------------------------
    def check_data_quality(self, m):
        """Single-reading check. Returns (status, reason): GOOD / SUSPECT / UNUSABLE."""
        q = self.cfg["quality"]
        if not math.isfinite(m.value):
            return "UNUSABLE", "value is not a finite number"
        if m.quality < q["min_quality"]:
            return "UNUSABLE", f"sensor quality {m.quality} is too low"
        sc = self.cfg["signals"].get(m.signal)
        if sc:
            lo, hi = sc["valid"]
            if not (lo <= m.value <= hi):
                return "UNUSABLE", f"value {m.value:.1f} is outside the valid range"
        if m.quality < q["good_quality"]:
            return "SUSPECT", f"moderate sensor quality {m.quality}"
        return "GOOD", "data is trustworthy"

    def _screen(self, measurements, times, now_dt):
        """Quality-gate a whole batch. Returns [(status, reason), ...] aligned with input."""
        q = self.cfg["quality"]
        st = [list(self.check_data_quality(m)) for m in measurements]

        if now_dt is not None:  # stale data
            for i, m in enumerate(measurements):
                t = _parse_ts(m.timestamp)
                if st[i][0] != "UNUSABLE" and t is not None:
                    age = (now_dt - t).total_seconds() / 60.0
                    if age > q["stale_after_minutes"]:
                        st[i] = ["UNUSABLE", f"stale data ({age:.0f} min old)"]

        by_signal = {}
        for i, m in enumerate(measurements):
            by_signal.setdefault(m.signal, []).append(i)

        for signal, idxs in by_signal.items():
            # flat-line: the exact same value for flatline_seconds or longer
            ok = [i for i in idxs if st[i][0] != "UNUSABLE"]
            run = []
            for i in ok + [None]:
                if run and (i is None or abs(measurements[i].value - measurements[run[0]].value) > 1e-9):
                    span = times[run[-1]] - times[run[0]]
                    if len(run) >= q["flatline_min_readings"] and span >= q["flatline_seconds"]:
                        for j in run:
                            st[j] = ["UNUSABLE", f"flat-line: same value for {span:.0f} s"]
                    run = []
                if i is not None:
                    run.append(i)

            # physically impossible change between consecutive samples (per second)
            ok = [i for i in idxs if st[i][0] != "UNUSABLE"]
            jump = q["max_jump_per_second"].get(signal)
            if jump:
                for a in range(1, len(ok)):
                    dt = times[ok[a]] - times[ok[a - 1]]
                    d = abs(measurements[ok[a]].value - measurements[ok[a - 1]].value)
                    if dt > 0 and d / dt > jump:
                        st[ok[a]] = ["UNUSABLE", f"impossible change ({d:.0f} in {dt:.0f} s)"]

            # isolated spike: an excursion that jumps away and straight back (added by Data/AI Lead)
            ok = [i for i in idxs if st[i][0] != "UNUSABLE"]
            limit = q["isolated_spike"].get(signal)
            if limit:
                for a in range(1, len(ok) - 1):
                    prev, cur, nxt = ok[a - 1], ok[a], ok[a + 1]
                    up = measurements[cur].value - measurements[prev].value
                    down = measurements[cur].value - measurements[nxt].value
                    gap = (times[cur] - times[prev]) / 60.0
                    if abs(up) > limit and abs(down) > limit and up * down > 0 \
                            and gap <= q["spike_max_gap_minutes"]:
                        st[cur] = ["UNUSABLE", f"isolated spike ({up:+.0f} jump that reverted)"]
        return [tuple(s) for s in st]

    # ------------------------------------------------------------------
    # Layers 2 + 3: classify one reading
    # ------------------------------------------------------------------
    def _classify(self, crew_id, signal, m, status, mission_day, baseline_ok):
        """Returns (level, rule, dev). Red > amber > advisory > normal.
        The baseline comparison (dev) is always computed when a baseline exists, so alerts
        and multi-signal rules can use it even when a fixed limit already matched."""
        sc = self._signal_cfg(signal, mission_day)
        v = self._r(signal, m.value)
        bcfg = self.cfg["baseline"]

        dev = None
        if baseline_ok:
            d = self.baseline_calc.calculate_deviation(crew_id, signal, m.value)
            if "error" not in d:
                dev = d

        # fixed limits (safety net) first
        if sc.get("red_low") is not None and v <= sc["red_low"]:
            return RED, "RED-ABS", dev
        if sc.get("red_high") is not None and v >= sc["red_high"]:
            return RED, "RED-ABS", dev
        for lo, hi in sc.get("amber_abs", []):
            if lo <= v <= hi:
                return AMBER, "AMBER-ABS", dev

        # personal baseline (early warning)
        if dev is not None:
            if sc.get("baseline_amber"):
                guard = bcfg["min_change"].get(signal, 0)
                if abs(dev["z_score"]) >= bcfg["amber_z"] and abs(dev["deviation"]) >= guard:
                    return AMBER, "AMBER-BASELINE", dev
            drop = sc.get("amber_drop_from_baseline")
            if drop is not None and dev["baseline_median"] - m.value >= drop:
                return AMBER, "AMBER-DROP", dev
            rise = sc.get("advisory_above_baseline")
            if rise is not None and m.value - dev["baseline_median"] >= rise and status == "GOOD":
                return ADVISORY, "ADVISORY-BASELINE", dev

        adv = sc.get("advisory_max")
        if adv is not None and v <= adv and status == "GOOD":
            return ADVISORY, "ADVISORY-LOW", dev
        return NORMAL, None, dev

    def _evaluate_signal(self, series):
        """series: [(t, level, rule, m, dev, status)] in time order.
        Applies the persistence windows and returns the signal's CURRENT state."""
        p = self.cfg["persistence"]
        red_s, amb_s, adv_s = p["acute_red_seconds"], p["acute_amber_minutes"] * 60, p["advisory_minutes"] * 60
        red0 = amb0 = adv0 = None
        for t, lvl, *_ in series:
            red0 = (t if red0 is None else red0) if lvl >= RED else None
            amb0 = (t if amb0 is None else amb0) if lvl >= AMBER else None
            adv0 = (t if adv0 is None else adv0) if lvl >= ADVISORY else None
        t_last, _, rule, m, dev, status = series[-1]
        state = NORMAL
        if red0 is not None and t_last - red0 >= red_s:
            state, start = RED, red0
        elif amb0 is not None and t_last - amb0 >= amb_s:
            state, start = AMBER, amb0
        elif adv0 is not None and t_last - adv0 >= adv_s:
            state, start = ADVISORY, adv0
        else:
            start = None
        return {"state": state, "start": start, "amber_start": amb0, "t_last": t_last,
                "rule": rule, "m": m, "dev": dev, "status": status}

    def _news2_total(self, signal_series, mission_day):
        """MS-05: NEWS2-style aggregate from the median of the last N minutes per signal."""
        window = self.cfg["multi_signal"]["MS-05"]["window_minutes"] * 60
        inflight = mission_day is not None and mission_day >= 8
        total, parts = 0, {}
        for sig in NEWS2_SIGNALS:
            series = signal_series.get(sig)
            if not series:
                continue
            t_last = series[-1][0]
            win = [s for s in series if t_last - s[0] <= window]
            if win[-1][0] - win[0][0] < self.cfg["persistence"]["acute_red_seconds"]:
                continue  # needs sustained data, not a single instant
            v = statistics.median([self._r(sig, s[3].value) for s in win])
            bands = self.cfg["news2"][sig]
            if sig == "temperature_core":
                bands = bands["inflight" if inflight else "ground"]
            score = _band_score(bands, v)
            parts[sig] = score
            total += score
        return total, parts

    # ------------------------------------------------------------------
    # main entry point
    # ------------------------------------------------------------------
    def detect_anomaly(self, crew_id, measurements, now=None, mission_day=None,
                       symptom_reported=False):
        """Evaluate readings (in time order). The result reflects the CURRENT state at the
        end of the batch: alerts clear when the signal returns to normal.

        now:               optional ISO time; readings older than stale_after_minutes are GRAY.
        mission_day:       day of the mission (1 = launch day). Days 1-7: baseline rules are off,
                           only fixed limits apply. From day 8: in-flight temperature limits.
        symptom_reported:  True if the daily check-in reports a symptom (rule MS-04).
        """
        now_dt = _parse_ts(now) if now is not None else None
        times = []
        for i, m in enumerate(measurements):
            t = _parse_ts(m.timestamp)
            times.append(t.timestamp() if t is not None else i * 60.0)
        # process in time order, whatever order the caller sent them in
        order = sorted(range(len(measurements)), key=lambda i: times[i])
        measurements = [measurements[i] for i in order]
        times = [times[i] for i in order]

        screened = self._screen(measurements, times, now_dt)
        phase = self.phase_for(mission_day, self.cfg)
        baseline_ok = phase != "calibrating"

        notes, latest_unusable, series = [], {}, {}
        for i, (m, (status, reason)) in enumerate(zip(measurements, screened)):
            sc = self.cfg["signals"].get(m.signal)
            if not sc:
                continue  # check-in / context signals never affect the vital-sign status
            alertable = not sc.get("trend_only")
            if status == "UNUSABLE":
                notes.append(f"{m.signal}: {reason}")
                if alertable:
                    latest_unusable[m.signal] = reason
                continue
            if alertable:
                latest_unusable.pop(m.signal, None)
            else:
                continue  # trend-only signal: validated but not alerted on here
            lvl, rule, dev = self._classify(crew_id, m.signal, m, status, mission_day, baseline_ok)
            series.setdefault(m.signal, []).append((times[i], lvl, rule, m, dev, status))

        states = {sig: self._evaluate_signal(s) for sig, s in series.items()}

        # Spec: when data quality is poor the state is GRAY regardless of the values.
        # A signal whose LATEST reading is unusable goes gray; we remember what it was.
        last_known = {}
        for sig in list(states):
            if sig in latest_unusable:
                last_known[sig] = LEVEL_NAME[states[sig]["state"]]
                del states[sig]
        series = {sig: s for sig, s in series.items() if sig in states}

        alerts, advisories, rules = [], [], []
        for sig in sorted(states):
            s = states[sig]
            m, dev = s["m"], s["dev"]
            if s["state"] >= AMBER:
                alerts.append({
                    "signal": sig,
                    "level": LEVEL_NAME[s["state"]],
                    "rule": s["rule"] if s["rule"] else "AMBER-ABS",
                    "current": round(m.value, 1),
                    "baseline": round(dev["baseline_median"], 1) if dev else None,
                    "percent_change": dev["percent_change"] if dev else None,
                    "duration_seconds": round(s["t_last"] - s["start"]),
                    "quality": s["status"],
                })
            elif s["state"] == ADVISORY:
                advisories.append({
                    "signal": sig, "current": round(m.value, 1),
                    "duration_seconds": round(s["t_last"] - s["start"]),
                    "action": "Check sensor fit and repeat the measurement (not an official alert)",
                })

        # ---- multi-signal rules (advisories never count) ----
        ms = self.cfg["multi_signal"]
        ms_red = []
        amber_sigs = [sig for sig, s in states.items() if s["state"] >= AMBER]

        if len(amber_sigs) >= ms["MS-01"]["amber_count"]:
            t_end = max(states[s]["t_last"] for s in amber_sigs)
            overlap = t_end - max(states[s]["amber_start"] for s in amber_sigs)
            if overlap >= ms["MS-01"]["minutes"] * 60:
                ms_red.append(("MS-01", "Two or more signals have been in amber together for "
                               f"{ms['MS-01']['minutes']}+ minutes"))

        sp, rr_series = states.get("spo2"), series.get("respiratory_rate")
        if sp and sp["state"] >= AMBER and rr_series and baseline_ok:
            m2 = ms["MS-02"]
            t_last = rr_series[-1][0]
            vals = [x[3].value for x in rr_series if t_last - x[0] <= m2["rr_window_minutes"] * 60]
            d = self.baseline_calc.calculate_deviation(crew_id, "respiratory_rate", statistics.median(vals))
            if "error" not in d and d["z_score"] >= m2["rr_min_z"]:
                ms_red.append(("MS-02", "SpO2 is low while respiratory rate is rising: possible "
                               "respiratory problem or CO2 build-up"))

        if symptom_reported and amber_sigs:
            ms_red.append(("MS-04", "An amber signal together with a symptom reported in the check-in"))

        news_total, news_parts = self._news2_total(series, mission_day)
        if news_total >= ms["MS-05"]["news2_total_min"]:
            ms_red.append(("MS-05", f"Combined early-warning score is {news_total} "
                           f"(limit {ms['MS-05']['news2_total_min']})"))

        red_signals = [a for a in alerts if a["level"] == "RED"]
        if red_signals:
            escalation = "absolute_limit"
        elif ms_red:
            escalation = ms_red[0][0]
        elif alerts:
            escalation = "single_signal" if len(alerts) == 1 else "multiple_amber"
        else:
            escalation = None

        gray_reasons = sorted(
            f"{s}: {r}" + (f" (last confirmed state: {last_known[s]})"
                           if last_known.get(s) in ("AMBER", "RED", "ADVISORY") else "")
            for s, r in latest_unusable.items())
        if not series and not gray_reasons:
            gray_reasons = ["no valid vital-sign data received"]
        if red_signals or ms_red:
            overall = "RED"
        elif alerts:
            overall = "AMBER"
        elif gray_reasons:
            overall = "GRAY"
        else:
            overall = "GREEN"

        rules_triggered = sorted({a["rule"] for a in alerts} | {r for r, _ in ms_red})
        return {
            "overall_status": overall,
            "escalation": escalation,
            "alerts": alerts,
            "advisories": advisories,
            "rules_triggered": rules_triggered,
            "gray_reasons": gray_reasons,
            "data_notes": sorted(set(notes))[:10],
            "baseline_phase": phase,
            "news2_total": news_total,
            "explanation": self._explain(overall, alerts, advisories, ms_red, gray_reasons,
                                         notes, phase),
            "timestamp": measurements[-1].timestamp if measurements else None,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _explain(overall, alerts, advisories, ms_red, gray_reasons, notes, phase):
        def one(a):
            lab, cur, mins = LABEL.get(a["signal"], a["signal"]), a["current"], a["duration_seconds"] / 60
            if a["rule"] == "RED-ABS":
                return f"{lab} is {cur:g}, beyond the critical limit (for {mins:.0f} min)"
            if a["rule"] == "AMBER-ABS":
                return f"{lab} is {cur:g}, in the watch range (for {mins:.0f} min)"
            if a["rule"] == "AMBER-DROP":
                return (f"{lab} is {cur:g} vs personal baseline {a['baseline']:g}, "
                        f"a drop of {a['baseline'] - cur:.1f} points (for {mins:.0f} min)")
            return (f"{lab} is {cur:g} vs personal baseline {a['baseline']:g} "
                    f"({a['percent_change']:+.1f}%) (for {mins:.0f} min)")

        if overall == "GREEN":
            text = "All signals are within this crew member's normal limits."
        elif overall == "GRAY":
            return ("Sensor data is unreliable (" + "; ".join(gray_reasons)
                    + "). This is NOT a medical alert - check sensor contact.")
        else:
            text = "; ".join(one(a) for a in alerts) + "." if alerts else ""
            for rid, msg in ms_red:
                text += f" {msg} ({rid}): escalated to RED."
        for adv in advisories:
            text += (f" Advisory (not an alert): {LABEL.get(adv['signal'], adv['signal'])} is "
                     f"{adv['current']:g}. Check sensor fit and repeat the measurement.")
        if gray_reasons and overall != "GRAY":
            text += " Note: some sensor data is also unreliable (" + "; ".join(gray_reasons) + ")."
        elif notes and overall == "GREEN":
            text += " (Some readings were excluded as unreliable.)"
        if phase == "calibrating":
            text += " Baseline is calibrating (mission days 1-7): only fixed limits are active."
        return text.strip()


if __name__ == "__main__":
    from simulator import HealthSimulator

    SIGS = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "temperature_core")
    normal = HealthSimulator.simulate_normal_day("AV-01", 20, seed=1)
    calc = BaselineCalculator()
    for s in SIGS:
        calc.calculate_baseline("AV-01", s, normal)

    scenarios = [
        ("Normal Day", normal),
        ("Fatigue", HealthSimulator.simulate_fatigue("AV-01", 20, seed=2)),
        ("Deterioration", HealthSimulator.simulate_deterioration("AV-01", 20, seed=3)),
        ("Sensor Failure", HealthSimulator.simulate_sensor_failure("AV-01", 10, seed=4)),
    ]
    for label, data in scenarios:
        r = AnomalyDetector(calc).detect_anomaly("AV-01", data)
        print(f"{label}: {r['overall_status']}  (escalation: {r['escalation']}, rules: {r['rules_triggered']})")
        print(f"  {r['explanation']}\n")
