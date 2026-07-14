#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Measure LiteDSP block quality metrics on the golden models and gate on quality budgets.

    python3 char/run_char.py                       # All blocks, gate vs char/budgets.json.
    python3 char/run_char.py --block nco           # Single block.
    python3 char/run_char.py --update              # Refresh the budget baseline from this run.
    python3 char/run_char.py --report              # + regenerate doc/characterization.md.
    python3 char/run_char.py --check-report        # Fail if doc/characterization.md is stale (CI).

Every run rewrites ``char/results.json`` (block -> metric -> measured value). The report is
generated deterministically from ``char/results.json`` + ``char/budgets.json`` only, so
``--check-report`` regenerates it from the checked-in files and diffs — no measurement.
"""

import os
import sys
import json
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from char import budgets
from char.specs import SPECS, DIRECTIONS, DESCRIPTIONS, unit

RESULTS_PATH = os.path.join(ROOT, "char", "results.json")
REPORT_PATH  = os.path.join(ROOT, "doc",  "characterization.md")

# Measurement ----------------------------------------------------------------------------------------

def measure(blocks):
    """Evaluate the characterization specs for ``blocks`` (block -> metric -> value)."""
    results = {}
    for name in blocks:
        results[name] = {m: round(float(v), 3) for m, v in SPECS[name]().items()}
    return results

def load_results():
    with open(RESULTS_PATH) as f:
        return json.load(f)

def save_results(results):
    data = load_results() if os.path.exists(RESULTS_PATH) else {}
    data.update(results)
    with open(RESULTS_PATH, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")

# Console Report -------------------------------------------------------------------------------------

def console(results, violations):
    print(f"\n=== quality characterization: {len(results)} blocks ===")
    print(f"{'block':10} {'metric':26} {'unit':>8} {'measured':>10}  status")
    for name, mets in results.items():
        bad = set(v.split()[0] for v in violations.get(name, []) if " " in v)
        for m, v in mets.items():
            status = "ok" if m not in bad else "BUDGET"
            print(f"{name:10} {m:26} {unit(m):>8} {v:>10.3f}  {status}")
        for v in violations.get(name, []):
            print(f"{'':10} !! {v}")

# Markdown Report ------------------------------------------------------------------------------------

def markdown(results, budget_data):
    """Render results + budgets as doc/characterization.md (deterministic)."""
    out = [
        "# DSP quality characterization",
        "",
        "Datasheet-grade quality metrics for the LiteDSP blocks, measured by `char/run_char.py`",
        "on the NumPy golden models (`test/models.py`; the CORDIC through a Migen simulation).",
        "The golden models are held bit-exact / SNR-equivalent to the RTL by the co-simulation",
        "tests in `test/` and `sim/`, so these numbers characterize the gateware itself.",
        "",
        "*Guaranteed* is the checked-in baseline (`char/budgets.json`) with the gate tolerance",
        f"applied ({budgets.TOLERANCE:.0%} of the baseline, {budgets.ABS_TOLERANCE:g} absolute",
        "minimum, direction-aware); CI fails if a measurement crosses it. Regenerate with",
        "`python3 char/run_char.py --update --report` after a deliberate quality change.",
        "",
    ]
    for name in SPECS:
        if name not in results:
            continue
        out += [f"## {name}", "", DESCRIPTIONS[name], ""]
        out += ["| Metric | Unit | Measured | Guaranteed |", "|---|---|---|---|"]
        for m, v in results[name].items():
            entry = budget_data.get(name, {}).get(m)
            if entry is None:
                guaranteed = "-"
            else:
                sign = ">=" if entry["direction"] == "min" else "<="
                guaranteed = f"{sign} {budgets.bound(entry):.2f}"
            out.append(f"| `{m}` | {unit(m)} | {v:.2f} | {guaranteed} |")
        out.append("")
    return "\n".join(out)

# Main -----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteDSP quality characterization (measure + budget gate).")
    parser.add_argument("--block",        default=None,         help="Single block name (default: all).")
    parser.add_argument("--update",       action="store_true",  help="Rewrite the budget baseline from this run.")
    parser.add_argument("--no-gate",      action="store_true",  help="Don't fail on budget violations (measure only).")
    parser.add_argument("--report",       action="store_true",  help="Regenerate doc/characterization.md.")
    parser.add_argument("--check-report", action="store_true",  help="Fail if doc/characterization.md is stale (CI).")
    args = parser.parse_args()

    if args.check_report:
        content = markdown(load_results(), budgets.load())
        current = open(REPORT_PATH, encoding="utf-8").read() if os.path.exists(REPORT_PATH) else ""
        if current != content:
            print("doc/characterization.md is stale — regenerate with python3 char/run_char.py --report")
            return 1
        print("doc/characterization.md is up to date.")
        return 0

    names = [args.block] if args.block else list(SPECS)
    results = measure(names)
    save_results(results)

    violations = {}
    if not args.update:
        violations = {name: budgets.check(name, results[name]) for name in names}
    console(results, violations)

    if args.update:
        budgets.update(results, DIRECTIONS)
        print(f"\n[budgets] baseline updated ({len(results)} blocks)")
    if args.report:
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write(markdown(load_results(), budgets.load()))
        print(f"[report] {REPORT_PATH}")

    failed = any(violations.values()) and not args.no_gate
    return 1 if (failed and not args.update) else 0

if __name__ == "__main__":
    sys.exit(main())
