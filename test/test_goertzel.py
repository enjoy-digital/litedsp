#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.analysis.goertzel import LiteDSPGoertzel

from test.common import run_stream, column, to_signed

class TestGoertzel(unittest.TestCase):
    def test_detects_bin(self):
        N, k = 64, 10
        def run(freq_bin):
            dut = LiteDSPGoertzel(N=N, k=k, data_width=16, with_csr=False)
            x = np.round(12000*np.cos(2*np.pi*freq_bin*np.arange(N)/N)).astype(int)
            cap = run_stream(dut, [{"data": int(v)} for v in x], 1, ["data"], ["data"],
                sink_throttle=0.0, source_ready_rate=1.0)
            return abs(int(to_signed(column(cap, "data"), dut.source.data.nbits)[0]))
        on  = run(k)        # tone at the Goertzel bin.
        off = run(k + 8)    # tone elsewhere.
        self.assertGreater(on, 20*max(off, 1))

if __name__ == "__main__":
    unittest.main()
