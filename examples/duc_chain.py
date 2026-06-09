#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Digital up-converter example: interpolate a baseband tone and shift it to an IF.

    python3 examples/duc_chain.py
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from litedsp.mixing.duc import DUC

from test.common import run_stream, column

def main():
    data_width    = 16
    interpolation = 4
    f_out         = 0.10                       # Target IF (normalized to the output rate).
    n             = 400

    dut = DUC(data_width=data_width, interpolation=interpolation, method="fir", with_csr=False)
    dut.nco.phase_inc.reset = int(round(f_out*(1 << 32))) & 0xffffffff

    # Baseband: a low complex tone (well inside the interpolation passband).
    f_bb = 0.02
    bb   = 9000*np.exp(1j*2*np.pi*f_bb*np.arange(n))
    samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in bb]

    cap = run_stream(dut, samples, n*interpolation - 20, ["i", "q"], ["i", "q"],
        sink_throttle=0.0, source_ready_rate=1.0)
    y    = (column(cap, "i", 16) + 1j*column(cap, "q", 16))[64:]
    spec = np.abs(np.fft.fft(y*np.hanning(len(y))))**2
    f    = np.fft.fftfreq(len(y))
    peak = f[np.argmax(spec)]
    print(f"DUC: interpolate x{interpolation}, shift baseband {f_bb:.3f} -> IF {f_out:.3f}")
    print(f"  output spectral peak at {peak:+.3f} (expected ~{f_out + f_bb/interpolation:+.3f})")

if __name__ == "__main__":
    main()
