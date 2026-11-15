"""Data validation: reject physically impossible or untrustworthy data.
Valid ranges come from config/thresholds_v1.json. These are PHYSICAL limits;
deciding whether a value is concerning is the job of anomaly.py."""

import math

from measurement_schema import Measurement
from thresholds import load_thresholds


class DataValidator:
    CONFIG = load_thresholds()

    @staticmethod
    def validate_measurement(measurement, config=None):
        """Returns (is_valid, reason)."""
        cfg = config or DataValidator.CONFIG
        if measurement.signal not in Measurement.VALID_SIGNALS:
            return False, f"Unknown signal: {measurement.signal}"

        if not math.isfinite(measurement.value):
            return False, "Value is not a finite number"

        sig = cfg["signals"].get(measurement.signal)
        if sig:
            lo, hi = sig["valid"]
            if measurement.value < lo or measurement.value > hi:
                return False, (f"{measurement.signal} out of valid range: "
                               f"{measurement.value} (valid: {lo}-{hi})")

        if measurement.quality < cfg["quality"]["min_quality"]:
            return False, (f"Data quality too low: {measurement.quality} "
                           f"(need >= {cfg['quality']['min_quality']})")

        if not measurement.timestamp:
            return False, "Missing timestamp"
        return True, "Valid measurement"


if __name__ == "__main__":
    print("=== Testing Data Validator ===\n")
    ts = "2026-10-09T08:30:00Z"
    tests = [
        ("Good HR", Measurement("AV-01", ts, "heart_rate", 82.0, "bpm", 0.95)),
        ("HR 250 (impossible)", Measurement("AV-01", ts, "heart_rate", 250.0, "bpm", 0.95)),
        ("Low quality SpO2", Measurement("AV-01", ts, "spo2", 96.0, "%", 0.3)),
        ("Elevated HR 120 (still valid)", Measurement("AV-01", ts, "heart_rate", 120.0, "bpm", 0.95)),
        ("Core temp 36.7", Measurement("AV-01", ts, "temperature_core", 36.7, "C", 0.95)),
    ]
    for name, m in tests:
        ok, reason = DataValidator.validate_measurement(m)
        print(f"{'PASS' if ok else 'REJECT'} | {name}: {reason}")
