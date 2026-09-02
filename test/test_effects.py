#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.audio.effects import LiteDSPLFO, LiteDSPDelayLine

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import lfo_model, delay_line_model

FS24, FS16 = (1 << 23) - 1, (1 << 15) - 1

def tdm(chans):
    beats = []
    for k in range(len(chans[0])):
        for c, ch in enumerate(chans):
            beats.append({"data": int(ch[k]), "channel": c})
    return beats

class TestLFO(unittest.TestCase):
    # verify-tier: model — accumulator, ROM sine / folded triangle / saw / square and the
    # amplitude scaling, bit-exact under backpressure for every shape.
    def test_bit_exact_shapes(self):
        n, inc = 200, 0x0345_6789
        for shape in range(4):
            with self.subTest(shape=shape):
                dut = LiteDSPLFO(with_csr=False)
                dut.phase_inc.reset, dut.shape.reset, dut.amplitude.reset = inc, shape, 20000
                cap = run_stream(dut, None, n, None, ["data"], source_ready_rate=0.7)
                self.assertTrue(np.array_equal(column(cap, "data", 16), lfo_model(inc, n, shape, 20000)))
                self.assertEqual(dut.latency, 1)

    # verify-tier: bound — the frequency is phase_inc * f_s / 2**32: a 1/64-rate triangle has
    # exactly 64-sample periods (zero-crossing spacing) and spans +/- full scale.
    def test_frequency_and_range(self):
        n = 640
        dut = LiteDSPLFO(with_csr=False)
        dut.phase_inc.reset, dut.shape.reset = (1 << 32)//64, 1
        cap = run_stream(dut, None, n, None, ["data"], source_ready_rate=1.0)
        y = column(cap, "data", 16)
        zc = np.nonzero((y[:-1] < 0) & (y[1:] >= 0))[0]                 # Rising crossings.
        self.assertTrue(np.all(np.diff(zc) == 64))
        self.assertGreater(y.max(), 0.98*FS16)
        self.assertLess(y.min(), -0.98*FS16)

    def test_invalid(self):
        for kwargs in ({"lut_depth": 100}, {"phase_bits": 16}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPLFO(with_csr=False, **kwargs)

class TestDelayLine(unittest.TestCase):
    def run_delay(self, dut, beats, mods=None, throttle=0.2, ready_rate=0.7):
        fields = ["data", "channel"] if dut.n_channels > 1 else ["data"]
        captured = []
        gens = [stream_driver(dut.sink, beats, fields, seed=1, throttle=throttle),
                stream_capture(dut.source, captured, len(beats), fields, seed=3, ready_rate=ready_rate)]
        if mods is not None:
            gens.append(stream_driver(dut.sink_mod, [{"data": int(m)} for m in mods], ["data"],
                seed=2, throttle=0.3))
        run_simulation(dut, gens)
        return column(captured, "data", 24)

    # verify-tier: model — per-channel buffer/pointer, damping one-pole, feedback write and
    # mix, bit-exact under backpressure (stereo, 64-frame buffer, delay 9, feedback 0.6).
    def test_bit_exact_plain(self):
        prng  = random.Random(1)
        chans = [[prng.randint(-FS24//2, FS24//2) for _ in range(80)] for _ in range(2)]
        beats = tdm(chans)
        dut   = LiteDSPDelayLine(data_width=24, n_channels=2, max_delay=64, with_csr=False)
        dut.delay.reset, dut.feedback.reset, dut.damping.reset = 9, int(0.6*FS16), 8000
        dut.wet.reset, dut.dry.reset = int(0.7*FS16), int(0.4*FS16)
        got = self.run_delay(dut, beats)
        ref = delay_line_model([b["data"] for b in beats], [b["channel"] for b in beats], 9,
            feedback=int(0.6*FS16), damping=8000, wet=int(0.7*FS16), dry=int(0.4*FS16), max_delay=64)
        self.assertTrue(np.array_equal(got, ref))
        self.assertEqual((dut.cycles_per_sample, dut.latency), (8, 7))

    # verify-tier: model — chorus: LFO modulation stream joined at each frame, fractional
    # delay with linear interpolation, bit-exact with all three streams throttled.
    def test_bit_exact_chorus(self):
        prng  = random.Random(2)
        n_fr  = 80
        chans = [[prng.randint(-FS24//2, FS24//2) for _ in range(n_fr)] for _ in range(2)]
        beats = tdm(chans)
        mods  = lfo_model((1 << 32)//20, n_fr, shape=0, amplitude=FS16)
        dut   = LiteDSPDelayLine(data_width=24, n_channels=2, max_delay=64, modulation=True, with_csr=False)
        dut.delay.reset, dut.mod_depth.reset, dut.feedback.reset = 20, 6, int(0.3*FS16)
        got = self.run_delay(dut, beats, mods)
        ref = delay_line_model([b["data"] for b in beats], [b["channel"] for b in beats], 20,
            feedback=int(0.3*FS16), mod=mods, mod_depth=6, modulation=True, max_delay=64)
        self.assertTrue(np.array_equal(got, ref))
        self.assertEqual(dut.cycles_per_sample, 10)

    # verify-tier: bound — echo impulse response (mono, delay 8, feedback 0.5, wet 1, dry 0):
    # taps at 8, 16, 24, ... with amplitudes 0.5**(k-1) of the impulse within k LSB (one
    # rounding per pass through the loop), nothing between the taps.
    def test_echo_impulse_response(self):
        n   = 60
        dut = LiteDSPDelayLine(data_width=24, n_channels=1, max_delay=16, with_csr=False)
        dut.delay.reset, dut.feedback.reset, dut.wet.reset, dut.dry.reset = 8, 1 << 14, FS16, 0
        x = [1 << 20] + [0]*(n - 1)
        got = self.run_delay(dut, [{"data": v} for v in x], throttle=0.0, ready_rate=1.0)
        for k in range(1, 7):
            expect = (1 << 20)*0.5**(k - 1)*(FS16/(1 << 15))**1
            self.assertLessEqual(abs(int(got[8*k]) - round(expect)), k + 1, f"tap {k}")
        between = np.delete(got, [8*k for k in range(1, 8)])
        self.assertTrue(np.all(between == 0))

    def test_wet_zero_bypass_invalid(self):
        prng  = random.Random(3)
        beats = tdm([[prng.randint(-1000, 1000) for _ in range(20)] for _ in range(2)])
        dut   = LiteDSPDelayLine(data_width=24, max_delay=16, with_csr=False)
        dut.wet.reset, dut.dry.reset = 0, FS16
        got = self.run_delay(dut, beats)
        self.assertTrue(np.array_equal(got, [b["data"] for b in beats]))
        dut = LiteDSPDelayLine(data_width=24, max_delay=16, with_csr=False)
        dut.bypass.reset = 1
        self.assertTrue(np.array_equal(self.run_delay(dut, beats), [b["data"] for b in beats]))
        for kwargs in ({"max_delay": 2}, {"coeff_frac": 16}, {"mod_frac": 0}, {"modulation": 1}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPDelayLine(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
