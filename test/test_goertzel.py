#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import run_simulation, passive

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

    # verify-tier: model — folding changes the accepted-sample interval, not recurrence or
    # power arithmetic.
    def test_folded_bit_identical(self):
        N, k = 32, 7
        rng  = np.random.RandomState(17)
        x    = rng.randint(-12000, 12000, 5*N)
        samples = [{"data": int(v)} for v in x]

        def capture(architecture):
            dut = LiteDSPGoertzel(N=N, k=k, architecture=architecture, with_csr=False)
            cap = run_stream(dut, samples, 5, ["data"], ["data"], sink_throttle=0.2,
                source_ready_rate=0.65)
            return [int(v) for v in column(cap, "data")]

        self.assertEqual(capture("folded"), capture("classic"))

    # verify-tier: model — folded recurrence accepts exactly one sample every two clocks.
    def test_folded_sample_interval(self):
        dut   = LiteDSPGoertzel(N=16, k=3, architecture="folded", with_csr=False)
        stats = {"cycles": []}

        @passive
        def driver():
            cycle = 0
            yield dut.sink.valid.eq(1)
            yield dut.source.ready.eq(1)
            while len(stats["cycles"]) < 40:
                yield
                cycle += 1
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    stats["cycles"].append(cycle)

        def stop():
            while len(stats["cycles"]) < 40:
                yield

        run_simulation(dut, [driver(), stop()])
        np.testing.assert_array_equal(np.diff(stats["cycles"]), np.full(39, 2))
        self.assertEqual(dut.sample_interval, 2)

    def test_invalid_architecture(self):
        with self.assertRaises(ValueError):
            LiteDSPGoertzel(N=16, k=3, architecture="invalid", with_csr=False)

if __name__ == "__main__":
    unittest.main()
