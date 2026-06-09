#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-module / per-device resource budgets (the 'expected usage' manifest) + the gate check."""

import os
import json

PATH      = os.path.join(os.path.dirname(os.path.abspath(__file__)), "budgets.json")
TOLERANCE = 1.15                      # Measured resources may exceed the baseline by up to 15%.
METRICS   = ["lut", "ff", "bram", "dsp"]

def load():
    if os.path.exists(PATH):
        with open(PATH) as f:
            return json.load(f)
    return {}

def save(data):
    with open(PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)

def update(device, results):
    """Record measured ``results`` (name -> resource dict) as the new baseline for ``device``."""
    data = load()
    for name, res in results.items():
        entry = data.setdefault(name, {}).setdefault(device, {})
        for m in METRICS:
            if m in res:
                entry[m] = res[m]
        if res.get("pnr", {}).get("fmax_mhz"):
            entry["fmax_min"] = round(res["pnr"]["fmax_mhz"]*0.85, 1)   # 15% fmax margin.
    save(data)

def check(device, name, res):
    """Return a list of human-readable budget violations for one module (empty = within budget)."""
    data = load().get(name, {}).get(device)
    if not data:
        return [f"no budget recorded for {name}/{device}"]
    bad = []
    for m in METRICS:
        if m in data and m in res and res[m] > data[m]*TOLERANCE:
            bad.append(f"{m} {res[m]} > {data[m]}*{TOLERANCE:g}")
    fmax = res.get("pnr", {}).get("fmax_mhz")
    if data.get("fmax_min") and fmax is not None and fmax < data["fmax_min"]:
        bad.append(f"fmax {fmax:.1f} < {data['fmax_min']} MHz")
    return bad
