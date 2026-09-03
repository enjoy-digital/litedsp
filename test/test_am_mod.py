#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math
import random
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.comm.am_mod   import LiteDSPAMModulator
from litedsp.comm.am_demod import LiteDSPAMDemod

from test.common import run_stream, column
from test.models import am_modulator_model

class TestAMModulator(unittest.TestCase):
    # verify-tier: model — 300 random samples, baseband and embedded-carrier outputs at indices
    # 1.0 and 0.5, bit-exact under backpressure; the envelope tracks 2^14 (1 + m x) within 2 LSB;
    # pinned latencies.
    def test_bit_exact(self):
        prng = random.Random(2)
        x = [prng.randint(-32768, 32767) for _ in range(300)]
        for carrier, index in (("baseband", 32768), ("baseband", 16384), ("nco", 32768)):
            with self.subTest(carrier=carrier, index=index):
                dut = LiteDSPAMModulator(carrier=carrier, with_csr=False)
                dut.index.reset = index
                dut.phase_inc.reset = 0x0800_0000
                cap = run_stream(dut, [{"data": v} for v in x], 300, ["data"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
                ri, rq = am_modulator_model(x, index, carrier, 0x0800_0000)
                self.assertEqual(column(cap, "i", 16).tolist(), ri.tolist())
                self.assertEqual(column(cap, "q", 16).tolist(), rq.tolist())
                self.assertEqual(dut.latency, 2 if carrier == "baseband" else 4)
                if carrier == "baseband":
                    env = 16384*(1 + np.array(x)/32768*index/32768)
                    self.assertLessEqual(int(np.max(np.abs(column(cap, "i", 16) - np.round(env)))), 2)

    # verify-tier: bound — a 1 kHz-like tone at index 0.8 through the modulator and the AM
    # demodulator correlates > 0.95 with the message after the DC blocker settles; invalid carrier.
    def test_loopback(self):
        n = 600
        msg = [int(round(24000*math.sin(2*math.pi*0.005*k))) for k in range(n)]
        class Loop(LiteXModule):
            def __init__(self):
                self.mod   = LiteDSPAMModulator(carrier="nco", with_csr=False)
                self.demod = LiteDSPAMDemod(with_csr=False)
                self.mod.index.reset = int(0.8*32768)
                self.mod.phase_inc.reset = 0x2000_0000                  # fs / 8 carrier.
                self.sink, self.source = self.mod.sink, self.demod.source
                self.comb += self.mod.source.connect(self.demod.sink)
        cap = run_stream(Loop(), [{"data": v} for v in msg], n, ["data"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "data", 16).astype(float)[300:]
        self.assertGreater(float(np.corrcoef(y, np.array(msg[300:], float))[0, 1]), 0.95)
        with self.assertRaises(ValueError):
            LiteDSPAMModulator(carrier="lo", with_csr=False)

if __name__ == "__main__":
    unittest.main()
