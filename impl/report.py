#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Format implementation results as a console / Markdown table.

Run ``python3 impl/report.py`` to regenerate ``doc/resources.md`` from the checked-in
reference numbers (``impl/budgets.json``, updated by ``impl/run.py`` sweeps).
"""

def _cells(res):
    s = f"{res.get('lut', 0):>6} {res.get('ff', 0):>6} {res.get('bram', 0):>4} {res.get('dsp', 0):>4}"
    fmax = res.get("pnr", {}).get("fmax_mhz")
    return s + (f" {fmax:>6.0f}" if fmax is not None else f" {'-':>6}")

def console(device, results, violations, target_misses=None):
    target_misses = target_misses or {}
    print(f"\n=== {device} implementation: {len(results)} modules ===")
    print(f"{'module':18} {'lut':>6} {'ff':>6} {'bram':>4} {'dsp':>4} {'fmax':>6}  status")
    for name, res in results.items():
        bad = violations.get(name, [])
        misses = target_misses.get(name, [])
        status = "ok" if not bad else "BUDGET: " + "; ".join(bad)
        if misses:
            status += "; TARGET: " + "; ".join(misses)
        print(f"{name:18} {_cells(res)}  {status}")

def markdown(all_results):
    """all_results: {device: {name: res}}. Returns a Markdown table string."""
    devices = list(all_results.keys())
    names = sorted(set().union(*[set(r) for r in all_results.values()])) if all_results else []
    hdr = ["module"] + [f"{d} (LUT/FF/BRAM/DSP/Fmax)" for d in devices]
    out = ["| " + " | ".join(hdr) + " |", "|" + "|".join(["---"]*len(hdr)) + "|"]
    for n in names:
        row = [n]
        for d in devices:
            r = all_results[d].get(n)
            if r is None:
                row.append("-")
            else:
                fmax = r.get("pnr", {}).get("fmax_mhz")
                row.append(f"{r.get('lut',0)}/{r.get('ff',0)}/{r.get('bram',0)}/{r.get('dsp',0)}/"
                           + (f"{fmax:.0f}" if fmax else "-"))
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out) + "\n"

# Budgets -> doc/resources.md ----------------------------------------------------------------------

_DEVICE_LABELS = {"ecp5": "ECP5 (Yosys/nextpnr)", "xilinx": "Artix-7 (Vivado)"}

def budgets_markdown(budgets):
    """Render the checked-in per-block budgets as a Markdown resource table."""
    devices = sorted({d for entry in budgets.values() for d in entry})
    hdr = ["module"] + [f"{_DEVICE_LABELS.get(d, d)} LUT/FF/BRAM/DSP/Fmax floor/target" for d in devices]
    out = [
        "# Resource usage per block",
        "",
        "Reference numbers from the FPGA implementation sweeps (`impl/run.py`, default block",
        "parameters, 16-bit datapaths). Regenerate with `python3 impl/report.py` after a sweep",
        "updates `impl/budgets.json`; CI checks new results against these budgets.",
        "",
        "| " + " | ".join(hdr) + " |",
        "|" + "|".join(["---"]*len(hdr)) + "|",
    ]
    for name in sorted(budgets):
        row = [f"`{name}`"]
        for d in devices:
            r = budgets[name].get(d)
            if r is None:
                row.append("-")
                continue
            floor  = r.get("fmax_min")
            target = r.get("fmax_target")
            timing = "-" if floor is None else f"{floor:.1f}"
            if target is not None:
                timing += f"/{target:.1f}"
            row.append(f"{r.get('lut', 0)}/{r.get('ff', 0)}/{r.get('bram', 0)}/{r.get('dsp', 0)}/"
                       + timing)
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out) + "\n"

if __name__ == "__main__":
    import os
    import sys
    import json
    import argparse
    parser = argparse.ArgumentParser(description="Regenerate doc/resources.md from impl/budgets.json.")
    parser.add_argument("--check", action="store_true", help="Fail if doc/resources.md is stale (CI).")
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "impl", "budgets.json")) as f:
        budgets = json.load(f)
    path    = os.path.join(root, "doc", "resources.md")
    content = budgets_markdown(budgets)
    if args.check:
        current = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
        if current != content:
            print("doc/resources.md is stale — regenerate with python3 impl/report.py")
            sys.exit(1)
        print("doc/resources.md is up to date.")
        sys.exit(0)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Generated: {path} ({len(budgets)} modules)")
