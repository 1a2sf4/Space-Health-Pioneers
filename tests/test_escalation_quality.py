"""Tests for the alert rules in the Biomedical Threshold Specification:
persistence windows, absolute limits, advisories, multi-signal rules, baseline phases
by mission day, and the data-quality gate."""

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from measurement_schema import Measurement
from baselines import BaselineCalculator
from anomaly import AnomalyDetector
from simulator import HealthSimulator

SIGS = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "temperature_core")
T0 = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)


def ts(minute, second=0):
    return (T0 + timedelta(minutes=minute, seconds=second)).strftime("%Y-%m-%dT%H:%M:%SZ")


def rd(signal, value, minute, second=0, quality=0.95):
    return Measurement("AV-01", ts(minute, second), signal, value, "x", quality)


def series(signal, values, start=0):
    """One reading per minute."""
    return [rd(signal, v, start + i) for i, v in enumerate(values)]


def detector(with_baseline=True):
    calc = BaselineCalculator()
    if with_baseline:
        base = HealthSimulator.simulate_normal_day("AV-01", 20, seed=1)
        for s in SIGS:
            calc.calculate_baseline("AV-01", s, base)
    return AnomalyDetector(calc)


def wiggle(center, n, amp=0.3):
    return [center + (amp if i % 2 else -amp) * ((i % 3) + 1) / 3 for i in range(n)]


# ---------- persistence windows ----------
def test_amber_needs_five_minutes():
    short = series("heart_rate", wiggle(120, 4))     # 3 minutes of span
    long_ = series("heart_rate", wiggle(120, 7))     # 6 minutes of span
    assert detector().detect_anomaly("AV-01", short)["overall_status"] == "GREEN"
    assert detector().detect_anomaly("AV-01", long_)["overall_status"] == "AMBER"


def test_red_needs_fifteen_seconds_not_one_reading():
    one = [rd("spo2", 88, 0)]
    two = [rd("spo2", 88, 0), rd("spo2", 87.6, 1)]
    assert detector().detect_anomaly("AV-01", one)["overall_status"] == "GREEN"
    r = detector().detect_anomaly("AV-01", two)
    assert r["overall_status"] == "RED" and r["escalation"] == "absolute_limit"


def test_red_limit_at_131_is_inclusive():
    r = detector().detect_anomaly("AV-01", series("heart_rate", [131, 131.4, 130.9]))
    assert r["overall_status"] == "RED"


def test_single_spike_does_not_alert():
    vals = [75, 75.4, 75.8, 125, 75.2, 75.6, 75.1]
    r = detector().detect_anomaly("AV-01", series("heart_rate", vals))
    assert r["overall_status"] == "GREEN"
    assert any("spike" in n for n in r["data_notes"])


def test_alert_clears_when_signal_recovers():
    vals = wiggle(120, 8) + wiggle(75, 3)
    assert detector().detect_anomaly("AV-01", series("heart_rate", vals))["overall_status"] == "GREEN"


# ---------- personal baseline (amber) ----------
def test_baseline_deviation_gives_amber_below_absolute_band():
    # HR 95 is not in the 111-130 band, but is far above this person's baseline
    r = detector().detect_anomaly("AV-01", series("heart_rate", wiggle(95, 8)))
    assert r["overall_status"] == "AMBER"
    assert r["alerts"][0]["rule"] == "AMBER-BASELINE"


def test_no_baseline_rules_without_a_baseline():
    r = detector(with_baseline=False).detect_anomaly("AV-01", series("heart_rate", wiggle(95, 8)))
    assert r["overall_status"] == "GREEN"


def test_spo2_drop_of_four_points_is_amber():
    calc = BaselineCalculator()
    calc.calculate_baseline("AV-01", "spo2", [rd("spo2", 99, i) for i in range(10)])
    r = AnomalyDetector(calc).detect_anomaly(
        "AV-01", series("spo2", [94.8, 94.9, 94.7, 95.0, 94.9, 94.8, 95.0]))
    assert r["overall_status"] == "AMBER" and r["alerts"][0]["rule"] == "AMBER-DROP"


# ---------- baseline phases by mission day ----------
def test_calibrating_phase_turns_baseline_rules_off():
    data = series("heart_rate", wiggle(95, 8))
    early = detector().detect_anomaly("AV-01", data, mission_day=3)
    later = detector().detect_anomaly("AV-01", data, mission_day=30)
    assert early["overall_status"] == "GREEN" and early["baseline_phase"] == "calibrating"
    assert later["overall_status"] == "AMBER" and later["baseline_phase"] == "stable"


def test_fixed_limits_still_active_while_calibrating():
    r = detector().detect_anomaly("AV-01", series("spo2", [88, 87.5, 88.2]), mission_day=2)
    assert r["overall_status"] == "RED"


def test_provisional_phase_label():
    r = detector().detect_anomaly("AV-01", series("heart_rate", wiggle(75, 6)), mission_day=15)
    assert r["baseline_phase"] == "provisional"


# ---------- advisories (never official alerts) ----------
def test_spo2_94_is_advisory_only():
    r = detector().detect_anomaly("AV-01", series("spo2", [94.0, 94.2, 93.9, 94.1, 94.0, 94.2, 94.1]))
    assert r["overall_status"] == "GREEN"
    assert r["advisories"] and r["advisories"][0]["signal"] == "spo2"


def test_advisory_does_not_count_for_multi_signal_rules():
    data = series("heart_rate", wiggle(120, 14)) + series("spo2", [94.0, 94.1] * 7)
    r = detector().detect_anomaly("AV-01", data)
    assert r["overall_status"] == "AMBER"
    assert "MS-01" not in r["rules_triggered"]


def test_low_grade_fever_is_advisory_relative_to_baseline():
    r = detector().detect_anomaly("AV-01", series("temperature_core", [37.3, 37.35, 37.28] * 3))
    assert r["overall_status"] == "GREEN" and r["advisories"]


# ---------- core temperature: ground vs in-flight limits ----------
def test_inflight_temperature_limits_from_day_8():
    data = series("temperature_core", [36.6, 36.65, 36.55] * 3)
    assert detector().detect_anomaly("AV-01", data)["overall_status"] == "GREEN"
    r = detector().detect_anomaly("AV-01", data, mission_day=10)
    assert r["overall_status"] == "AMBER"


# ---------- multi-signal rules ----------
def test_ms01_two_ambers_for_ten_minutes_is_red():
    data = series("heart_rate", wiggle(120, 12)) + series("respiratory_rate", wiggle(22, 12, 0.2))
    r = detector().detect_anomaly("AV-01", data)
    assert r["overall_status"] == "RED" and "MS-01" in r["rules_triggered"]


def test_two_ambers_for_only_six_minutes_stay_amber():
    data = series("heart_rate", wiggle(120, 7)) + series("respiratory_rate", wiggle(22, 7, 0.2))
    r = detector().detect_anomaly("AV-01", data)
    assert r["overall_status"] == "AMBER" and "MS-01" not in r["rules_triggered"]


def test_ms02_low_spo2_with_rising_respiratory_rate_is_red():
    data = series("spo2", wiggle(93, 7, 0.2)) + series("respiratory_rate", wiggle(22, 7, 0.2))
    r = detector().detect_anomaly("AV-01", data)
    assert r["overall_status"] == "RED" and "MS-02" in r["rules_triggered"]


def test_ms04_amber_plus_symptom_is_red():
    data = series("heart_rate", wiggle(120, 7))
    assert detector().detect_anomaly("AV-01", data)["overall_status"] == "AMBER"
    r = detector().detect_anomaly("AV-01", data, symptom_reported=True)
    assert r["overall_status"] == "RED" and "MS-04" in r["rules_triggered"]


def test_ms04_symptom_alone_does_not_alert():
    data = series("heart_rate", wiggle(75, 7))
    assert detector().detect_anomaly("AV-01", data, symptom_reported=True)["overall_status"] == "GREEN"


def test_ms05_news2_aggregate_of_five_is_red():
    # HR 95 (1) + RR 11 (1) + SpO2 95 (1) + SBP 100 (2, amber) = 5
    data = (series("heart_rate", wiggle(95, 8, 0.2)) + series("respiratory_rate", wiggle(11, 8, 0.2))
            + series("spo2", wiggle(95, 8, 0.2)) + series("systolic_bp", wiggle(100, 8, 0.2)))
    r = detector(with_baseline=False).detect_anomaly("AV-01", data)
    assert r["news2_total"] >= 5
    assert r["overall_status"] == "RED" and "MS-05" in r["rules_triggered"]


# ---------- data-quality gate ----------
def test_flatlined_sensor_is_gray():
    r = detector().detect_anomaly("AV-01", series("heart_rate", [75.0] * 6))
    assert r["overall_status"] == "GRAY"
    assert any("flat-line" in g for g in r["gray_reasons"])


def test_sudden_onset_is_not_mistaken_for_spike():
    vals = [75, 75.4, 75.8, 75.2, 75.6, 125, 124, 126, 125.5, 124.5, 126.5]
    r = detector().detect_anomaly("AV-01", series("heart_rate", vals))
    assert r["overall_status"] == "AMBER"    # 125 is in the 111-130 amber band; the jump stays, so it is not a spike
    assert not any("spike" in n for n in r["data_notes"])


# ---------- robustness: found during the final audit ----------
def test_nan_value_is_rejected_by_validator_and_detector():
    from validator import DataValidator
    bad = rd("heart_rate", float("nan"), 0)
    assert not DataValidator.validate_measurement(bad)[0]
    r = detector().detect_anomaly("AV-01", [rd("heart_rate", float("nan"), i) for i in range(3)])
    assert r["overall_status"] == "GRAY"


def test_empty_input_is_gray_not_green():
    r = detector().detect_anomaly("AV-01", [])
    assert r["overall_status"] == "GRAY"
    assert "no valid vital-sign data" in r["explanation"]


def test_result_does_not_depend_on_reading_order():
    data = series("heart_rate", wiggle(120, 8))
    a = detector().detect_anomaly("AV-01", data)["overall_status"]
    b = detector().detect_anomaly("AV-01", data[::-1])["overall_status"]
    assert a == b == "AMBER"


def test_sensor_dropout_during_alert_turns_that_signal_gray():
    data = series("heart_rate", wiggle(120, 8)) + [rd("heart_rate", 0.0, 8, quality=0.1)]
    r = detector().detect_anomaly("AV-01", data)
    assert r["overall_status"] == "GRAY"
    assert any("last confirmed state: AMBER" in g for g in r["gray_reasons"])


def test_other_signals_still_alert_when_one_sensor_fails():
    data = (series("heart_rate", wiggle(120, 8))
            + series("spo2", [96.5, 96.4, 96.6, 96.5], start=0) + [rd("spo2", 0.0, 4, quality=0.1)])
    r = detector().detect_anomaly("AV-01", data)
    assert r["overall_status"] == "AMBER"
    assert any(a["signal"] == "heart_rate" for a in r["alerts"])


def test_bad_checkin_data_does_not_turn_vitals_gray():
    data = series("heart_rate", wiggle(75, 8)) + [rd("sleep", 6, 0, quality=0.1)]
    assert detector().detect_anomaly("AV-01", data)["overall_status"] == "GREEN"


def test_ms05_ignores_a_single_instant():
    r = detector().detect_anomaly("AV-01", [rd("heart_rate", 135, 0), rd("respiratory_rate", 26, 0)])
    assert r["overall_status"] == "GREEN" and "MS-05" not in r["rules_triggered"]


def test_ms02_needs_respiratory_rate_clearly_above_this_persons_baseline():
    calc = BaselineCalculator()
    for sig, vals in (("respiratory_rate", [22, 22.3, 21.8, 22.1, 21.9, 22.2, 22, 21.7, 22.4, 22.1]),
                      ("spo2", [96.5, 96.4] * 5)):
        calc.calculate_baseline("AV-01", sig, [rd(sig, v, i) for i, v in enumerate(vals)])
    data = series("spo2", wiggle(93, 7, 0.2)) + series("respiratory_rate", wiggle(22, 7, 0.2))
    r = AnomalyDetector(calc).detect_anomaly("AV-01", data)
    assert r["overall_status"] == "AMBER" and "MS-02" not in r["rules_triggered"]


def test_baseline_needs_minimum_samples():
    calc = BaselineCalculator()
    assert calc.calculate_baseline("AV-01", "heart_rate", [rd("heart_rate", 80, 0)]) is None


def test_fuzz_random_and_garbage_input_never_crashes():
    import math
    import random
    rng = random.Random(42)
    signals = list(SIGS) + ["skin_temp", "hrv_rmssd", "sleep", "unknown_signal"]
    weird = [0.0, -5.0, 1e9, float("nan"), float("inf"), 75.0, 120.0, 95.0]
    for _ in range(1500):
        n = rng.randint(0, 40)
        data = []
        for _i in range(n):
            ts_ = ts(rng.randint(0, 30)) if rng.random() > 0.05 else "not-a-time"
            v = rng.choice(weird) if rng.random() < 0.3 else rng.uniform(0, 250)
            q = rng.choice([0.05, 0.5, 0.75, 0.95, 1.0])
            data.append(Measurement("AV-01", ts_, rng.choice(signals), v, "x", q))
        r = detector().detect_anomaly("AV-01", data, mission_day=rng.choice([None, 1, 5, 10, 40]),
                                      symptom_reported=rng.random() < 0.3)
        assert r["overall_status"] in ("GREEN", "AMBER", "RED", "GRAY")
        assert isinstance(r["explanation"], str) and r["explanation"]


# ---------- conformance with Table 6 of the Biomedical Threshold Specification ----------
import pytest

# (signal, value, mission_day, expected status). No baseline is used, so only the fixed
# limits are tested. Each value is held for 8 minutes (long enough for amber AND red).
TABLE_6 = [
    # heart rate: amber 111-130, red <=40 or >=131
    ("heart_rate", 110, None, "GREEN"), ("heart_rate", 111, None, "AMBER"),
    ("heart_rate", 130, None, "AMBER"), ("heart_rate", 131, None, "RED"),
    ("heart_rate", 41, None, "GREEN"), ("heart_rate", 40, None, "RED"),
    # SpO2: advisory 94, amber 92-93, red <=91
    ("spo2", 95, None, "GREEN"), ("spo2", 94, None, "GREEN"),
    ("spo2", 93, None, "AMBER"), ("spo2", 92, None, "AMBER"), ("spo2", 91, None, "RED"),
    # respiratory rate: amber 21-24, red <=8 or >=25
    ("respiratory_rate", 20, None, "GREEN"), ("respiratory_rate", 21, None, "AMBER"),
    ("respiratory_rate", 24, None, "AMBER"), ("respiratory_rate", 25, None, "RED"),
    ("respiratory_rate", 9, None, "GREEN"), ("respiratory_rate", 8, None, "RED"),
    # systolic BP: amber 91-100, red <=90 or >=220
    ("systolic_bp", 101, None, "GREEN"), ("systolic_bp", 100, None, "AMBER"),
    ("systolic_bp", 91, None, "AMBER"), ("systolic_bp", 90, None, "RED"),
    ("systolic_bp", 219, None, "GREEN"), ("systolic_bp", 220, None, "RED"),
    # core temperature, Earth and mission days 1-7: amber 35.1-36.0 / 38.1-39.0, red <=35.0 / >=39.1
    ("temperature_core", 36.1, None, "GREEN"), ("temperature_core", 36.0, None, "AMBER"),
    ("temperature_core", 35.1, None, "AMBER"), ("temperature_core", 35.0, None, "RED"),
    ("temperature_core", 38.0, None, "GREEN"), ("temperature_core", 38.1, None, "AMBER"),
    ("temperature_core", 39.0, None, "AMBER"), ("temperature_core", 39.1, None, "RED"),
    ("temperature_core", 36.6, 3, "GREEN"),
    # core temperature in flight from day 8: amber 36.1-37.0 / 38.6-39.5, red <=36.0 / >=39.6
    ("temperature_core", 37.1, 10, "GREEN"), ("temperature_core", 37.0, 10, "AMBER"),
    ("temperature_core", 36.1, 10, "AMBER"), ("temperature_core", 36.0, 10, "RED"),
    ("temperature_core", 38.5, 10, "GREEN"), ("temperature_core", 38.6, 10, "AMBER"),
    ("temperature_core", 39.5, 10, "AMBER"), ("temperature_core", 39.6, 10, "RED"),
]


@pytest.mark.parametrize("signal,value,day,expected", TABLE_6)
def test_table6_thresholds_at_exact_boundaries(signal, value, day, expected):
    wobble = 0.02 if signal == "temperature_core" else 0.04   # avoids the flat-line rule, same rounding
    data = [rd(signal, value + (wobble if i % 2 else -wobble), i) for i in range(8)]
    r = detector(with_baseline=False).detect_anomaly("AV-01", data, mission_day=day)
    assert r["overall_status"] == expected, (signal, value, day, r["explanation"])
