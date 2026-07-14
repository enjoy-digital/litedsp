#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Verilator-lint every implementation-registry block.

Verilog-level portability check under a second tool's semantics (width/latch/comb-loop
classes of issues), covering the whole registry — the co-simulation runners then check
bit-exactness for the blocks with NumPy models.

    python3 sim/run_lint.py
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from impl.modules import REGISTRY
from litedsp.flow.generate import emit_verilog
from sim.verilator import lint, have_verilator

def main(build_root="/tmp/litedsp_lint"):
    if not have_verilator():
        print("[skip] verilator not installed")
        return 0
    fails = []
    for name, factory in sorted(REGISTRY.items()):
        dut, ios, _ = factory()
        # "_dut" suffix: a top named like one of its ports (e.g. gain) breaks Verilator's C model.
        top     = name + "_dut"
        verilog = emit_verilog(dut, ios, top, os.path.join(build_root, name))
        ok = lint(verilog, top)
        print(f"{name:20s} verilator lint: {'PASS' if ok else 'FAIL'}")
        if not ok:
            fails.append(name)
    if fails:
        print(f"\nFAILED: {', '.join(fails)}")
    return 1 if fails else 0

if __name__ == "__main__":
    sys.exit(main())
