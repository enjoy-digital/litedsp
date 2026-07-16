#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Verilator line coverage of the co-simulation suite: how much RTL the harness exercises.

Every ``sim/cosim_specs.py`` block is re-run through the generic co-simulation harness
(``sim/run_blocks.py``) with Verilator's ``--coverage-line`` instrumentation; the testbench
dumps ``coverage.dat`` per block (in its build dir), which is converted to lcov format with
``verilator_coverage --write-info`` and reduced to covered/total line-coverage points
(``DA:`` records) over the block's generated Verilog. KNOWN_FAIL blocks contribute normally:
coverage measures exercised lines, not data match.

    python3 sim/run_coverage.py                # All table entries, report-only (exit 0).
    python3 sim/run_coverage.py nco gain       # A selection.
    python3 sim/run_coverage.py --min 85       # Gate: exit 1 if a non-waived block is < 85%.

Waivers: ``sim/coverage_waivers.json`` maps block name -> reason string for documented
exclusions from the ``--min`` gate (e.g. reset-only paths unreachable under the cosim
stimulus). Waived blocks are still measured and shown in the table (marked ``waived``),
they just never fail the gate. Keep the file pure JSON; document the *why* in the reason.

Results land in ``coverage.json`` (per-block pct + covered/total points + overall;
``--output`` overrides the path, default: repo root).
"""

import os
import sys
import json
import shutil
import argparse
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sim.verilator   import have_verilator
from sim.run_blocks  import run_block
from sim.cosim_specs import SPECS, check_coverage

WAIVERS_PATH = os.path.join(ROOT, "sim", "coverage_waivers.json")

# Aggregation --------------------------------------------------------------------------------------

def line_coverage(block_dir):
    """(covered, total) line-coverage points of a block's coverage.dat (lcov ``DA:`` records).

    ``verilator_coverage --write-info`` folds the point counters per source line; only the
    generated ``.v`` sources are instrumented, so all ``DA:`` records belong to the DUT (the
    ``SF:`` filter is belt-and-braces against future multi-file builds).
    """
    dat  = os.path.join(block_dir, "coverage.dat")
    info = os.path.join(block_dir, "coverage.info")
    subprocess.check_call(["verilator_coverage", "--write-info", info, dat],
        stdout=subprocess.DEVNULL)
    covered, total, in_verilog = 0, 0, False
    with open(info) as f:
        for line in f:
            if line.startswith("SF:"):
                in_verilog = line.strip().endswith(".v")
            elif line.startswith("DA:") and in_verilog:
                total   += 1
                covered += int(line.strip().split(",")[1]) > 0
    return covered, total

# Runner ---------------------------------------------------------------------------------------------

def cover_block(name, build_dir):
    """Co-simulate ``name`` with coverage instrumentation and aggregate its coverage.dat.

    Returns ``(covered, total)`` (``(0, 0)`` when no coverage.dat was produced). A failing run
    (e.g. output-count timeout) still wrote its counters before exiting, so aggregation is
    attempted regardless of the run verdict.
    """
    bd = os.path.join(build_dir, name)
    try:
        run_block(name, coverage=True, build_dir=build_dir)
    except Exception as e:
        print(f"{name:18s} cosim run failed ({e}); aggregating any partial coverage")
    if not os.path.exists(os.path.join(bd, "coverage.dat")):
        return 0, 0
    return line_coverage(bd)

# Console Report -------------------------------------------------------------------------------------

def console(results, waivers, min_pct):
    print(f"\n=== Verilator line coverage: {len(results)} blocks ===")
    print(f"{'block':18} {'points':>11} {'coverage':>9}  status")
    for name, (covered, total) in results.items():
        pct = 100.0*covered/total if total else 0.0
        if name in waivers:
            status = f"waived ({waivers[name]})"
        elif total == 0:
            status = "NO DATA"
        elif min_pct is not None and pct < min_pct:
            status = f"BELOW MIN ({min_pct:.1f}%)"
        else:
            status = "ok"
        print(f"{name:18} {f'{covered}/{total}':>11} {pct:8.1f}%  {status}")
    covered = sum(c for c, _ in results.values())
    total   = sum(t for _, t in results.values())
    print(f"{'overall':18} {f'{covered}/{total}':>11} {100.0*covered/total if total else 0.0:8.1f}%")

# Main -----------------------------------------------------------------------------------------------

def main(argv=None):
    parser = argparse.ArgumentParser(description="Verilator line coverage of the LiteDSP co-simulation suite.")
    parser.add_argument("blocks", nargs="*",                 help="Blocks to run (default: all table entries).")
    parser.add_argument("--min",       default=None, type=float, help="Gate: fail if a non-waived block is below this %%.")
    parser.add_argument("--output",    default=os.path.join(ROOT, "coverage.json"), help="coverage.json path.")
    parser.add_argument("--build-dir", default="/tmp/litedsp_sim_cov", help="Build directory.")
    args = parser.parse_args(argv)

    check_coverage()
    if not have_verilator() or shutil.which("verilator_coverage") is None:
        print("[skip] verilator/verilator_coverage not installed")
        return 0
    for name in args.blocks:
        if name not in SPECS:
            parser.error(f"unknown block '{name}' (see run_blocks.py --list)")
    with open(WAIVERS_PATH) as f:
        waivers = json.load(f)

    names   = args.blocks or list(SPECS)
    results = {name: cover_block(name, args.build_dir) for name in names}
    console(results, waivers, args.min)

    covered = sum(c for c, _ in results.values())
    total   = sum(t for _, t in results.values())
    data = {
        "blocks": {
            name: {
                "pct":     round(100.0*c/t, 1) if t else 0.0,
                "covered": c,
                "total":   t,
                **({"waived": waivers[name]} if name in waivers else {}),
            } for name, (c, t) in results.items()
        },
        "overall": {
            "pct":     round(100.0*covered/total, 1) if total else 0.0,
            "covered": covered,
            "total":   total,
        },
    }
    with open(args.output, "w") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    print(f"[coverage] {args.output}")

    if args.min is not None:
        below = [n for n, (c, t) in results.items()
                 if n not in waivers and (100.0*c/t if t else 0.0) < args.min]
        if below:
            print(f"[gate] below --min {args.min:.1f}%: {', '.join(below)}")
            return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
