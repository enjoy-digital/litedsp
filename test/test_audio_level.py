#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.audio.level import LiteDSPVolume, LiteDSPStereoMatrix

from test.common import run_stream, column
from test.models import volume_model, stereo_matrix_model

FS24 = (1 << 23) - 1
ONE  = 1 << 19                                   # 1.0 in the default Q5.19 gain format.

def tdm_beats(samples, n_channels):
    """Interleave per-channel sample lists into TDM beats [{data, channel}]."""
    beats = []
    for k in range(len(samples[0])):
        for c in range(n_channels):
            beats.append({"data": int(samples[c][k]), "channel": c})
    return beats

class TestVolume(unittest.TestCase):
    def run_volume(self, beats, dut, throttle=0.2, ready_rate=0.7, extra=None):
        fields = ["data", "channel"] if dut.n_channels > 1 else ["data"]
        cap = run_stream(dut, beats, len(beats), fields, fields, sink_throttle=throttle,
            source_ready_rate=ready_rate, extra=extra)
        return column(cap, "data", 24), (column(cap, "channel") if dut.n_channels > 1 else None)

    # verify-tier: model — per-channel ramp state advances per accepted beat of that channel;
    # bit-exact under backpressure with gain and mute changes mid-stream (counted in beats).
    def test_bit_exact_with_gain_and_mute_changes(self):
        n, n_ch = 150, 2
        prng  = random.Random(1)
        xs    = [[prng.randint(-FS24, FS24) for _ in range(n)] for _ in range(n_ch)]
        beats = tdm_beats(xs, n_ch)
        dut   = LiteDSPVolume(data_width=24, n_channels=n_ch, with_csr=False)
        dut.gains[0].reset, dut.gains[1].reset = int(0.5*ONE), int(2.0*ONE)
        events = {100: ("gain", 1, int(0.25*ONE)), 200: ("mute", None, 0b01)}

        @passive
        def ctrl():
            accepted = 0
            while True:
                yield
                if (yield dut.sink.valid) and (yield dut.sink.ready):
                    accepted += 1
                    if accepted in events:
                        kind, ch, v = events[accepted]
                        if kind == "gain":
                            yield dut.gains[ch].eq(v)
                        else:
                            yield dut.mute.eq(v)

        got, chs = self.run_volume(beats, dut, extra=[ctrl()])
        nb = len(beats)
        g0 = np.full(nb, int(0.5*ONE)); g1 = np.array([int(2.0*ONE)]*100 + [int(0.25*ONE)]*(nb - 100))
        mute = np.array([0]*200 + [0b01]*(nb - 200))
        ref = volume_model([b["data"] for b in beats], [b["channel"] for b in beats], [g0, g1], mute)
        self.assertTrue(np.array_equal(got, ref))
        self.assertTrue(np.array_equal(chs, [b["channel"] for b in beats]))
        self.assertEqual(dut.latency, 2)

    # verify-tier: bound — a -6 dB gain step: the applied gain moves monotonically by at most
    # max(|delta| >> ramp_shift, 1) per sample and converges exactly (no dead band), so the
    # output of a constant input is monotonic and reaches the exact final value.
    def test_ramp_monotonic_and_exact(self):
        n = 3000
        dut = LiteDSPVolume(data_width=24, n_channels=1, ramp_shift=6, with_csr=False)
        dut.gains[0].reset = ONE

        @passive
        def ctrl():
            for _ in range(20):
                yield
            yield dut.gains[0].eq(ONE//2)
            while True:
                yield

        got, _ = self.run_volume([{"data": 1 << 22}]*n, dut, throttle=0.0, ready_rate=1.0,
            extra=[ctrl()])
        d = np.diff(got.astype(np.int64))
        self.assertTrue(np.all(d[5:] <= 0))                       # Monotonic decrease.
        self.assertEqual(int(got[-1]), (1 << 22)//2)              # Exact -6 dB.
        self.assertGreater(int(np.argmax(got == (1 << 22)//2)), 100)   # Ramped, not stepped.

    def test_mute_fades_to_zero_and_n_channels(self):
        for n_ch in (1, 2, 8):
            with self.subTest(n_channels=n_ch):
                n   = 60
                dut = LiteDSPVolume(data_width=24, n_channels=n_ch, ramp_shift=2, with_csr=False)
                dut.mute.reset = (1 << n_ch) - 1
                xs  = [[FS24//2]*n for _ in range(n_ch)]
                beats = tdm_beats(xs, n_ch) if n_ch > 1 else [{"data": FS24//2}]*n
                got, _ = self.run_volume(beats, dut, throttle=0.0, ready_rate=1.0)
                self.assertEqual(int(got[-1]), 0)
                self.assertGreater(int(got[0]), 0)                # Fading, not cut.

    def test_bypass_and_invalid(self):
        dut = LiteDSPVolume(data_width=24, n_channels=2, with_csr=False)
        dut.bypass.reset, dut.gains[0].reset = 1, 0
        beats = tdm_beats([[1234, -5678, 9], [42, -42, 7]], 2)
        got, chs = self.run_volume(beats, dut)
        self.assertTrue(np.array_equal(got, [b["data"] for b in beats]))
        for kwargs in ({"n_channels": 0}, {"ramp_shift": 0}, {"gain_frac": 23}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPVolume(with_csr=False, **kwargs)

class TestStereoMatrix(unittest.TestCase):
    def run_matrix(self, l, r, coeffs, throttle=0.2, ready_rate=0.7, bypass=0):
        dut = LiteDSPStereoMatrix(data_width=24, with_csr=False)
        for name, v in zip("abcd", coeffs):
            getattr(dut, name).reset = v
        dut.bypass.reset = bypass
        beats = tdm_beats([l, r], 2)
        cap = run_stream(dut, beats, len(beats), ["data", "channel"], ["data", "channel"],
            sink_throttle=throttle, source_ready_rate=ready_rate)
        d, ch = column(cap, "data", 24), column(cap, "channel")
        return dut, d[0::2], d[1::2], ch

    # verify-tier: model — four products on one multiplier, one rounding per output.
    def test_bit_exact_random_matrix(self):
        n    = 150
        prng = random.Random(2)
        l = [prng.randint(-FS24, FS24) for _ in range(n)]
        r = [prng.randint(-FS24, FS24) for _ in range(n)]
        coeffs = [prng.randint(-(1 << 16), 1 << 16) for _ in range(4)]
        dut, gl, gr, ch = self.run_matrix(l, r, coeffs)
        rl, rr = stereo_matrix_model(l, r, *coeffs)
        self.assertTrue(np.array_equal(gl, rl) and np.array_equal(gr, rr))
        self.assertTrue(np.array_equal(ch, [0, 1]*n))
        self.assertEqual(dut.cycles_per_frame, 8)

    # verify-tier: bound — mid/side encode then decode is the identity within 1 LSB (two
    # roundings); constant-power center pan attenuates both channels by 3.01 dB +/- 0.05.
    def test_ms_round_trip_and_pan(self):
        n    = 200
        prng = random.Random(3)
        l = [prng.randint(-FS24//2, FS24//2) for _ in range(n)]
        r = [prng.randint(-FS24//2, FS24//2) for _ in range(n)]
        half, one = 1 << 14, 1 << 15
        _, m, s, _ = self.run_matrix(l, r, (half, half, half, -half), throttle=0.0, ready_rate=1.0)
        _, gl, gr, _ = self.run_matrix(list(m), list(s), (one, one, one, -one), throttle=0.0, ready_rate=1.0)
        self.assertLessEqual(np.max(np.abs(gl - np.array(l))), 1)
        self.assertLessEqual(np.max(np.abs(gr - np.array(r))), 1)
        k = int(round(np.cos(np.pi/4)*one))
        _, pl, pr, _ = self.run_matrix([FS24//2]*n, [FS24//2]*n, (k, 0, 0, k), throttle=0.0, ready_rate=1.0)
        for v in (pl[-1], pr[-1]):
            self.assertLess(abs(20*np.log10(int(v)/(FS24//2)) + 3.01), 0.05)

    def test_bypass_preserves_order_and_invalid(self):
        l, r = [1, 2, 3, 4], [-1, -2, -3, -4]
        _, gl, gr, ch = self.run_matrix(l, r, (0, 0, 0, 0), bypass=1)
        self.assertTrue(np.array_equal(gl, l) and np.array_equal(gr, r))
        self.assertTrue(np.array_equal(ch, [0, 1]*4))
        for kwargs in ({"coeff_frac": 17}, {"coeff_frac": 0}, {"data_width": 4}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPStereoMatrix(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
