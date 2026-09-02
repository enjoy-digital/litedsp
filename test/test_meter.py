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

from litedsp.audio.meter  import LiteDSPPeakMeter, LiteDSPLoudness
from litedsp.audio.design import k_weighting_sos

from test.common import run_stream, column
from test.models import peak_meter_model, loudness_model, log2_model

FS24 = (1 << 23) - 1

def tdm(chans):
    return [{"data": int(v), "channel": c} for k in range(len(chans[0])) for c, v in
            enumerate(x[k] for x in chans)]

def drive(dut, beats, gap=0, prng=None, log=None):
    """Push beats with ``source.ready`` held high; ``gap`` idle cycles (random up to ``gap`` when
    ``prng`` is given) between beats. ``log(k)`` runs after beat k has been accepted."""
    yield dut.source.ready.eq(1)
    for k, b in enumerate(beats):
        yield dut.sink.valid.eq(1)
        yield dut.sink.data.eq(b["data"])
        if hasattr(dut.sink, "channel"):
            yield dut.sink.channel.eq(b["channel"])
        yield
        yield dut.sink.valid.eq(0)
        yield                                                    # Transfer edge: state updated.
        if log is not None:
            yield from log(k)
        for _ in range(prng.randint(0, gap) if prng else gap):
            yield
    for _ in range(4):
        yield

def sos_gain(sections, f, fs):
    """|H(f)| of float ``[b0, b1, b2, a0, a1, a2]`` rows."""
    z = np.exp(-2j*np.pi*f/fs)
    h = 1.0
    for b0, b1, b2, a0, a1, a2 in sections:
        h *= (b0 + b1*z + b2*z*z)/(a0 + a1*z + a2*z*z)
    return abs(h)

class TestPeakMeter(unittest.TestCase):
    # verify-tier: model — peak/hold trajectories read back after every accepted beat match the
    # integer model (fast decay so the fall-back path is exercised), clip counts and flags too.
    def test_trajectory_bit_exact(self):
        prng  = random.Random(1)
        n     = 160
        xs    = [[prng.choice([prng.randint(-FS24, FS24), prng.randint(-2000, 2000), FS24, -FS24 - 1])
                  for _ in range(n)] for _ in range(2)]
        beats = tdm(xs)
        dut   = LiteDSPPeakMeter(data_width=24, n_channels=2, decay_shift=3, clip_threshold=FS24,
            with_csr=False)
        got_p, got_h = [], []
        def log(k):
            c = beats[k]["channel"]
            got_p.append((yield dut.peak[c]))
            got_h.append((yield dut.hold[c]))
        run_simulation(dut, drive(dut, beats, gap=3, prng=prng, log=log))
        p, h, count, clip = peak_meter_model([b["data"] for b in beats], [b["channel"] for b in beats],
            n_channels=2, decay_shift=3, clip_threshold=FS24)
        self.assertTrue(np.array_equal(got_p, p))
        self.assertTrue(np.array_equal(got_h, h))
        self.assertEqual(dut.latency, 0)

    # verify-tier: bound — an impulse decays geometrically, (1 - 2**-ds)**k after k silent beats
    # (ds=6, k=63: 0.372, about e**-1 per 2**ds beats) and the log2 scan reports the LUT log2 of the peak.
    def test_decay_and_log2(self):
        dut   = LiteDSPPeakMeter(data_width=24, n_channels=2, decay_shift=6, with_csr=False)
        beats = tdm([[1 << 22] + [0]*63, [0]*64])
        seen  = {}
        def log(k):
            if k == 0:
                for _ in range(8):
                    yield
                seen["log2"] = (yield dut.peak_log2[0])
            if k == 2*63:
                seen["peak"] = (yield dut.peak[0])
        run_simulation(dut, drive(dut, beats, log=log))
        self.assertAlmostEqual(seen["peak"]/(1 << 22), (1 - 2**-6)**63, delta=0.005)
        self.assertEqual(seen["log2"], int(log2_model(np.array([1 << 22]), in_width=24, frac_bits=8, lut=True)[0]))

    def test_clip_irq_clear(self):
        dut   = LiteDSPPeakMeter(data_width=24, n_channels=2, with_csr=False, with_irq=True)
        beats = tdm([[100]*8, [FS24, -FS24 - 1, FS24, 0, 0, FS24, 0, 0]])
        seen  = {}
        def log(k):
            if k == len(beats) - 1:
                seen["count"] = [(yield dut.clip_count[0]), (yield dut.clip_count[1])]
                seen["clip"]  = (yield dut.clip)
                seen["irq"]   = (yield dut.ev.clip.pending)
                yield dut.clear.eq(1)
                yield
                yield dut.clear.eq(0)
                yield
                seen["after"] = ((yield dut.clip_count[1]), (yield dut.clip), (yield dut.hold[1]))
        run_simulation(dut, drive(dut, beats, log=log))
        self.assertEqual(seen["count"], [0, 4])
        self.assertEqual(seen["clip"], 0b10)
        self.assertEqual(seen["irq"], 1)
        self.assertEqual(seen["after"], (0, 0, 0))

    def test_passthrough(self):
        prng  = random.Random(2)
        beats = tdm([[prng.randint(-FS24, FS24) for _ in range(100)] for _ in range(2)])
        dut   = LiteDSPPeakMeter(data_width=24, n_channels=2, with_csr=False)
        cap   = run_stream(dut, beats, len(beats), ["data", "channel"], ["data", "channel"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data", 24), [b["data"] for b in beats]))
        self.assertEqual(column(cap, "channel").tolist(), [b["channel"] for b in beats])

    def test_invalid(self):
        for kwargs in ({"decay_shift": 16}, {"n_channels": 0}, {"clip_threshold": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPPeakMeter(with_csr=False, **kwargs)

class TestLoudness(unittest.TestCase):
    # verify-tier: model — the hop sums latched on ``update`` equal the model (K-weighting EQ
    # model, squares, Q2.14 weights); beats paced at the engine rate.
    def test_hop_sums_bit_exact(self):
        prng  = random.Random(3)
        hop   = 32
        beats = tdm([[prng.randint(-FS24//2, FS24//2) for _ in range(4*hop)] for _ in range(2)])
        dut   = LiteDSPLoudness(data_width=24, n_channels=2, sample_rate=48000, hop_samples=hop,
            channel_weights=[1.0, 1.41], with_csr=False)
        sums  = []
        @passive
        def monitor():
            while True:
                if (yield dut.update):
                    sums.append((yield dut.sum_sq))
                yield
        run_simulation(dut, [drive(dut, beats, gap=dut.cycles_per_sample), monitor()])
        ref = loudness_model([b["data"] for b in beats], [b["channel"] for b in beats], dut.sections,
            n_channels=2, hop_samples=hop, channel_weights=dut.channel_weights)
        self.assertEqual(len(ref), 4)
        self.assertEqual(sums, ref)
        self.assertEqual(dut.latency, 0)

    # verify-tier: bound — a -20 dBFS 997 Hz stereo tone reads the K-weighted level within
    # 0.2 dB of the design (LKFS = -0.691 + 10 log10(sum_sq/(hop*FS^2)); 8 kHz sample rate so
    # the 38 Hz RLB high-pass settles within 400 frames).
    def test_tone_level(self):
        fs, f0, hop = 8000, 997.0, 200
        n     = 400 + 3*hop
        tone  = [int(round(0.1*(1 << 23)*math.sin(2*math.pi*f0*k/fs))) for k in range(n)]
        beats = tdm([tone, tone])
        dut   = LiteDSPLoudness(data_width=24, n_channels=2, sample_rate=fs, hop_samples=hop,
            with_csr=False)
        sums  = []
        @passive
        def monitor():
            while True:
                if (yield dut.update):
                    sums.append((yield dut.sum_sq))
                yield
        run_simulation(dut, [drive(dut, beats, gap=dut.cycles_per_sample), monitor()])
        self.assertEqual(len(sums), 5)
        lkfs = -0.691 + 10*math.log10(sums[-1]/(hop*float(1 << 23)**2))
        gain = sos_gain(k_weighting_sos(fs), f0, fs)
        expected = -0.691 + 10*math.log10(2*0.5*0.1**2*gain**2)
        self.assertAlmostEqual(lkfs, expected, delta=0.2)

    def test_overrun_and_clear(self):
        dut   = LiteDSPLoudness(data_width=24, n_channels=2, hop_samples=4, with_csr=False)
        beats = tdm([[1000]*8, [1000]*8])
        seen  = {}
        def log(k):
            if k == len(beats) - 1:
                for _ in range(40):
                    yield
                seen["overrun"] = (yield dut.overrun)
                seen["hops"]    = (yield dut.hop_count)
                yield dut.clear.eq(1)
                yield
                yield dut.clear.eq(0)
                yield
                seen["after"] = ((yield dut.overrun), (yield dut.hop_count))
        run_simulation(dut, drive(dut, beats, log=log))          # Back-to-back: engine busy.
        self.assertEqual(seen["overrun"], 1)
        self.assertEqual(seen["after"], (0, 0))
        self.assertLess(seen["hops"], 2)

    def test_passthrough(self):
        prng  = random.Random(4)
        beats = tdm([[prng.randint(-FS24, FS24) for _ in range(100)] for _ in range(2)])
        dut   = LiteDSPLoudness(data_width=24, n_channels=2, hop_samples=8, with_csr=False)
        cap   = run_stream(dut, beats, len(beats), ["data", "channel"], ["data", "channel"],
            sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(cap, "data", 24), [b["data"] for b in beats]))

    def test_invalid(self):
        for kwargs in ({"hop_samples": 0}, {"channel_weights": [1.0]}, {"channel_weights": [1.0, 4.0]}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPLoudness(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
