#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Format implementation results as a console / Markdown table."""

def _cells(res):
    s = f"{res.get('lut', 0):>6} {res.get('ff', 0):>6} {res.get('bram', 0):>4} {res.get('dsp', 0):>4}"
    fmax = res.get("pnr", {}).get("fmax_mhz")
    return s + (f" {fmax:>6.0f}" if fmax is not None else f" {'-':>6}")

def console(device, results, violations):
    print(f"\n=== {device} implementation: {len(results)} modules ===")
    print(f"{'module':18} {'lut':>6} {'ff':>6} {'bram':>4} {'dsp':>4} {'fmax':>6}  status")
    for name, res in results.items():
        bad = violations.get(name, [])
        status = "ok" if not bad else "BUDGET: " + "; ".join(bad)
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
