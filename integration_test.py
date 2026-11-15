"""Integration test: simulator -> validator -> baseline -> anomaly detector -> API output."""

import json

from validator import DataValidator
from baselines import BaselineCalculator
from anomaly import AnomalyDetector
from simulator import HealthSimulator
from api_interface import analyze_crew, _to_rows

print("=== FULL INTEGRATION TEST ===\n")
SIGS = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "temperature_core")

normal = HealthSimulator.simulate_normal_day("AV-01", 20, seed=1)
data = {
    "normal": normal,
    "fatigue": HealthSimulator.simulate_fatigue("AV-01", 20, seed=2),
    "deterioration": HealthSimulator.simulate_deterioration("AV-01", 20, seed=3),
    "failure": HealthSimulator.simulate_sensor_failure("AV-01", 10, seed=4),
}
for name, rows in data.items():
    ok = sum(DataValidator.validate_measurement(m)[0] for m in rows)
    print(f"Validator: {ok}/{len(rows)} {name} readings valid")

calc = BaselineCalculator()
for s in SIGS:
    calc.calculate_baseline("AV-01", s, normal)

print()
status = {}
for name, rows in data.items():
    status[name] = AnomalyDetector(calc).detect_anomaly("AV-01", rows)["overall_status"]
    print(f"{name:14s} -> {status[name]}")

assert status["normal"] == "GREEN"
assert status["fatigue"] == "AMBER"
assert status["deterioration"] == "RED"
assert status["failure"] == "GRAY"

out = analyze_crew("AV-01", _to_rows(normal), _to_rows(data["deterioration"]))
json.dumps(out)  # must be JSON-serializable
assert out["status"] == "RED" and "MS-01" in out["rules_triggered"]

print("\nAll 4 scenario assertions passed; API output is valid JSON.")
