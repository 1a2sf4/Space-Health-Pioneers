# Astro Vitals by Space Health Pioneers

**Explainable, on-board health monitoring software for astronauts beyond Earth orbit**
NASA Space Apps Challenge 2026

## Overview

Astro Vitals (developed by team Space Health Pioneers) is a rule-based, explainable health monitoring engine for deep-space missions, where real-time medical support from Earth is delayed. It takes raw wearable readings and decides whether a crew member is fine (GREEN), needs watching (AMBER), needs urgent attention (RED), or whether the sensor data simply cannot be trusted (GRAY). Instead of applying a single terrestrial range to everyone, it compares each astronaut with their own baseline, keeps fixed clinical limits as a safety net, and explains every alert in plain English: what changed, compared to what, and for how long.

## How it works

Readings pass through five stages: **validate → quality gate → personal baseline → detect → explain**.

1. **Data quality gate.** Each reading is checked for a sensor quality score of at least 0.7, a physically valid range, stale data (older than 5 minutes), flat-lined sensors (same value for 60 s or more), physically impossible jumps and isolated spikes that revert immediately. A signal whose latest reading is unusable is reported as GRAY, never as a medical alert or a falsely reassuring GREEN.
2. **Personal baseline.** Median and median absolute deviation (MAD) of the crew member's own readings; deviation is measured as a robust z-score, z = 0.6745 · (x − median) / MAD.
3. **Two detection layers in parallel, the more severe one wins.**
   - *Absolute safety net (NEWS2-based):* for example SpO₂ ≤ 91%, heart rate ≤ 40 or ≥ 131 bpm, respiratory rate ≤ 8 or ≥ 25/min, systolic BP ≤ 90 or ≥ 220 mmHg. RED after 15 seconds of valid data; AMBER bands after 5 minutes.
   - *Personal baseline:* AMBER when a signal deviates by |z| ≥ 2 (with a minimum absolute change, e.g. 8 bpm), or when SpO₂ drops 4 points or more below baseline.
4. **Advisories.** SpO₂ of 94% or a core temperature 0.5 °C or more above baseline prompts a sensor check and repeat measurement. Advisories never count as alerts or toward escalation.
5. **Multi-signal escalation to RED.**
   - **MS-01:** two or more signals in amber together for 10 minutes or more.
   - **MS-02:** low SpO₂ while respiratory rate is rising (possible respiratory problem or CO₂ build-up).
   - **MS-04:** an amber signal plus a symptom reported in the daily check-in.
   - **MS-05:** combined NEWS2-style early-warning score of 5 or more.
6. **Mission phases.** Days 1–7 (*calibrating*): baseline rules off, fixed limits only, while the body adapts to microgravity. Days 8–21: *provisional* baseline. Day 22 onward: *stable*. From day 8, core temperature uses in-flight limits shifted upward (normal 37.1–38.5 °C), because resting body temperature rises in flight.
7. **Explanation.** Every result includes the status, the rules that fired, a plain-English reason, the NEWS2 total, the baseline phase and the thresholds version, as JSON ready for a dashboard.

## Repository structure

| File | Purpose |
|---|---|
| `anomaly.py` | Detection engine: quality gate, persistence windows, two detection layers, advisories, multi-signal rules, mission phases and explanations |
| `baselines.py` | Personal baseline (median + MAD) and robust z-score |
| `validator.py` | Rejects physically impossible or low-quality readings |
| `thresholds.py` | Loads the threshold configuration |
| `config/thresholds_v1.json` | All thresholds and rules in one editable, versioned file (thresholds v1.1) |
| `measurement_schema.py` | Measurement format and accepted signals |
| `api_interface.py` | `analyze_crew()`: JSON-style input, JSON-serializable output for a backend or dashboard |
| `simulator.py` | Synthetic crew data for four scenarios |
| `stress_test.py` | 300 random simulated crew members across the four scenarios |
| `integration_test.py` | End-to-end check: simulator → validator → baseline → detector → API output |
| `tests/` | Automated test suite (pytest) |

## Quick start

Requires Python 3.9 or later.

```
pip install -r requirements.txt
pytest                      # 93 automated tests
python stress_test.py       # 300 simulated crew members
python integration_test.py  # end-to-end pipeline check
python anomaly.py           # four demo scenarios with explanations
python api_interface.py     # example JSON output for the dashboard
```

## Validation

- **93 automated tests pass.** They check every threshold at its exact boundary and cover persistence windows, personal baseline, advisories, multi-signal rules MS-01, MS-02, MS-04 and MS-05, mission phases, in-flight temperature limits and the data quality gate.
- **Fuzz test:** 1,500 random and malformed inputs, with no crash.
- **Stress test:** 300 simulated crew members, zero misclassifications across four scenarios:

| Scenario | Simulated data | Expected result |
|---|---|---|
| Normal day | Heart rate ~75 bpm, SpO₂ ~96.5%, normal breathing, BP and temperature | GREEN |
| Single-signal watch | Heart rate ~120 bpm (amber band), SpO₂ ~94% (advisory only) | AMBER |
| Multi-signal deterioration | Heart rate and respiratory rate both in amber for 10+ minutes | RED (MS-01) |
| Sensor failure | Heart rate reads 0, impossible SpO₂ values, very low sensor quality | GRAY |

## Limitations

- All data is synthetic; real astronaut vital signs are not publicly available in real time.
- No NASA document defines amber or red cutoffs for astronauts. The fixed limits are based on NEWS2, designed for hospital patients, so they are a safety net and not validated astronaut limits.
- Every threshold requires review by a qualified medical adviser before any real-world use. This is a decision-support prototype, not a medical device.
- Pulse oximeters are less accurate on darker skin and under poor perfusion. Low-quality SpO₂ readings are shown as GRAY, but some residual bias remains.
- Skin temperature and HRV are validated but used for trends only; check-in and cabin context data (sleep, fatigue, CO₂, radiation) are accepted but do not change the vital-sign status.

## Next steps

- Exercise mode with rate-pressure product monitoring for cardiac decoupling (MS-07).
- Multi-day trend rule using HRV and sleep (MS-03), tested on public wearable datasets.
- Acknowledgement timers (MS-06) and trend alerts for skin temperature and HRV.
- Baselines that adapt slowly during a mission and freeze during an active alert.
- Medical adviser review and recalibration for lower cabin pressure on exploration missions.

## Scientific basis

Thresholds and design decisions come from the team's *Biomedical Research Report and Alert Threshold Specification* and *Sleep and Fatigue Research Report*, based on the NASA Human Research Program, the Canadian Space Agency (Bio-Monitor, CARDIOBREATH) and the Royal College of Physicians' National Early Warning Score 2 (NEWS2).
