"""Data schema for Space Health Pioneers measurements."""


class Measurement:
    """One health measurement from a sensor."""

    VALID_SIGNALS = {
        # Real-time wearable
        "heart_rate": "bpm",
        "systolic_bp": "mmHg",
        "respiratory_rate": "breaths/min",
        "spo2": "%",
        "temperature_core": "C",
        "skin_temp": "C",
        "hrv_rmssd": "ms",
        "activity": "steps",
        # Daily check-in
        "sleep": "hours",
        "fatigue": "1-10",
        "mood": "1-10",
        "workload": "1-10",
        # Environmental context
        "radiation_dose": "mSv",
        "cabin_co2": "ppm",
    }

    def __init__(self, crew_id, timestamp, signal, value, unit, quality):
        self.crew_id = crew_id
        self.timestamp = timestamp
        self.signal = signal
        self.value = value
        self.unit = unit
        self.quality = quality

    def __repr__(self):
        return (f"Measurement({self.crew_id}, {self.signal}="
                f"{self.value:.1f}{self.unit}, quality={self.quality})")


if __name__ == "__main__":
    print(Measurement("AV-01", "2026-10-09T08:30:00Z", "heart_rate", 82.0, "bpm", 0.95))
