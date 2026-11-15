# Space Health Pioneers
**Explainable, On-Board Health Monitoring Software for Astronauts Beyond Earth Orbit**  
*NASA Space Apps Challenge 2026*

## Overview
**Space Health Pioneers** is a rule-based, explainable biometric monitoring engine designed for deep-space missions where real-time medical support from Earth is delayed. Instead of relying on terrestrial medical cutoffs that trigger false alarms in microgravity, the system adapts to each astronaut's personal in-flight baseline and cross-references multiple physiological and environmental signals.

## Key Features
* **Phased In-Flight Baselines:** Accounts for early microgravity adaptation (fluid shift, space motion sickness, and space anemia) across three phases: *Calibrating* (Days 1–7), *Provisional* (Days 8–21), and *Stable* (Day 22+).
* **Statistical & Clinical Safety Nets:** Combines personal deviation detection (`robust z-score >= 2.0` via MAD) with fixed clinical limits derived from NEWS2 and adjusted for chronic *space fever* (+1.0 °C basal offset).
* **Multi-Signal Escalation (`MS-01` to `MS-07`):** Detects complex risks such as localized CO₂ pockets (`MS-02`), sleep/circadian fatigue (`MS-03`), and cardiac decoupling during exercise using the Rate Pressure Product (`MS-07`).
* **Sensor Quality Gate (`GRAY` State):** Isolates low-quality wearable readings, motion artifacts, and flatlines so bad sensor contact is never mistaken for a medical emergency or a false reassuring `GREEN`.

## Repository Structure
* `anomaly.py`, `baselines.py`, `thresholds.py`, `validator.py`: Core rule-based detection and statistical baseline engine.
* `api_interface.py` & `measurement_schema.py`: Data validation and telemetry ingestion interfaces.
* `simulator.py`, `stress_test.py`, `integration_test.py`: Synthetic crew simulation and stress-testing suite (300 simulated crew members).
* `config/thresholds_v1.json`: Editable threshold and multi-signal configuration parameters.
* `tests/`: Automated unit and pipeline validation suite (93 passing tests).
* `SpaceHealthPioneers Biomedical ResearchReport.pdf` & `SpaceHealthPioneers Sleep and Fatigue ResearchReport.pdf`: Full biomedical literature review, physiological rationale, and NASA data references.

## Quick Start
```bash
pip install -r requirements.txt
pytest
python simulator.py
```

