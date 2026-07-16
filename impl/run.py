#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Run LiteDSP blocks through the FPGA implementation flows and gate on resource budgets.

    python3 impl/run.py --device ecp5   --flow synth                # all modules, Yosys synth
    python3 impl/run.py --device xilinx --flow synth --subset       # Vivado OOC synth (subset)
    python3 impl/run.py --device ecp5   --flow pnr                  # + nextpnr P&R (fmax), all
    python3 impl/run.py --device ecp5   --flow pnr  --subset        # + nextpnr P&R, fast subset
    python3 impl/run.py --device ecp5   --flow synth --update-budgets   # seed/refresh baseline
    python3 impl/run.py --device xilinx --flow synth --missing-budgets --update-budgets
"""

import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from impl.modules import REGISTRY, PNR_SUBSET, SYNTH_ONLY
from impl import wrap, ecp5, xilinx, report, budgets

def build_one(device, flow, name, build_root):
    dut, ios, clock_ns = REGISTRY[name]()
    bd = os.path.join(build_root, device, name)
    verilog = wrap.gen(name, dut, ios, bd)
    if device == "ecp5":
        json_out = name + ".json" if flow == "pnr" else None
        res = ecp5.synth(verilog, name, bd, json_out=json_out)
        if flow == "pnr":
            if not ecp5.have_nextpnr():
                raise RuntimeError("nextpnr-ecp5 not installed")
            res["pnr"] = ecp5.pnr(os.path.join(bd, json_out), name, bd, clock_ns)
    else:
        res = xilinx.synth(verilog, name, bd, impl=(flow == "pnr"), clock_ns=clock_ns)
    return res

def main():
    parser = argparse.ArgumentParser(description="LiteDSP FPGA implementation flows (synth/P&R + budget gate).")
    parser.add_argument("--device",         default="ecp5",              choices=["ecp5", "xilinx"], help="Target device/toolchain.")
    parser.add_argument("--flow",           default="synth",             choices=["synth", "pnr"],   help="Implementation flow.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--module",         default=None,        help="Single module name (default: all).")
    selection.add_argument("--subset",         action="store_true", help="Only the P&R subset.")
    selection.add_argument("--missing-budgets", action="store_true",
        help="Only modules without a baseline for the selected device.")
    parser.add_argument("--build",          default="/tmp/litedsp_impl", help="Build directory.")
    parser.add_argument("--update-budgets", action="store_true",         help="Rewrite the budget baseline from this run.")
    parser.add_argument("--no-gate",        action="store_true",         help="Don't fail on budget violations (portability/compile-clean check only).")
    parser.add_argument("--report",         default=None,                help="Write a Markdown table to this path.")
    args = parser.parse_args()

    if args.module:
        names = [args.module]
    elif args.subset:
        names = list(PNR_SUBSET)
    elif args.missing_budgets:
        names = budgets.missing(args.device, REGISTRY)
    else:
        names = list(REGISTRY)
    if args.flow == "pnr":                                # Port count exceeds device pins.
        names = [n for n in names if n not in SYNTH_ONLY]

    if not names:
        print(f"[ok] no missing budgets for {args.device}")
        return 0

    tool_ok = {"ecp5": ecp5.have_yosys(), "xilinx": xilinx.have_vivado()}[args.device]
    if not tool_ok:
        print(f"[skip] toolchain for {args.device} not installed")
        return 0

    results, violations, errors = {}, {}, {}
    for name in names:
        try:
            res = build_one(args.device, args.flow, name, args.build)
            results[name] = res
            if not args.update_budgets:
                violations[name] = budgets.check(args.device, name, res)
        except Exception as e:
            errors[name] = f"{type(e).__name__}: {e}"

    report.console(args.device, results, violations)
    if errors:
        print("\n--- errors ---")
        for n, e in errors.items():
            print(f"  {n}: {e}")
    if args.update_budgets:
        budgets.update(args.device, results)
        print(f"\n[budgets] baseline updated for {args.device} ({len(results)} modules)")
    if args.report:
        with open(args.report, "w") as f:
            f.write(report.markdown({args.device: results}))

    failed = bool(errors) or (any(violations.values()) and not args.no_gate and not args.update_budgets)
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
