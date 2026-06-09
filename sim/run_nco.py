#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Build the NCO with Verilator (real HDL sim) and check it against the NumPy model.

    python3 sim/run_nco.py
"""

import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from litedsp.generation.nco import NCO

from sim.verilog   import to_verilog
from sim.verilator import build, run
from test.models   import nco_model

def main(phase_inc=0x01234567, n=256, build_dir="/tmp/litedsp_sim"):
    dut = NCO(data_width=16, with_csr=False)
    ios = {dut.phase_inc, dut.source.valid, dut.source.ready, dut.source.i, dut.source.q}
    verilog = to_verilog(dut, ios, "nco", build_dir)
    binary  = build(verilog, os.path.join(ROOT, "sim", "nco_tb.cpp"), "nco", build_dir)
    out     = os.path.join(build_dir, "nco_out.txt")
    run(binary, [phase_inc, n, out])

    data = np.loadtxt(out).astype(int)
    got_i, got_q = data[:, 0], data[:, 1]
    ref_i, ref_q = nco_model(phase_inc, n)
    ok = np.array_equal(got_i, ref_i) and np.array_equal(got_q, ref_q)
    print(f"NCO Verilator sim: {n} samples, phase_inc={phase_inc:#x}")
    print(f"  bit-exact vs NumPy model: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("  got[:4]", list(zip(got_i[:4], got_q[:4])))
        print("  ref[:4]", list(zip(ref_i[:4], ref_q[:4])))
    return ok

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
