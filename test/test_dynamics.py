#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.audio.dynamics import LiteDSPCompressor, PRESET_VALUES
from litedsp.audio.design   import log2_from_db, time_constant_coeff

from test.common import run_stream, column
from test.models import compressor_model

FS24 = (1 << 23) - 1

def params(preset, **over):
    thr, sa, sb, att, rel, grm = PRESET_VALUES[preset]
    p = dict(threshold=thr, slope_above=sa, slope_below=sb, attack=att, release=rel, gr_max=grm)
    p.update(over)
    return p

def dbfs(x):
    return 20*np.log10(max(abs(float(x)), 1e-9)/FS24)

class TestCompressor(unittest.TestCase):
    def build(self, preset="compressor", n_channels=2, lookahead=0, **ctrl):
        dut = LiteDSPCompressor(data_width=24, n_channels=n_channels, lookahead=lookahead,
            preset=preset, with_csr=False)
        for k, v in ctrl.items():
            getattr(dut, k).reset = v
        return dut

    def run_comp(self, dut, beats, throttle=0.2, ready_rate=0.7):
        fields = ["data", "channel"] if dut.n_channels > 1 else ["data"]
        cap = run_stream(dut, beats, len(beats), fields, fields, sink_throttle=throttle,
            source_ready_rate=ready_rate)
        return column(cap, "data", 24)

    def stereo_beats(self, n, prng, bursts=True):
        beats = []
        for k in range(n):
            level = [0.01, 0.1, 0.5, 1.0][(k//40) % 4] if bursts else 0.3
            for c in range(2):
                beats.append({"data": int(prng.randint(-FS24, FS24)*level), "channel": c})
        return beats

    # verify-tier: model — peak detector, hard-knee gain computer, Q7.24 smoother, exp2 gain
    # and rounding, bit-exact under backpressure over level bursts (compressor preset).
    def test_bit_exact_peak_stereo(self):
        prng  = random.Random(1)
        beats = self.stereo_beats(100, prng)
        dut   = self.build()
        got   = self.run_comp(dut, beats)
        ref, _ = compressor_model([b["data"] for b in beats], [b["channel"] for b in beats],
            **params("compressor"))
        self.assertTrue(np.array_equal(got, ref))

    # verify-tier: model — RMS detector, stereo link (previous-frame maximum, shared smoother)
    # and a 4-frame lookahead, bit-exact.
    def test_bit_exact_rms_link_lookahead(self):
        prng  = random.Random(2)
        beats = self.stereo_beats(100, prng)
        dut   = self.build(lookahead=4, detector=1, stereo_link=1, rms_shift=4)
        got   = self.run_comp(dut, beats)
        ref, _ = compressor_model([b["data"] for b in beats], [b["channel"] for b in beats],
            detector=1, stereo_link=1, rms_shift=4, lookahead=4, **params("compressor"))
        self.assertTrue(np.array_equal(got, ref))

    # verify-tier: bound — static curve on DC levels (exact peak level): -40..0 dBFS through
    # the -20 dB / 4:1 compressor with 0 dB make-up must give out = in - 0.75*max(in + 20, 0)
    # within 0.1 dB (LUT log2 and exp2: 0.02 dB each); mono, free flow, 1500 beats with a
    # 0.5 ms attack (24 samples) so the smoother has fully settled.
    def test_static_curve_matches_design(self):
        for in_db in (-40.0, -30.0, -20.0, -10.0, -3.0):
            with self.subTest(in_db=in_db):
                a   = int(round(FS24*10**(in_db/20)))
                dut = self.build(n_channels=1, attack=time_constant_coeff(0.5))
                got = self.run_comp(dut, [{"data": a}]*1500, throttle=0.0, ready_rate=1.0)
                out_db = dbfs(got[-1])
                design = in_db - 0.75*max(in_db + 20.0, 0.0)
                self.assertLess(abs(out_db - design), 0.1, f"{out_db:.2f} vs {design:.2f} dB")

    # verify-tier: bound — limiter preset (threshold -1 dBFS, instant attack) with a 16-frame
    # lookahead on 0 dBFS bursts: the gain reduction acts before the delayed peak, so the
    # output never exceeds the threshold by more than 0.3 dB (the two LUTs); a plain limiter
    # without lookahead would let the first samples of a burst through.
    def test_limiter_ceiling_with_lookahead(self):
        beats = ([{"data": 0}]*64 + [{"data": FS24 if k % 2 == 0 else -FS24} for k in range(96)]
                 + [{"data": 0}]*64)*2
        dut = self.build(preset="limiter", n_channels=1, lookahead=16)
        got = self.run_comp(dut, beats, throttle=0.0, ready_rate=1.0)
        self.assertLess(dbfs(np.max(np.abs(got))), -1.0 + 0.3)
        self.assertGreater(dbfs(np.max(np.abs(got))), -1.0 - 0.5)   # Still delivers the level.

    # verify-tier: bound — gate preset: a -60 dBFS signal (10 dB below the -50 dB threshold,
    # 1:8 expansion -> 70 dB, clamped at gr_max = 60 dB) is attenuated by >= 30 dB, a -10 dBFS
    # signal passes within 0.1 dB.
    def test_gate(self):
        for in_db, min_att, max_att in ((-60.0, 30.0, 61.0), (-10.0, -0.1, 0.1)):
            with self.subTest(in_db=in_db):
                a   = int(round(FS24*10**(in_db/20)))
                dut = self.build(preset="gate", n_channels=1)
                got = self.run_comp(dut, [{"data": a}]*600, throttle=0.0, ready_rate=1.0)
                att = in_db - dbfs(got[-1])
                self.assertGreaterEqual(att, min_att, f"attenuation {att:.1f} dB")
                self.assertLessEqual(att, max_att, f"attenuation {att:.1f} dB")

    # verify-tier: bound — attack/release time constants: a -30 -> -10 dBFS step reaches 63 %
    # of its final gain reduction after attack_ms*fs samples (one-pole alpha = 1 - exp(-1/N)):
    # N = 96 (2 ms at 48 kHz) within +/-20 %, and the release back within N = 240 (5 ms).
    def test_attack_release_time_constants(self):
        n_att, n_rel = 96, 240
        dut = self.build(n_channels=1, attack=time_constant_coeff(2.0),
                         release=time_constant_coeff(5.0))
        lo, hi = int(round(FS24*10**(-30/20))), int(round(FS24*10**(-10/20)))
        beats  = [{"data": lo}]*400 + [{"data": hi}]*600 + [{"data": lo}]*800
        got    = self.run_comp(dut, beats, throttle=0.0, ready_rate=1.0)
        g      = got.astype(float)/np.array([b["data"] for b in beats])       # Linear gain.
        g_db   = 20*np.log10(np.maximum(g, 1e-9))
        gr_hi, gr_lo = -g_db[999], -g_db[399]                               # Steady-state GR.
        # Attack: samples until 63 % of the way from gr_lo to gr_hi.
        target = gr_lo + 0.632*(gr_hi - gr_lo)
        k_att  = int(np.argmax(-g_db[400:1000] >= target))
        self.assertLess(abs(k_att - n_att), 0.2*n_att + 4, f"attack {k_att} samples")
        target = gr_hi - 0.632*(gr_hi - gr_lo)
        k_rel  = int(np.argmax(-g_db[1000:] <= target))
        self.assertLess(abs(k_rel - n_rel), 0.2*n_rel + 4, f"release {k_rel} samples")

    def test_latency_cycles_bypass_invalid(self):
        dut = self.build(n_channels=1)
        got = self.run_comp(dut, [{"data": 12345}]*20, throttle=0.0, ready_rate=1.0)
        self.assertEqual(dut.cycles_per_sample, 16)
        dut = self.build(n_channels=2)
        dut.bypass.reset = 1
        beats = self.stereo_beats(20, random.Random(3))
        self.assertTrue(np.array_equal(self.run_comp(dut, beats), [b["data"] for b in beats]))
        for kwargs in ({"preset": "expander"}, {"lookahead": -1}, {"n_channels": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPCompressor(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
