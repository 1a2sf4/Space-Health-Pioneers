"""Interface for the backend (Person B).

One main function: analyze_crew(). JSON-style dictionaries go in and a plain
JSON-serializable dictionary comes out, so FastAPI can return it directly and the
dashboard can render it.

Example input row:
    {"crew_id": "AV-01", "timestamp": "2026-10-09T08:30:00Z",
     "signal": "heart_rate", "value": 82.0, "unit": "bpm", "quality": 0.95}
"""

from measurement_schema import Measurement
from validator import DataValidator
from baselines import BaselineCalculator
from anomaly import AnomalyDetector
from thresholds import load_thresholds

REQUIRED_FIELDS = ("crew_id", "timestamp", "signal", "value", "unit", "quality")


def measurements_from_dicts(rows):
    """Convert a list of dicts (e.g. parsed JSON) into Measurement objects."""
    out = []
    for i, row in enumerate(rows):
        missing = [f for f in REQUIRED_FIELDS if f not in row]
        if missing:
            raise ValueError(f"Row {i} is missing fields: {missing}")
        out.append(Measurement(row["crew_id"], row["timestamp"], row["signal"],
                               float(row["value"]), row["unit"], float(row["quality"])))
    return out


def analyze_crew(crew_id, baseline_rows, recent_rows, now=None, mission_day=None,
                 symptom_reported=False, config=None):
    """Analyze recent readings for one crew member against their own baseline.

    baseline_rows:    readings from a period when the crew member was well (resting,
                      good quality), as a list of dicts.
    recent_rows:      readings to evaluate now, in time order, as a list of dicts.
    now:              optional ISO time. Readings older than 5 minutes are stale (GRAY).
    mission_day:      optional int (1 = launch day). Days 1-7: baseline rules are off and only
                      fixed limits apply. From day 8: in-flight temperature limits.
    symptom_reported: True if the daily check-in reports a symptom (rule MS-04).

    Returns a JSON-serializable dict:
        {"crew_id", "status" (GREEN/AMBER/RED/GRAY), "escalation", "explanation",
         "alerts": [...], "advisories": [...], "rules_triggered": [...],
         "gray_reasons": [...], "data_notes": [...], "baseline_phase", "news2_total",
         "timestamp", "data_quality": {...}, "baselines": {...}, "thresholds_version"}
    """
    cfg = config or load_thresholds()
    baseline = measurements_from_dicts(baseline_rows)
    recent = measurements_from_dicts(recent_rows)
    wrong = sorted({m.crew_id for m in recent if m.crew_id != crew_id})
    if wrong:
        raise ValueError(f"recent_rows contain other crew members: {wrong} (expected {crew_id})")

    calc = BaselineCalculator(cfg)
    clean = [m for m in baseline if DataValidator.validate_measurement(m, cfg)[0]]
    for signal in sorted({m.signal for m in clean}):
        calc.calculate_baseline(crew_id, signal, clean)

    result = AnomalyDetector(calc, cfg).detect_anomaly(
        crew_id, recent, now=now, mission_day=mission_day, symptom_reported=symptom_reported)
    valid = sum(DataValidator.validate_measurement(m, cfg)[0] for m in recent)

    return {
        "crew_id": crew_id,
        "status": result["overall_status"],
        "escalation": result["escalation"],
        "explanation": result["explanation"],
        "alerts": result["alerts"],
        "advisories": result["advisories"],
        "rules_triggered": result["rules_triggered"],
        "gray_reasons": result["gray_reasons"],
        "data_notes": result["data_notes"],
        "baseline_phase": result["baseline_phase"],
        "news2_total": result["news2_total"],
        "timestamp": result["timestamp"],
        "data_quality": {"total": len(recent), "valid": valid, "rejected": len(recent) - valid},
        "baselines": {
            sig: {"median": b["median"], "mad": b["mad"], "samples": b["samples"]}
            for sig, b in calc.baselines.get(crew_id, {}).items()
        },
        "thresholds_version": cfg["version"],
    }


def _to_rows(measurements):
    return [{"crew_id": m.crew_id, "timestamp": m.timestamp, "signal": m.signal,
             "value": m.value, "unit": m.unit, "quality": m.quality} for m in measurements]


if __name__ == "__main__":
    import json
    from simulator import HealthSimulator

    base = _to_rows(HealthSimulator.simulate_normal_day("AV-01", 20, seed=1))
    recent = _to_rows(HealthSimulator.simulate_deterioration("AV-01", 20, seed=3))
    print(json.dumps(analyze_crew("AV-01", base, recent), indent=2))
