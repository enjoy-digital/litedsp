#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Fixed-point width audit: core blocks must stay bit-exact at non-default Qm.n widths.

The interface contract promises parameterized data widths; this sweep pins that guarantee in
CI by running the golden-model comparison for representative blocks at 12/18/24 bits (below,
between and above the 16-bit default).
"""

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.generation.nco import NCO
from litedsp.mixing.mixer   import Mixer
from litedsp.filter.fir     import FIRFilter

from test.common import stream_driver, stream_capture, column
from test.models import nco_model, mixer_model, fir_model

WIDTHS = (12, 18, 24)

class TestWidthSweep(unittest.TestCase):
    def test_nco(self):
        for dw in WIDTHS:
            phase_inc = 0x0731_9CDE
            dut = NCO(data_width=dw, with_csr=False)
            dut.phase_inc.reset = phase_inc
            cap = []
            run_simulation(dut, [stream_capture(dut.source, cap, 64, ("i", "q"), ready_rate=0.7)])
            ri, rq = nco_model(phase_inc, 64, data_width=dw)
            self.assertTrue(np.array_equal(column(cap, "i", dw), ri), f"dw={dw}")
            self.assertTrue(np.array_equal(column(cap, "q", dw), rq), f"dw={dw}")

    def test_mixer(self):
        for dw in WIDTHS:
            prng = random.Random(dw)
            hi   = int(0.6 * 2**(dw - 1))
            n    = 64
            a = [(prng.randint(-hi, hi), prng.randint(-hi, hi)) for _ in range(n)]
            b = [(prng.randint(-hi, hi), prng.randint(-hi, hi)) for _ in range(n)]
            dut = Mixer(data_width=dw, with_csr=False)     # mode=0: down.
            cap = []
            run_simulation(dut, [
                stream_driver(dut.sink_a, [{"i": i, "q": q} for (i, q) in a], ("i", "q"), throttle=0.2),
                stream_driver(dut.sink_b, [{"i": i, "q": q} for (i, q) in b], ("i", "q"), throttle=0.3, seed=3),
                stream_capture(dut.source, cap, n, ("i", "q"), ready_rate=0.7),
            ])
            ri, rq = mixer_model(np.array([s[0] for s in a]), np.array([s[1] for s in a]),
                                 np.array([s[0] for s in b]), np.array([s[1] for s in b]),
                                 mode="down", data_width=dw)
            self.assertTrue(np.array_equal(column(cap, "i", dw), ri), f"dw={dw}")
            self.assertTrue(np.array_equal(column(cap, "q", dw), rq), f"dw={dw}")

    def test_fir(self):
        for dw in WIDTHS:
            prng   = random.Random(dw + 1)
            hi     = int(0.6 * 2**(dw - 1))
            n_taps = 7
            coeffs = [prng.randint(-hi//4, hi//4) for _ in range(n_taps)]
            x      = [prng.randint(-hi, hi) for _ in range(64)]
            dut = FIRFilter(n_taps=n_taps, data_width=dw)
            for t in range(n_taps):
                dut.coeffs[t].reset = coeffs[t]            # Signed; do not mask.
            cap = []
            run_simulation(dut, [
                stream_driver(dut.sink, [{"data": v} for v in x], ("data",), throttle=0.2),
                stream_capture(dut.source, cap, len(x), ("data",), ready_rate=0.7),
            ])
            got = column(cap, "data", dw)
            ref = fir_model(np.array(x), coeffs, data_width=dw)[:len(got)]
            self.assertTrue(np.array_equal(got, ref), f"dw={dw}")

if __name__ == "__main__":
    unittest.main()
