"""Loads the threshold configuration (config/thresholds_v1.json).
All alert values live in that file so they can be edited without touching the code."""

import json
import os

_HERE = os.path.dirname(os.path.abspath(__file__))


def load_thresholds(path=None):
    candidates = [path] if path else [
        os.path.join(_HERE, "config", "thresholds_v1.json"),
        os.path.join(_HERE, "thresholds_v1.json"),
    ]
    for p in candidates:
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("thresholds_v1.json not found (looked in config/ and project folder)")
