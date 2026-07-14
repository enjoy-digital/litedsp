#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.filter.pulse_shape import LiteDSPPulseShaper

from test.common import run_stream, column

class TestPulseShaper(unittest.TestCase):
    def test_pulse(self):
        sps, span = 4, 8
        dut = LiteDSPPulseShaper(sps=sps, span=span, beta=0.35, data_width=16, with_csr=False)
        # One nonzero symbol among zeros -> output is one RRC pulse.
        syms = [0]*4 + [16000] + [0]*8
        n_out = len(syms)*sps
        cap = run_stream(dut, [{"i": s, "q": 0} for s in syms], n_out, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16)
        self.assertGreater(np.abs(y).max(), 2000)             # Pulse present.
        self.assertLess(abs(int(np.argmax(np.abs(y))) - (4*sps + sps*span//2)), 2*sps)

if __name__ == "__main__":
    unittest.main()
