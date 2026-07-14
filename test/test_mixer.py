#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation

from litedsp.mixing.mixer import LiteDSPMixer, MIXER_MODE_DOWN, MIXER_MODE_UP, \
    MIXER_BYPASS_SINK_A, MIXER_BYPASS_SINK_B

from test.common import stream_driver, stream_capture, column
from test.models import mixer_model

class TestMixer(unittest.TestCase):
    def run_mixer(self, a, b, mode=MIXER_MODE_DOWN, bypass=0, data_width=16, n=None):
        n   = n or len(a["i"])
        dut = LiteDSPMixer(data_width=data_width, with_csr=False)
        dut.mode.reset   = mode
        dut.bypass.reset = bypass

        samples_a = [{"i": a["i"][k], "q": a["q"][k]} for k in range(n)]
        samples_b = [{"i": b["i"][k], "q": b["q"][k]} for k in range(n)]
        captured  = []
        run_simulation(dut, [
            stream_driver(dut.sink_a, samples_a, ["i", "q"], seed=1, throttle=0.2),
            stream_driver(dut.sink_b, samples_b, ["i", "q"], seed=2, throttle=0.3),
            stream_capture(dut.source, captured, n, ["i", "q"], seed=3, ready_rate=0.7),
        ])
        return (column(captured, "i", data_width), column(captured, "q", data_width))

    def random_iq(self, n, seed, amp=30000):
        prng = random.Random(seed)
        return {"i": [prng.randint(-amp, amp) for _ in range(n)],
                "q": [prng.randint(-amp, amp) for _ in range(n)]}

    def test_down_bit_exact(self):
        a, b = self.random_iq(256, 10), self.random_iq(256, 11)
        gi, gq = self.run_mixer(a, b, mode=MIXER_MODE_DOWN)
        ri, rq = mixer_model(a["i"], a["q"], b["i"], b["q"], mode="down")
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

    def test_up_bit_exact(self):
        a, b = self.random_iq(256, 20), self.random_iq(256, 21)
        gi, gq = self.run_mixer(a, b, mode=MIXER_MODE_UP)
        ri, rq = mixer_model(a["i"], a["q"], b["i"], b["q"], mode="up")
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))

    def test_bypass_a(self):
        a, b = self.random_iq(128, 30), self.random_iq(128, 31)
        gi, gq = self.run_mixer(a, b, bypass=MIXER_BYPASS_SINK_A)
        self.assertTrue(np.array_equal(gi, np.array(a["i"])))
        self.assertTrue(np.array_equal(gq, np.array(a["q"])))

    def test_bypass_b(self):
        a, b = self.random_iq(128, 40), self.random_iq(128, 41)
        gi, gq = self.run_mixer(a, b, bypass=MIXER_BYPASS_SINK_B)
        self.assertTrue(np.array_equal(gi, np.array(b["i"])))
        self.assertTrue(np.array_equal(gq, np.array(b["q"])))

if __name__ == "__main__":
    unittest.main()
