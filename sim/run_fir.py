#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Build FIRFilterComplex with Verilator and check it against the NumPy model.

    python3 sim/run_fir.py
"""

import os
import sys
import random

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from litedsp.filter.fir    import LiteDSPFIRFilterComplex
from litedsp.filter.design import firwin_lowpass

from litedsp.verilog import to_verilog
from sim.verilator import build, run
from test.models   import fir_complex_model

def main(n_taps=17, n=200, build_dir="/tmp/litedsp_sim"):
    coeffs = firwin_lowpass(n_taps, 0.2)
    dut = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=16, coefficients=coeffs, with_csr=False)
    ios = {dut.bypass, dut.sink.valid, dut.sink.ready, dut.sink.i, dut.sink.q,
           dut.source.valid, dut.source.ready, dut.source.i, dut.source.q}
    verilog = to_verilog(dut, ios, "fir", build_dir)
    binary  = build(verilog, os.path.join(ROOT, "sim", "fir_tb.cpp"), "fir", build_dir)

    prng = random.Random(1)
    xi = [prng.randint(-30000, 30000) for _ in range(n)]
    xq = [prng.randint(-30000, 30000) for _ in range(n)]
    fin = os.path.join(build_dir, "fir_in.txt")
    with open(fin, "w") as f:
        for i, q in zip(xi, xq):
            f.write(f"{i} {q}\n")
    out = os.path.join(build_dir, "fir_out.txt")
    run(binary, [fin, n, out])

    data = np.loadtxt(out).astype(int)
    got_i, got_q = data[:, 0], data[:, 1]
    ref_i, ref_q = fir_complex_model(xi, xq, coeffs)
    m = min(len(got_i), len(ref_i))
    ok = np.array_equal(got_i[:m], ref_i[:m]) and np.array_equal(got_q[:m], ref_q[:m])
    print(f"FIRFilterComplex Verilator sim: {m} samples, {n_taps} taps")
    print(f"  bit-exact vs NumPy model: {'PASS' if ok else 'FAIL'}")
    if not ok:
        print("  got[:4]", list(zip(got_i[:4], got_q[:4])))
        print("  ref[:4]", list(zip(ref_i[:4], ref_q[:4])))
    return ok

if __name__ == "__main__":
    sys.exit(0 if main() else 1)
