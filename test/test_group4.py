#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.filter.farrow    import FarrowInterpolator
from litedsp.filter.resampler import RationalResampler
from litedsp.stream.route     import ChannelMux, ChannelDemux
from litedsp.stream.adapt     import IQClockDomainCrossing

from test.common import run_stream, column, stream_driver, stream_capture, snr_db

class TestFarrow(unittest.TestCase):
    def test_fractional_delay(self):
        n  = 2000
        f  = 0.02
        mu = 0.5
        x  = np.round(15000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        dut = FarrowInterpolator(data_width=16, frac_bits=15, with_csr=False)
        dut.mu.reset = int(round(mu*(1 << 15)))
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n - 4,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16).astype(float)[16:]
        # Compare to the ideal cosine sampled at a fractional offset (search integer alignment).
        best = -np.inf
        for d in range(0, 25):
            ref = 15000*np.cos(2*np.pi*f*(np.arange(len(y)) + d + mu))
            best = max(best, snr_db(ref, y))
        self.assertGreater(best, 35.0)

class TestRationalResampler(unittest.TestCase):
    def test_ratio(self):
        L, M, n = 3, 2, 600
        f = 0.05
        x = np.round(12000*np.cos(2*np.pi*f*np.arange(n))).astype(int)
        dut = RationalResampler(L, M, data_width=16, with_csr=False)
        n_out = n*L//M - 40
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n_out,
            ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "i", 16).astype(float)[40:]
        # Output tone at f*M/L; should be a clean sinusoid (compare to ideal, search phase).
        fout = f*M/L
        best = -np.inf
        for ph in np.linspace(0, 2*np.pi, 16, endpoint=False):
            ref = np.std(y)*np.sqrt(2)*np.cos(2*np.pi*fout*np.arange(len(y)) + ph)
            best = max(best, snr_db(ref, y))
        self.assertGreater(best, 15.0)   # Resampled tone preserved (crude amplitude-fit metric).

class TestRoute(unittest.TestCase):
    def test_mux_demux(self):
        dut = ChannelMux(n=3, data_width=16, with_csr=False)
        dut.sel.reset = 1
        caps = []
        prng = random.Random(1)
        data = [{"i": prng.randint(-1000, 1000), "q": prng.randint(-1000, 1000)} for _ in range(40)]

        @passive
        def feed_others(dut):
            yield dut.sinks[0].valid.eq(0)
            yield dut.sinks[2].valid.eq(0)
            while True:
                yield
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sinks[1], data, ["i", "q"], throttle=0.1),
            feed_others(dut),
            stream_capture(dut.source, cap, len(data), ["i", "q"], ready_rate=0.8),
        ])
        self.assertTrue(np.array_equal(column(cap, "i", 16), [d["i"] for d in data]))

class TestCDC(unittest.TestCase):
    def test_same_domain_passthrough(self):
        dut = IQClockDomainCrossing(cd_from="sys", cd_to="sys", data_width=16, depth=8)
        prng = random.Random(2)
        data = [{"i": prng.randint(-2000, 2000), "q": prng.randint(-2000, 2000)} for _ in range(60)]
        cap = run_stream(dut, data, len(data), ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "i", 16), [d["i"] for d in data]))

if __name__ == "__main__":
    unittest.main()
