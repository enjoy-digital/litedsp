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
import statistics

from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from impl.modules import REGISTRY, PNR_SUBSET, TARGET_CLOSED, SYNTH_ONLY
from impl import wrap, ecp5, xilinx, report, budgets

def aggregate_pnr_runs(runs, failures):
    """Select the median completed route and attach best/median/worst statistics."""
    if not runs:
        details = "; ".join(f"seed {seed}: {error}" for seed, error in failures)
        raise RuntimeError("no P&R run completed" + (f" ({details})" if details else ""))
    ordered = sorted(runs, key=lambda item: item[1]["fmax_mhz"])
    median_fmax = statistics.median(item[1]["fmax_mhz"] for item in ordered)
    selected = min(ordered, key=lambda item: abs(item[1]["fmax_mhz"] - median_fmax))
    stats = {
        "completed": len(ordered),
        "failed": len(failures),
        "best_mhz": ordered[-1][1]["fmax_mhz"],
        "median_mhz": median_fmax,
        "worst_mhz": ordered[0][1]["fmax_mhz"],
        "runs": [{"seed": seed, "fmax_mhz": result["fmax_mhz"]}
                 for seed, result in ordered],
        "failures": [{"seed": seed, "error": error} for seed, error in failures],
    }
    return selected[1], stats

def build_many(names, builder, jobs=1):
    """Run independent implementation builds concurrently and return ordered results/errors."""
    results, errors = {}, {}
    if jobs == 1:
        futures = [(name, None) for name in names]
    else:
        executor = ThreadPoolExecutor(max_workers=jobs)
        futures = [(name, executor.submit(builder, name)) for name in names]
    try:
        for name, future in futures:
            try:
                results[name] = builder(name) if future is None else future.result()
            except Exception as e:
                errors[name] = f"{type(e).__name__}: {e}"
    finally:
        if jobs != 1:
            executor.shutdown(wait=True)
    return results, errors

def build_one(device, flow, name, build_root, seeds=None, pnr_timeout=1800):
    dut, ios, clock_ns = REGISTRY[name]()
    bd = os.path.join(build_root, device, name)
    verilog = wrap.gen(name, dut, ios, bd)
    if device == "ecp5":
        json_out = name + ".json" if flow == "pnr" else None
        res = ecp5.synth(verilog, name, bd, json_out=json_out)
        if flow == "pnr":
            if not ecp5.have_nextpnr():
                raise RuntimeError("nextpnr-ecp5 not installed")
            runs, failures = [], []
            for seed in seeds or [None]:
                try:
                    route = ecp5.pnr(os.path.join(bd, json_out), name, bd, clock_ns,
                        seed=seed, timeout=pnr_timeout)
                    runs.append((seed, route))
                except (ecp5.PNRTimeout, RuntimeError) as e:
                    failures.append((seed, str(e)))
            res["pnr"], res["pnr_stats"] = aggregate_pnr_runs(runs, failures)
    elif device in xilinx.PARTS:
        res = xilinx.synth(verilog, name, bd, impl=(flow == "pnr"), clock_ns=clock_ns,
            timeout=pnr_timeout, part=xilinx.PARTS[device])
    else:
        raise ValueError(f"unsupported implementation device: {device}")
    return res

def main():
    parser = argparse.ArgumentParser(description="LiteDSP FPGA implementation flows (synth/P&R + budget gate).")
    parser.add_argument("--device",         default="ecp5",
        choices=["ecp5", *xilinx.PARTS], help="Target device/toolchain/profile.")
    parser.add_argument("--flow",           default="synth",             choices=["synth", "pnr"],   help="Implementation flow.")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--module",         default=None,        help="Single module name (default: all).")
    selection.add_argument("--subset",         action="store_true", help="Only the P&R subset.")
    selection.add_argument("--target-closed",  action="store_true",
        help="Only blocks whose reviewed timing target is already closed.")
    selection.add_argument("--missing-budgets", action="store_true",
        help="Only modules without a baseline for the selected device.")
    parser.add_argument("--build",          default="/tmp/litedsp_impl", help="Build directory.")
    parser.add_argument("--update-budgets", action="store_true",         help="Rewrite the budget baseline from this run.")
    parser.add_argument("--no-gate",        action="store_true",         help="Don't fail on budget violations (portability/compile-clean check only).")
    parser.add_argument("--target-gate",    action="store_true",         help="Also fail when P&R misses an explicit fmax_target.")
    parser.add_argument("--report",         default=None,                help="Write a Markdown table to this path.")
    routes = parser.add_mutually_exclusive_group()
    routes.add_argument("--seeds", default=None,
        help="Comma-separated nextpnr seeds; synthesize once and report best/median/worst.")
    routes.add_argument("--repeat", type=int, default=None,
        help="Run nextpnr with seeds 0..N-1; synthesize once and report route statistics.")
    parser.add_argument("--pnr-timeout", type=int, default=1800,
        help="Per-route timeout in seconds (default: 1800; 0 disables the timeout).")
    parser.add_argument("--jobs", type=int, default=1,
        help="Independent module builds to run concurrently (default: 1).")
    args = parser.parse_args()

    if args.seeds is not None:
        try:
            seeds = [int(seed.strip()) for seed in args.seeds.split(",") if seed.strip()]
        except ValueError:
            parser.error("--seeds must be a comma-separated list of integers")
        if not seeds:
            parser.error("--seeds must not be empty")
    elif args.repeat is not None:
        if args.repeat < 1:
            parser.error("--repeat must be >= 1")
        seeds = list(range(args.repeat))
    else:
        seeds = None
    if seeds is not None and (args.device != "ecp5" or args.flow != "pnr"):
        parser.error("--seeds/--repeat are supported only for ECP5 P&R")
    pnr_timeout = None if args.pnr_timeout == 0 else args.pnr_timeout
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")

    if args.module:
        names = [args.module]
    elif args.subset:
        names = list(PNR_SUBSET)
    elif args.target_closed:
        names = list(TARGET_CLOSED)
    elif args.missing_budgets:
        names = budgets.missing(args.device, REGISTRY, flow=args.flow)
    else:
        names = list(REGISTRY)
    if args.flow == "pnr":                                # Port count exceeds device pins.
        names = [n for n in names if n not in SYNTH_ONLY]

    if not names:
        print(f"[ok] no missing budgets for {args.device}")
        return 0

    tool_ok = ecp5.have_yosys() if args.device == "ecp5" else xilinx.have_vivado()
    if not tool_ok:
        print(f"[skip] toolchain for {args.device} not installed")
        return 0

    builder = lambda name: build_one(args.device, args.flow, name, args.build,
        seeds=seeds, pnr_timeout=pnr_timeout)
    results, errors = build_many(names, builder, jobs=args.jobs)
    violations, target_misses = {}, {}
    if not args.update_budgets:
        for name, res in results.items():
            violations[name] = budgets.check(args.device, name, res, flow=args.flow)
            target_misses[name] = budgets.check_target(args.device, name, res)

    report.console(args.device, results, violations, target_misses)
    for name, res in results.items():
        stats = res.get("pnr_stats")
        if stats and (stats["completed"] > 1 or stats["failed"]):
            print(f"  {name}: routes {stats['completed']} completed/{stats['failed']} failed; "
                  f"worst/median/best {stats['worst_mhz']:.1f}/"
                  f"{stats['median_mhz']:.1f}/{stats['best_mhz']:.1f} MHz")
    if errors:
        print("\n--- errors ---")
        for n, e in errors.items():
            print(f"  {n}: {e}")
    if args.update_budgets:
        budgets.update(args.device, results, flow=args.flow)
        print(f"\n[budgets] baseline updated for {args.device}/{args.flow} ({len(results)} modules)")
    if args.report:
        with open(args.report, "w") as f:
            f.write(report.markdown({args.device: results}))

    gated = any(violations.values()) or (args.target_gate and any(target_misses.values()))
    failed = bool(errors) or (gated and not args.no_gate and not args.update_budgets)
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
