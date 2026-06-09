#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.filter.fir_poly import FIRDecimator
from litedsp.filter.design   import firwin_lowpass

from test.common import column, stream_capture
from test.models import fir_decimator_model

class TestFIRReload(unittest.TestCase):
    def test_runtime_reload(self):
        n_taps, R = 16, 4
        new = firwin_lowpass(n_taps, 0.4/R)              # Reload these at runtime.
        # Build with the default (impulse) coefficients; reload `new` via the coeff interface.
        dut = FIRDecimator(n_taps, R, data_width=16, with_csr=False)
        prng = random.Random(1)
        x = [(prng.randint(-25000, 25000), prng.randint(-25000, 25000)) for _ in range(R*60)]
        n_out = len(x)//R - 2
        mask = (1 << 16) - 1

        @passive
        def driver(dut):
            yield dut.coeff_rst.eq(1)
            yield
            yield dut.coeff_rst.eq(0)
            for c in new:                                # Stream the new taps in.
                yield dut.coeff_data.eq(c & mask)
                yield dut.coeff_we.eq(1)
                yield
            yield dut.coeff_we.eq(0)
            for (i, q) in x:                             # Then feed data.
                yield dut.sink.i.eq(i)
                yield dut.sink.q.eq(q)
                yield dut.sink.valid.eq(1)
                yield
                while (yield dut.sink.ready) == 0:
                    yield
            yield dut.sink.valid.eq(0)

        cap = []
        run_simulation(dut, [driver(dut),
            stream_capture(dut.source, cap, n_out, ["i", "q"], ready_rate=1.0)])
        gi = column(cap, "i", 16)
        ref = fir_decimator_model([i for i, q in x], new, R)[:len(gi)]
        self.assertTrue(np.array_equal(gi, ref))         # Filter used the reloaded taps.

if __name__ == "__main__":
    unittest.main()
