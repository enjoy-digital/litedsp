#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-block quality budgets (the 'guaranteed characterization' manifest) + the gate check.

Same load/save/update/check shape as ``impl/budgets.py``, adapted to quality metrics: each
budget entry carries a ``direction`` so the check knows which way a change is a violation —
``"min"`` metrics (SFDR, ENOB, attenuation, rejection, IMD3, sidelobe level) fail by
dropping below ``baseline - tolerance``, ``"max"`` metrics (ripple, droop error, settling
time, steady-state error, noise floor) by rising above ``baseline + tolerance``. The
measurements are deterministic (fixed stimulus, pure NumPy), so the few-percent tolerance
only absorbs benign numeric drift (NumPy/BLAS versions); real regressions move whole dBs.
"""

import os
import json

PATH          = os.path.join(os.path.dirname(os.path.abspath(__file__)), "budgets.json")
TOLERANCE     = 0.03                  # Measured metrics may degrade vs the baseline by up to 3%...
ABS_TOLERANCE = 0.01                  # ...with an absolute floor for near-zero baselines (e.g.
                                      # CIC droop errors of ~0.001 dB).

def load():
    if os.path.exists(PATH):
        with open(PATH) as f:
            return json.load(f)
    return {}

def save(data):
    with open(PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")

def update(results, directions):
    """Record measured ``results`` (block -> metric -> value) as the new baseline."""
    data = load()
    for block, mets in results.items():
        entry = data.setdefault(block, {})
        for m, v in mets.items():
            entry[m] = {"value": round(float(v), 3), "direction": directions[block][m]}
    save(data)

def bound(entry):
    """Guaranteed bound implied by a budget entry (baseline ± tolerance, direction-aware)."""
    margin = max(TOLERANCE*abs(entry["value"]), ABS_TOLERANCE)
    return entry["value"] - margin if entry["direction"] == "min" else entry["value"] + margin

def check(block, results_block):
    """Return a list of human-readable budget violations for one block (empty = within budget)."""
    data = load().get(block)
    if not data:
        return [f"no budget recorded for {block}"]
    bad = []
    for m, entry in data.items():
        if m not in results_block:
            bad.append(f"{m}: budgeted but not measured")
            continue
        v, b = results_block[m], bound(entry)
        if entry["direction"] == "min" and v < b:
            bad.append(f"{m} {v:.3f} < {b:.3f} (baseline {entry['value']})")
        elif entry["direction"] == "max" and v > b:
            bad.append(f"{m} {v:.3f} > {b:.3f} (baseline {entry['value']})")
    return bad
