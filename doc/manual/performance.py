#!/usr/bin/env python3
#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Generate the tables of the Performance appendix (D_performance.md).

The tables are rebuilt from the checked-in tool results, without running any tool:

- `impl/budgets.json`: resources and fmax of every implementation configuration, per device;
- `impl/modules.py`: the factory of each configuration (to find its block family) and the
  strict target set (`TARGET_CLOSED`), read with `ast` (no Migen, no NumPy needed);
- `char/results.json` and `char/budgets.json`: the quality metrics measured on the golden
  models and their gate bounds.

Only the text between the `performance.py <region> begin/end` markers of D_performance.md is
written (regions `impl` and `quality`).

    python3 doc/manual/performance.py           # rewrite the generated part
    python3 doc/manual/performance.py --check   # fail if it is stale (CI)
"""

import ast
import json
import sys
from pathlib import Path

HERE    = Path(__file__).resolve().parent
ROOT    = HERE.parent.parent
TARGET  = HERE/"D_performance.md"
# Generated regions of D_performance.md: "<!-- performance.py <name> begin -->" ... "end -->".
REGIONS = ("impl", "quality")

DEVICES = [("ecp5", "ECP5"), ("xilinx", "Artix-7"), ("xilinx_au", "Artix UltraScale+")]

# Block families, in the order of the manual (package directory -> title, anchor suffix).
FAMILIES = [
    ("generation", "Generation"),
    ("mixing",     "Mixing"),
    ("correction", "Correction"),
    ("filter",     "Filters"),
    ("rate",       "Rate change"),
    ("level",      "Level control"),
    ("analysis",   "Analysis"),
    ("comm",       "Communications"),
    ("stream",     "Stream utilities"),
    ("frontend",   "Front ends"),
    ("gen",        "Generated IP cores"),
    ("motor",      "Motor control"),
    ("audio",      "Audio"),
    ("radar",      "Radar and sonar"),
    ("image",      "Image"),
]
ANCHORS = {"gen": "ip"}

# Plain-language names of the characterization metrics (char/specs.py keys).
METRICS = {
    "enob_bits":               ("ENOB", "bits"),
    "noise_floor_dbfs":        ("Noise floor", "dBFS"),
    "sfdr_db":                 ("SFDR, swept increments", "dB"),
    "sfdr_lut_exact_db":       ("SFDR, LUT-exact increments", "dB"),
    "image_rejection_db":      ("Image rejection", "dB"),
    "passband_ripple_db":      ("Passband ripple", "dB"),
    "stopband_atten_db":       ("Stopband attenuation", "dB"),
    "overshoot_pct":           ("Overshoot", "%"),
    "settling_samples":        ("Settling time", "samples"),
    "steady_state_error_pct":  ("Residual level error", "%"),
    "imd3_dbc":                ("IMD3", "dBc"),
    "evm_below_threshold_pct": ("EVM below threshold", "%"),
    "papr_reduction_db":       ("PAPR reduction", "dB"),
    "dc_rejection_db":         ("DC rejection", "dB"),
    "sidelobe_level_db":       ("Peak sidelobe attenuation", "dB"),
}
CIC_DROOP = "droop_err_r"  # droop_err_r<R>_n<N>_db: one metric per (decimation, stages).

# impl/modules.py reading (ast) ------------------------------------------------------------------

def read_modules():
    """Return (registry, families, target_closed) from impl/modules.py without importing it."""
    tree = ast.parse((ROOT/"impl"/"modules.py").read_text(encoding="utf-8"))
    class_family = {}   # LiteDSP class name -> package directory.
    functions    = {}   # Factory/helper name -> FunctionDef.
    registry     = {}   # Configuration name -> factory name.
    lists        = {}
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("litedsp."):
            family = node.module.split(".")[1]
            for alias in node.names:
                class_family[alias.asname or alias.name] = family
        elif isinstance(node, ast.FunctionDef):
            functions[node.name] = node
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "REGISTRY":
                for k, v in zip(node.value.keys, node.value.values):
                    registry[k.value] = v.id
            elif isinstance(node.value, ast.List):
                lists[name] = [e.value for e in node.value.elts]

    def family_of(func, depth=0):
        calls = [n.func.id for n in ast.walk(func)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
        for c in calls:
            if c in class_family:
                return class_family[c]
        for c in calls:
            if c in functions and depth < 2:
                f = family_of(functions[c], depth + 1)
                if f:
                    return f
        return None

    families = {}
    for name, factory in registry.items():
        family = family_of(functions[factory])
        if family is None:
            raise SystemExit(f"performance.py: no LiteDSP class found for {name!r}")
        families[name] = family
    return registry, families, set(lists.get("TARGET_CLOSED", []))

# Markdown ---------------------------------------------------------------------------------------

# A cell holding only "-" is read by pandoc as an empty bullet list: write words instead.
def fmax_cell(entry):
    if entry is None:
        return "not run"
    if "fmax_min" not in entry:
        return "synth"
    raw = entry.get("fmax_mhz")
    return f"{raw:.1f}" if raw is not None else "no fmax"

def synth_only(entries):
    """True when a family has ECP5 synthesis results only (no route, no Xilinx run)."""
    return all(set(v) == {"ecp5"} and "fmax_min" not in v["ecp5"] for v in entries)

def resources_cell(entry):
    return " / ".join(str(entry.get(k, 0)) for k in ("lut", "ff", "bram", "dsp"))

def impl_tables(budgets, families, closed):
    out = []
    # Coverage summary.
    out += ["### Configurations per device {#perf-counts}", ""]
    out += ["| Device | Synthesized | Routed (fmax) | Target set |",
            "|--------------------------|-------------|---------------|------------|"]
    for dev, title in DEVICES:
        synth  = sum(1 for v in budgets.values() if dev in v)
        routed = sum(1 for v in budgets.values() if dev in v and "fmax_min" in v[dev])
        target = sum(1 for k, v in budgets.items() if dev in v and k in closed)
        out.append(f"| {title} | {synth} | {routed} | {target} |")
    out.append("")
    known   = {family for family, _ in FAMILIES}
    unknown = sorted(k for k, f in families.items() if k in budgets and f not in known)
    if unknown:
        raise SystemExit(f"performance.py: configurations of an unknown family: {unknown}")
    for family, title in FAMILIES:
        names = sorted(k for k in budgets if families.get(k) == family)
        if not names:
            continue
        anchor = ANCHORS.get(family, family)
        out += [f"### {title} {{#perf-{anchor}}}", ""]
        if synth_only([budgets[n] for n in names]):
            out += ["ECP5 synthesis only.", ""]
            out += ["| Configuration | LUT | FF | BRAM | DSP |",
                    "|--------------------------------------|----------|----------|----------|----------|"]
            for name in names:
                e = budgets[name]["ecp5"]
                cells = [name + (" *" if name in closed else "")] + [str(e.get(k, 0)) for k in ("lut", "ff", "bram", "dsp")]
                out.append("| " + " | ".join(cells) + " |")
            out.append("")
            continue
        out += ["| Configuration | ECP5 LUT / FF / BRAM / DSP | ECP5 MHz | Artix-7 MHz | AU+ MHz |",
                "|------------------------------------|--------------------|----------|----------|----------|"]
        for name in names:
            v     = budgets[name]
            label = name + (" *" if name in closed else "")
            out.append(f"| {label} | {resources_cell(v['ecp5'])} | {fmax_cell(v.get('ecp5'))} | "
                       f"{fmax_cell(v.get('xilinx'))} | {fmax_cell(v.get('xilinx_au'))} |")
        out.append("")
    return out

def char_bound(entry, tolerance=0.03, abs_tolerance=0.01):
    # Same rule as char/budgets.py bound(): baseline +/- max(3 %, 0.01), direction-aware.
    margin = max(tolerance*abs(entry["value"]), abs_tolerance)
    if entry["direction"] == "min":
        return f">= {entry['value'] - margin:.2f}"
    return f"<= {entry['value'] + margin:.2f}"

def metric_name(metric):
    if metric.startswith(CIC_DROOP):
        r, n = metric[len(CIC_DROOP):-len("_db")].split("_n")
        return f"Droop error, R={r}, N={n}", "dB"
    if metric not in METRICS:
        raise SystemExit(f"performance.py: no name for characterization metric {metric!r}")
    return METRICS[metric]

def char_table(results, budgets):
    out = ["| Block | Metric | Unit | Measured | Gate |",
           "|-------------|------------------------------|---------|----------|----------|"]
    for block in sorted(results):
        for metric in sorted(results[block], key=lambda m: metric_name(m)[0]):
            name, unit = metric_name(metric)
            entry = budgets.get(block, {}).get(metric)
            gate  = char_bound(entry) if entry else "none"
            out.append(f"| {block} | {name} | {unit} | {results[block][metric]:.3f} | {gate} |")
    out.append("")
    return out

def generate():
    budgets = json.loads((ROOT/"impl"/"budgets.json").read_text(encoding="utf-8"))
    _, families, closed = read_modules()
    missing = sorted(k for k in budgets if k not in families)
    if missing:
        raise SystemExit(f"performance.py: configurations not in impl/modules.py: {missing}")
    results = json.loads((ROOT/"char"/"results.json").read_text(encoding="utf-8"))
    cbudget = json.loads((ROOT/"char"/"budgets.json").read_text(encoding="utf-8"))
    return {
        "impl":    impl_tables(budgets, families, closed),
        "quality": char_table(results, cbudget),
    }

def markers(name):
    return (f"<!-- performance.py {name} begin: generated, do not edit -->",
            f"<!-- performance.py {name} end -->")

def main(argv):
    text   = TARGET.read_text(encoding="utf-8")
    tables = generate()
    new    = text
    for name in REGIONS:
        begin, end = markers(name)
        if begin not in new or end not in new:
            print(f"performance.py: {name} markers not found in {TARGET.name}")
            return 1
        head, rest = new.split(begin, 1)
        _, tail    = rest.split(end, 1)
        new = head + "\n".join([begin, ""] + tables[name] + [end]) + tail
    if "--check" in argv:
        if new != text:
            print("D_performance.md is stale: run python3 doc/manual/performance.py")
            return 1
        print("D_performance.md is up to date.")
        return 0
    TARGET.write_text(new, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
