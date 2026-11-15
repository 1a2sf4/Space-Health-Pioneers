"""Baseline calculation: what is 'normal' for each crew member (median + MAD)."""

import statistics

from thresholds import load_thresholds


class BaselineCalculator:
    def __init__(self, config=None):
        cfg = config or load_thresholds()
        # Smallest spread (MAD) we trust per signal; stops a very tight baseline from
        # turning ordinary wiggles into huge z-scores (added by Data/AI Lead).
        self.min_mad = cfg["baseline"]["min_mad"]
        self.min_samples = cfg["baseline"].get("min_samples", 5)
        self.baselines = {}  # {crew_id: {signal: {...}}}

    @staticmethod
    def calculate_mad(values):
        """Median Absolute Deviation: robust alternative to standard deviation."""
        if not values:
            return 0.0
        med = statistics.median(values)
        return statistics.median([abs(v - med) for v in values])

    def calculate_baseline(self, crew_id, signal, measurements):
        values = [m.value for m in measurements
                  if m.crew_id == crew_id and m.signal == signal]
        if len(values) < self.min_samples:
            return None  # too few readings to call anything "normal"
        baseline = {
            "signal": signal,
            "median": statistics.median(values),
            "mad": self.calculate_mad(values),
            "samples": len(values),
            "min": min(values),
            "max": max(values),
        }
        self.baselines.setdefault(crew_id, {})[signal] = baseline
        return baseline

    def get_baseline(self, crew_id, signal):
        return self.baselines.get(crew_id, {}).get(signal)

    def calculate_deviation(self, crew_id, signal, current_value):
        """Robust z-score: z = 0.6745 * (x - median) / MAD (handbook formula)."""
        baseline = self.get_baseline(crew_id, signal)
        if baseline is None:
            return {"error": "No baseline available"}

        median, mad = baseline["median"], baseline["mad"]
        floor = self.min_mad.get(signal, 0.01 * abs(median))
        mad_safe = max(mad, floor, 1e-6)
        z = 0.6745 * (current_value - median) / mad_safe

        deviation = current_value - median
        pct = (deviation / median * 100) if median else 0.0
        return {
            "z_score": round(z, 2),
            "deviation": round(deviation, 2),
            "percent_change": round(pct, 2),
            "baseline_median": median,
            "current_value": current_value,
        }


if __name__ == "__main__":
    from simulator import HealthSimulator

    print("=== Testing Baseline Calculator ===\n")
    normal = HealthSimulator.simulate_normal_day("AV-01", 20, seed=1)
    fatigue = HealthSimulator.simulate_fatigue("AV-01", 20, seed=2)
    calc = BaselineCalculator()
    for sig in ("heart_rate", "spo2", "respiratory_rate", "systolic_bp", "temperature_core"):
        b = calc.calculate_baseline("AV-01", sig, normal)
        print(f"{sig:18s} baseline {b['median']:.1f}  (MAD {b['mad']:.2f}, {b['samples']} samples)")
    print()
    n_hr = [m.value for m in normal if m.signal == "heart_rate"][0]
    f_hr = [m.value for m in fatigue if m.signal == "heart_rate"][0]
    for label, v in [("Normal day", n_hr), ("Fatigue", f_hr)]:
        d = calc.calculate_deviation("AV-01", "heart_rate", v)
        print(f"{label}: HR={v:.1f} -> deviation {d['deviation']} bpm "
              f"({d['percent_change']}%), z-score {d['z_score']}")
