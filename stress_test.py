"""Stress test: 300 random simulated crew members. Run:  python stress_test.py
Each one gets a baseline from a random normal day; the detector must then classify
a fresh normal day (GREEN), fatigue (AMBER), deterioration (RED) and sensor failure (GRAY)."""

from simulator import HealthSimulator
from baselines import BaselineCalculator
from anomaly import AnomalyDetector

RUNS = 300
SIGS = ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "temperature_core")
expected = {"normal": "GREEN", "fatigue": "AMBER", "deterioration": "RED", "failure": "GRAY"}
wrong = {k: 0 for k in expected}

for s in range(RUNS):
    calc = BaselineCalculator()
    base = HealthSimulator.simulate_normal_day("AV-01", 20, seed=s)
    for sig in SIGS:
        calc.calculate_baseline("AV-01", sig, base)
    runs = {
        "normal": HealthSimulator.simulate_normal_day("AV-01", 20, seed=1000 + s),
        "fatigue": HealthSimulator.simulate_fatigue("AV-01", 20, seed=s),
        "deterioration": HealthSimulator.simulate_deterioration("AV-01", 20, seed=s),
        "failure": HealthSimulator.simulate_sensor_failure("AV-01", 10, seed=s),
    }
    for name, rows in runs.items():
        got = AnomalyDetector(calc).detect_anomaly("AV-01", rows)["overall_status"]
        wrong[name] += got != expected[name]

print(f"Runs: {RUNS}")
for name in expected:
    print(f"{name:14s} (expected {expected[name]}): misclassified {wrong[name]}")
