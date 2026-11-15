"""Core tests: validator, baselines, config, the demo scenarios and the API.
Run from the project folder:  python -m pytest"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from measurement_schema import Measurement
from validator import DataValidator
from baselines import BaselineCalculator
from anomaly import AnomalyDetector
from simulator import HealthSimulator
from thresholds import load_thresholds
from api_interface import analyze_crew, measurements_from_dicts, _to_rows

SIGS = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "temperature_core")


def m(signal, value, quality=0.95):
    return Measurement("AV-01", "2026-10-09T08:30:00Z", signal, value, "x", quality)


def make_detector():
    calc = BaselineCalculator()
    base = HealthSimulator.simulate_normal_day("AV-01", 20, seed=1)
    for s in SIGS:
        calc.calculate_baseline("AV-01", s, base)
    return AnomalyDetector(calc)


# ---------- config ----------
def test_config_loads_and_has_version():
    cfg = load_thresholds()
    assert cfg["version"].startswith("thresholds-")
    assert cfg["signals"]["heart_rate"]["red_high"] == 131
    assert cfg["persistence"]["acute_red_seconds"] == 15


# ---------- validator ----------
def test_validator_accepts_good_reading():
    assert DataValidator.validate_measurement(m("heart_rate", 82))[0]


def test_validator_rejects_impossible_value():
    assert not DataValidator.validate_measurement(m("heart_rate", 250))[0]


def test_validator_rejects_low_quality():
    assert not DataValidator.validate_measurement(m("spo2", 97, quality=0.3))[0]


def test_validator_keeps_elevated_but_possible_hr():
    assert DataValidator.validate_measurement(m("heart_rate", 125))[0]


def test_validator_rejects_unknown_signal():
    assert not DataValidator.validate_measurement(m("mystery_signal", 1))[0]


def test_validator_uses_spec_ranges():
    assert DataValidator.validate_measurement(m("spo2", 55))[0]            # valid 50-100
    assert not DataValidator.validate_measurement(m("spo2", 45))[0]
    assert not DataValidator.validate_measurement(m("temperature_core", 44))[0]  # valid 30-43


# ---------- baselines ----------
def test_mad_known_values():
    assert BaselineCalculator.calculate_mad([1, 2, 3, 4, 100]) == 1


def test_baseline_median_resists_outlier():
    calc = BaselineCalculator()
    rows = [m("heart_rate", v) for v in [74, 75, 76, 75, 74, 200]]
    assert calc.calculate_baseline("AV-01", "heart_rate", rows)["median"] == 75


def test_zscore_matches_handbook_formula():
    calc = BaselineCalculator()
    rows = [m("heart_rate", v) for v in [70, 72, 74, 76, 78]]  # median 74, MAD 2
    calc.calculate_baseline("AV-01", "heart_rate", rows)
    z = calc.calculate_deviation("AV-01", "heart_rate", 84)["z_score"]
    assert z == pytest.approx(0.6745 * (84 - 74) / 2, abs=0.01)


def test_deviation_without_baseline_returns_error():
    assert "error" in BaselineCalculator().calculate_deviation("AV-01", "heart_rate", 80)


# ---------- the demo scenarios ----------
def test_normal_day_is_green():
    r = make_detector().detect_anomaly("AV-01", HealthSimulator.simulate_normal_day("AV-01", 20, seed=5))
    assert r["overall_status"] == "GREEN"
    assert r["news2_total"] == 0


def test_fatigue_is_amber_with_spo2_advisory_and_no_escalation():
    r = make_detector().detect_anomaly("AV-01", HealthSimulator.simulate_fatigue("AV-01", 20, seed=5))
    assert r["overall_status"] == "AMBER"
    assert [a["signal"] for a in r["alerts"]] == ["heart_rate"]
    assert r["escalation"] == "single_signal"


def test_deterioration_is_red_via_ms01():
    r = make_detector().detect_anomaly("AV-01", HealthSimulator.simulate_deterioration("AV-01", 20, seed=5))
    assert r["overall_status"] == "RED"
    assert "MS-01" in r["rules_triggered"]


def test_sensor_failure_is_gray_not_medical():
    r = make_detector().detect_anomaly("AV-01", HealthSimulator.simulate_sensor_failure("AV-01", 10, seed=5))
    assert r["overall_status"] == "GRAY"
    assert r["alerts"] == []
    assert "NOT a medical alert" in r["explanation"]


# ---------- API interface ----------
def test_api_output_is_json_serializable():
    base = _to_rows(HealthSimulator.simulate_normal_day("AV-01", 20, seed=1))
    recent = _to_rows(HealthSimulator.simulate_deterioration("AV-01", 20, seed=2))
    out = analyze_crew("AV-01", base, recent)
    json.dumps(out)
    assert out["status"] == "RED"
    assert out["data_quality"]["total"] == 100
    assert out["thresholds_version"].startswith("thresholds-")
    assert "heart_rate" in out["baselines"]


def test_api_rejects_rows_with_missing_fields():
    with pytest.raises(ValueError):
        measurements_from_dicts([{"crew_id": "AV-01", "value": 80}])


def test_api_bad_sensor_data_cannot_poison_baseline():
    good = _to_rows(HealthSimulator.simulate_normal_day("AV-01", 20, seed=1))
    junk = _to_rows(HealthSimulator.simulate_sensor_failure("AV-01", 10, seed=1))
    out = analyze_crew("AV-01", good + junk,
                       _to_rows(HealthSimulator.simulate_normal_day("AV-01", 20, seed=9)))
    assert abs(out["baselines"]["heart_rate"]["median"] - 75) < 3
    assert out["status"] == "GREEN"


def test_api_rejects_other_crew_members_in_recent_rows():
    base = _to_rows(HealthSimulator.simulate_normal_day("AV-01", 20, seed=1))
    other = _to_rows(HealthSimulator.simulate_normal_day("AV-02", 5, seed=2))
    with pytest.raises(ValueError):
        analyze_crew("AV-01", base, other)


def test_validator_rejects_nan_and_infinity():
    assert not DataValidator.validate_measurement(m("heart_rate", float("nan")))[0]
    assert not DataValidator.validate_measurement(m("heart_rate", float("inf")))[0]
