"""Synthetic data simulator: fake crew health data for testing (1 reading per minute)."""

import random
from datetime import datetime, timedelta, timezone

from measurement_schema import Measurement

START = datetime(2026, 10, 9, 8, 30, tzinfo=timezone.utc)


def _ts(i):
    return (START + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _make(crew_id, i, vals, quality=0.95):
    units = {"heart_rate": "bpm", "spo2": "%", "respiratory_rate": "breaths/min",
             "systolic_bp": "mmHg", "temperature_core": "C"}
    return [Measurement(crew_id, _ts(i), sig, v, units[sig], quality)
            for sig, v in vals.items()]


class HealthSimulator:
    @staticmethod
    def simulate_normal_day(crew_id, num_samples=20, seed=None):
        """Scenario 1: normal. HR ~75, SpO2 ~96.5, RR ~16, SBP ~118, core temp ~36.7."""
        rng = random.Random(seed)
        out = []
        for i in range(num_samples):
            out += _make(crew_id, i, {
                "heart_rate": _clamp(75 + rng.gauss(0, 2), 40, 180),
                "spo2": _clamp(96.5 + rng.gauss(0, 0.5), 80, 100),
                "respiratory_rate": _clamp(16 + rng.gauss(0, 0.7), 8, 30),
                "systolic_bp": _clamp(118 + rng.gauss(0, 3), 80, 180),
                "temperature_core": _clamp(36.7 + rng.gauss(0, 0.1), 35, 40),
            })
        return out

    @staticmethod
    def simulate_fatigue(crew_id, num_samples=20, seed=None):
        """Scenario 2: fatigue/illness watch. Heart rate in the amber band, SpO2 only
        mildly low (an ADVISORY, not an alert). Expected: AMBER, no escalation."""
        rng = random.Random(seed)
        out = []
        for i in range(num_samples):
            out += _make(crew_id, i, {
                "heart_rate": _clamp(120 + rng.gauss(0, 3), 40, 180),
                "spo2": _clamp(94.0 + rng.gauss(0, 0.2), 80, 100),
                "respiratory_rate": _clamp(17 + rng.gauss(0, 0.7), 8, 30),
                "systolic_bp": _clamp(122 + rng.gauss(0, 3), 80, 180),
                "temperature_core": _clamp(36.9 + rng.gauss(0, 0.1), 35, 40),
            })
        return out

    @staticmethod
    def simulate_deterioration(crew_id, num_samples=20, seed=None):
        """Scenario 3: multi-signal deterioration. Heart rate AND respiratory rate both in
        their amber bands for 10+ minutes. Expected: RED via rule MS-01."""
        rng = random.Random(seed)
        out = []
        for i in range(num_samples):
            out += _make(crew_id, i, {
                "heart_rate": _clamp(118 + rng.gauss(0, 3), 40, 180),
                "spo2": _clamp(95.0 + rng.gauss(0, 0.3), 80, 100),
                "respiratory_rate": _clamp(22 + rng.gauss(0, 0.6), 8, 30),
                "systolic_bp": _clamp(118 + rng.gauss(0, 3), 80, 180),
                "temperature_core": _clamp(36.9 + rng.gauss(0, 0.1), 35, 40),
            })
        return out

    @staticmethod
    def simulate_sensor_failure(crew_id, num_samples=10, seed=None):
        """Scenario 4: sensor fell off. Impossible values, very low quality. Expected: GRAY."""
        rng = random.Random(seed)
        out = []
        for i in range(num_samples):
            out += _make(crew_id, i, {"heart_rate": 0.0}, quality=0.1)
            out += _make(crew_id, i, {"spo2": rng.choice([50, 150, 200])}, quality=0.05)
        return out


if __name__ == "__main__":
    for name, fn in [("Normal Day", HealthSimulator.simulate_normal_day),
                     ("Fatigue", HealthSimulator.simulate_fatigue),
                     ("Deterioration", HealthSimulator.simulate_deterioration),
                     ("Sensor Failure", HealthSimulator.simulate_sensor_failure)]:
        print(f"=== {name} ===")
        for m in fn("AV-01", 2):
            print(m)
        print()
