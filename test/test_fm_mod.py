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

from litedsp.comm.fm_mod   import LiteDSPFrequencyModulator, LiteDSPPhaseModulator
from litedsp.comm.fm_demod import LiteDSPFMDemod

from test.common import run_stream, column
from test.models import fm_modulator_model, pm_modulator_model

class TestAngleModulators(unittest.TestCase):
    # verify-tier: model — 300 random samples (full scale, negative) with a large and a wrapping
    # deviation, FM and PM, bit-exact under backpressure; latency 2.
    def test_bit_exact(self):
        prng = random.Random(1)
        x = [prng.randint(-32768, 32767) for _ in range(300)]
        for cls, model, dev in ((LiteDSPFrequencyModulator, fm_modulator_model, 0x0800_0000),
                                (LiteDSPFrequencyModulator, fm_modulator_model, 0xF000_0000),
                                (LiteDSPPhaseModulator, pm_modulator_model, 0x4000_0000)):
            with self.subTest(cls=cls.__name__, dev=hex(dev)):
                dut = cls(with_csr=False)
                dut.phase_inc.reset, dut.deviation.reset = 0x0123_4567, dev
                cap = run_stream(dut, [{"data": v} for v in x], 300, ["data"], ["i", "q"],
                                 sink_throttle=0.2, source_ready_rate=0.7)
                ri, rq = model(x, 0x0123_4567, dev)
                self.assertEqual(column(cap, "i", 16).tolist(), ri.tolist())
                self.assertEqual(column(cap, "q", 16).tolist(), rq.tolist())
                self.assertEqual(dut.latency, 2)

    # verify-tier: bound — an FM tone through the modulator and the FM demodulator: the recovered
    # peak deviation is within 2 % of the programmed one and the message correlates > 0.99;
    # a PM DC input rotates the carrier by the programmed angle within one LUT step.
    def test_loopback_and_pm_angle(self):
        n = 400
        msg = [int(round(20000*math.sin(2*math.pi*0.01*k))) for k in range(n)]
        dev = 0x0200_0000                                     # 1/128 turn per sample at full scale.
        class Loop(LiteXModule):
            def __init__(self):
                self.mod   = LiteDSPFrequencyModulator(with_csr=False)
                self.demod = LiteDSPFMDemod(with_csr=False)
                self.mod.deviation.reset = dev
                self.sink, self.source = self.mod.sink, self.demod.source
                self.comb += self.mod.source.connect(self.demod.sink)
        cap = run_stream(Loop(), [{"data": v} for v in msg], n, ["data"], ["data"],
                         sink_throttle=0.0, source_ready_rate=1.0)
        y = column(cap, "data", 16).astype(float)[20:]
        expect = dev/2**32*2**16*20000/32768                        # Peak angle step (angle units).
        # The LUT phase steps (64 angle units) jitter the per-sample estimate: compare the RMS.
        self.assertLessEqual(abs(np.sqrt(np.mean(y**2))*math.sqrt(2) - expect)/expect, 0.02)
        m = np.array(msg[20:], float)
        self.assertGreater(float(np.corrcoef(y, m)[0, 1]), 0.99)
        dut = LiteDSPPhaseModulator(with_csr=False)
        dut.phase_inc.reset, dut.deviation.reset = 0, 0x4000_0000      # Quarter turn at full scale.
        cap = run_stream(dut, [{"data": 16384}]*8, 8, ["data"], ["i", "q"], sink_throttle=0.0,
                         source_ready_rate=1.0)
        ang = math.atan2(column(cap, "q", 16)[-1], column(cap, "i", 16)[-1])
        self.assertLessEqual(abs(ang - math.pi/4), 2*math.pi/1024)
        with self.assertRaises(ValueError):
            LiteDSPFrequencyModulator(lut_depth=100, with_csr=False)

if __name__ == "__main__":
    unittest.main()
