#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Run LiteDSP blocks through the FPGA implementation flows and gate on resource budgets.

    python3 impl/run.py --device ecp5   --flow synth                # all modules, Yosys synth
    python3 impl/run.py --device xilinx --flow synth --subset       # Vivado OOC synth (subset)
    python3 impl/run.py --device ecp5   --flow pnr  --subset        # + nextpnr P&R (fmax)
    python3 impl/run.py --device ecp5   --flow synth --update-budgets   # seed/refresh baseline
"""

import os
import sys
import argparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from impl.modules import REGISTRY, PNR_SUBSET
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
    p = argparse.ArgumentParser()
    p.add_argument("--device", choices=["ecp5", "xilinx"], default="ecp5")
    p.add_argument("--flow",   choices=["synth", "pnr"],    default="synth")
    p.add_argument("--module", default=None, help="single module name (default: all)")
    p.add_argument("--subset", action="store_true", help="only the P&R subset")
    p.add_argument("--build",  default="/tmp/litedsp_impl")
    p.add_argument("--update-budgets", action="store_true")
    p.add_argument("--no-gate", action="store_true",
        help="don't fail on budget violations (portability/compile-clean check only)")
    p.add_argument("--report", default=None, help="write a Markdown table to this path")
    args = p.parse_args()

    if args.module:
        names = [args.module]
    elif args.subset or args.flow == "pnr":
        names = list(PNR_SUBSET)
    else:
        names = list(REGISTRY)

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

    failed = bool(errors) or (any(violations.values()) and not args.no_gate)
    return 1 if (failed and not args.update_budgets) else 0

if __name__ == "__main__":
    sys.exit(main())
