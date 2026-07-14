#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""SymbiYosys formal verification of the stream-protocol properties of the plumbing blocks.

Each block of ``formal/wrapper.py``'s registry is emitted at a tiny config (data_width=4) and
checked against the ``formal/stream_props.sv`` properties under fully arbitrary (anyseq) traffic
and backpressure: payload/valid stability, token conservation (no loss / no duplication) and no
valid-from-nowhere after reset. Two SymbiYosys tasks run per block:

- the property task — ``prove`` (k-induction, unbounded) where it closes, else ``bmc`` depth 30;
- a ``cover`` task — real traffic must reach the output, so an over-constrained (vacuously
  passing) setup fails loudly instead of proving nothing.

    python3 formal/run_formal.py                     # all registry entries
    python3 formal/run_formal.py --block skid_buffer # a selection
    python3 formal/run_formal.py --list              # list registry entries

Scope: formal owns the stream *plumbing*; the numerics are owned by the Verilator co-sim
(``sim/``). See ``doc/formal.md`` for the per-block property table and the honest scope statement.
"""

import os
import sys
import time
import shutil
import argparse
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from formal.wrapper import REGISTRY, emit

PROPS = os.path.join(ROOT, "formal", "stream_props.sv")

# SymbiYosys ---------------------------------------------------------------------------------------

def have_sby():
    return shutil.which("sby") is not None and shutil.which("yosys") is not None

def gen_sby(name, spec, build_dir, depth):
    """Write ``<build_dir>/<name>.sby`` (property task + cover task). Returns its path."""
    mode = spec["mode"]  # "prove" where k-induction closes, else "bmc" (set in wrapper.py).
    path = os.path.join(build_dir, name + ".sby")
    with open(path, "w") as f:
        f.write(f"""\
[tasks]
{mode}
cover

[options]
{mode}: mode {mode}
cover: mode cover
depth {depth}

[engines]
smtbmc bitwuzla

[script]
read_verilog -formal -sv stream_props.sv
read_verilog -formal -sv {name}_formal.sv
read_verilog {name}.v
prep -top {name}_formal

[files]
{PROPS}
{os.path.join(build_dir, name + "_formal.sv")}
{os.path.join(build_dir, name + ".v")}
""")
    return path

def run_sby(sby_path, task, build_dir):
    """Run one sby task. Returns (ok, seconds, last log lines for diagnostics)."""
    start = time.time()
    proc  = subprocess.run(["sby", "-f", sby_path, task],
        cwd=build_dir, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc.returncode == 0, time.time() - start, proc.stdout.splitlines()[-12:]

# Runner -------------------------------------------------------------------------------------------

def run_block(name, build_dir, depth):
    bd = os.path.join(build_dir, name)
    os.makedirs(bd, exist_ok=True)
    verilog, sv, spec = emit(name, bd)
    sby_path = gen_sby(name, spec, bd, depth)

    mode = spec["mode"]
    ok_p, t_p, log_p = run_sby(sby_path, mode,    bd)
    ok_c, t_c, log_c = run_sby(sby_path, "cover", bd)

    bound   = f"[{spec['min_diff']:+d}, {spec['max_diff']:+d}]"
    weights = f"{spec['in_weight']}:{spec['out_weight']}"
    verdict = ("PASS" if ok_p else "FAIL") + ("" if ok_c else " (COVER UNREACHED)")
    print(f"{name:14s} {mode:5s} depth={depth:2d} tokens {weights} diff{bound:10s} "
          f"{t_p + t_c:6.1f}s : {verdict}")
    for ok, log, what in ((ok_p, log_p, mode), (ok_c, log_c, "cover")):
        if not ok:
            print(f"  --- sby {what} log tail ({os.path.join(bd, name)}_{what}/) ---")
            for l in log:
                print(f"  {l}")
    return ok_p and ok_c

def main(argv=None):
    parser = argparse.ArgumentParser(
        description="SymbiYosys formal verification of LiteDSP stream-plumbing blocks.")
    parser.add_argument("--block", action="append", default=None,   help="Block to run (repeatable; default: all).")
    parser.add_argument("--list",  action="store_true",             help="List registry entries and exit.")
    parser.add_argument("--depth", default=30, type=int,            help="BMC / induction depth.")
    parser.add_argument("--build-dir", default="/tmp/litedsp_formal", help="Build directory.")
    args = parser.parse_args(argv)

    if args.list:
        for name in REGISTRY:
            print(name)
        return 0
    if not have_sby():
        print("[skip] sby/yosys not installed (OSS CAD Suite)")
        return 0
    for name in args.block or ():
        if name not in REGISTRY:
            parser.error(f"unknown block '{name}' (see --list)")

    names   = args.block or list(REGISTRY)
    start   = time.time()
    results = [run_block(n, args.build_dir, args.depth) for n in names]
    print(f"\n{sum(results)}/{len(names)} blocks formally verified "
          f"(stability + token conservation + cover) in {time.time() - start:.1f}s")
    return 0 if all(results) else 1

if __name__ == "__main__":
    sys.exit(main())
