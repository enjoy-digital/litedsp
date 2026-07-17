#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-module/device synthesis/P&R baselines, regression floors and timing targets."""

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
        f.write("\n")

def _flow_entry(entry, flow):
    """Return a flow-scoped baseline, falling back to the legacy flat schema."""
    return entry.get(flow, entry)

def _refresh_summary(entry):
    """Maintain the flat compatibility view consumed by GUI/docs.

    Post-route resources are preferred when present; otherwise synthesis resources are shown.
    Timing is always sourced from P&R.  The flow-scoped dictionaries remain authoritative for
    budget checks, so pre-opt synthesis and post-route utilization can differ without fighting
    over one ceiling.
    """
    resources = entry.get("pnr") or entry.get("synth") or entry
    for metric in METRICS:
        entry.pop(metric, None)
        if metric in resources:
            entry[metric] = resources[metric]
    timing = entry.get("pnr", {})
    for metric in ("fmax_mhz", "fmax_min"):
        entry.pop(metric, None)
        if metric in timing:
            entry[metric] = timing[metric]

def migrate(data):
    """Upgrade legacy flat entries to flow-scoped baselines in place.

    Existing timed entries originated from a P&R update and seed both scopes initially; a later
    synthesis sweep replaces the synth scope with its true pre-opt utilization. Untimed entries
    are synthesis-only. The flat summary is retained as a generated compatibility view.
    """
    for devices in data.values():
        for entry in devices.values():
            legacy = {metric: entry[metric] for metric in METRICS if metric in entry}
            if legacy:
                entry.setdefault("synth", dict(legacy))
                if "fmax_mhz" in entry or "fmax_min" in entry:
                    pnr = entry.setdefault("pnr", dict(legacy))
                    for metric in ("fmax_mhz", "fmax_min"):
                        if metric in entry:
                            pnr.setdefault(metric, entry[metric])
            _refresh_summary(entry)
    return data

def missing(device, names, flow="synth"):
    """Return registry names that have no baseline for ``device``/``flow`` yet."""
    data = load()
    out = []
    for name in names:
        entry = data.get(name, {}).get(device)
        if entry is None or (flow not in entry and not any(m in entry for m in METRICS)):
            out.append(name)
    return out

def update(device, results, flow="synth"):
    """Record measured ``results`` as the ``device``/``flow`` baseline."""
    if flow not in ("synth", "pnr"):
        raise ValueError(f"unsupported implementation flow: {flow}")
    data = load()
    for name, res in results.items():
        devices = data.setdefault(name, {})
        entry   = devices.setdefault(device, {})
        if "fmax_target" not in entry:
            sibling_targets = {d["fmax_target"] for key, d in devices.items()
                if key != device and "fmax_target" in d}
            if len(sibling_targets) == 1:
                entry["fmax_target"] = sibling_targets.pop()
        scoped = entry.setdefault(flow, {})
        for m in METRICS:
            if m in res:
                scoped[m] = res[m]
        if flow == "pnr" and res.get("pnr", {}).get("fmax_mhz"):
            measured = res["pnr"]["fmax_mhz"]
            scoped["fmax_mhz"] = round(measured, 1)             # Measurement provenance.
            scoped["fmax_min"] = round(measured*0.85, 1)        # 15% gate margin.
        _refresh_summary(entry)
    save(data)

def check(device, name, res, flow="synth"):
    """Return budget violations for one module/flow (empty = within budget)."""
    entry = load().get(name, {}).get(device)
    if not entry:
        return [f"no budget recorded for {name}/{device}/{flow}"]
    data = _flow_entry(entry, flow)
    bad = []
    for m in METRICS:
        if m in data and m in res and res[m] > data[m]*TOLERANCE:
            bad.append(f"{m} {res[m]} > {data[m]}*{TOLERANCE:g}")
    fmax = res.get("pnr", {}).get("fmax_mhz")
    if data.get("fmax_min") and fmax is not None and fmax < data["fmax_min"]:
        bad.append(f"fmax {fmax:.1f} < {data['fmax_min']} MHz")
    return bad

def check_target(device, name, res):
    """Return timing-target misses for one module (separate from regression failures).

    ``fmax_min`` remains the noise-tolerant CI regression floor. ``fmax_target`` is the
    engineering objective: normal implementation runs report misses, while callers decide
    whether to gate on them (``impl/run.py --target-gate`` does).
    """
    entry = load().get(name, {}).get(device)
    if not entry or entry.get("fmax_target") is None:
        return []
    fmax = res.get("pnr", {}).get("fmax_mhz")
    if fmax is not None and fmax < entry["fmax_target"]:
        return [f"fmax {fmax:.1f} < target {entry['fmax_target']} MHz"]
    return []
