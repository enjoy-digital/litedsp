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

from litedsp.radar.beamform import LiteDSPBeamformer
from litedsp.radar.design   import steering_weights

from test.models import beamformer_model

def simulate(dut, xs, n_out, rates=None, ready_rate=1.0, controls=None, seed=1, watchdog=200000,
             start=0):
    """Drive the element sinks with independent random throttles (after ``start`` idle cycles),
    capture n_out beats."""
    prng = random.Random(seed)
    out  = []
    n    = len(xs[0][0])
    rates = rates or [1.0]*len(xs)
    def driver(e):
        def gen():
            for _ in range(start):
                yield
            for k in range(n):
                yield dut.sinks[e].i.eq(int(xs[e][0][k])); yield dut.sinks[e].q.eq(int(xs[e][1][k]))
                yield dut.sinks[e].valid.eq(1)
                yield
                while not (yield dut.sinks[e].ready):
                    yield
                yield dut.sinks[e].valid.eq(0)
                while prng.random() > rates[e]:
                    yield
        return gen()
    def capture():
        cycles = 0
        while len(out) < n_out:
            yield dut.source.ready.eq(int(prng.random() < ready_rate))
            yield
            cycles += 1
            assert cycles < watchdog, "watchdog"
            if (yield dut.source.valid) and (yield dut.source.ready):
                beat = {"i": (yield dut.source.i), "q": (yield dut.source.q)}
                if hasattr(dut.source, "channel"):
                    beat["channel"] = (yield dut.source.channel)
                out.append(beat)
    gens = [driver(e) for e in range(len(xs))] + [capture()] + (controls or [])
    run_simulation(dut, gens)
    return out

def signed(v, w):
    return v - (1 << w) if v >= 1 << (w - 1) else v

class TestBeamformer(unittest.TestCase):
    # verify-tier: model — two beams x four elements x 150 random samples with independently
    # throttled element sinks and a throttled source: bit-exact beams and channel tags, a
    # watchdog guards the join; single-beam latency pinned at 3.
    def test_bit_exact(self):
        prng = random.Random(2)
        xs   = [([prng.randint(-30000, 30000) for _ in range(150)],
                 [prng.randint(-30000, 30000) for _ in range(150)]) for _ in range(4)]
        w    = [steering_weights(4, 15.0, 0.5, "rect"), steering_weights(4, -30.0, 0.5, "hamming")]
        dut  = LiteDSPBeamformer(n_elements=4, n_beams=2, with_csr=False)
        load = []
        for b, (re, im) in enumerate(w):
            for e in range(4):
                load.append((b*4 + e, re[e], im[e]))
        def loader():
            for idx, re, im in load:
                yield dut.weight_index.eq(idx); yield dut.weight_re.eq(re); yield dut.weight_im.eq(
                    im)
                yield dut.weight_we.eq(1)
                yield
            yield dut.weight_we.eq(0)
            yield dut.commit.eq(1)
            yield
            yield dut.commit.eq(0)
            yield
        out = simulate(dut, xs, 2*150, rates=[0.7, 0.9, 0.5, 0.8], ready_rate=0.7,
                       controls=[loader()], start=16)
        (ri, rq, rc), sat = beamformer_model(xs, w)
        self.assertEqual([signed(b["i"], 16) for b in out], ri.tolist())
        self.assertEqual([signed(b["q"], 16) for b in out], rq.tolist())
        self.assertEqual([b["channel"] for b in out], rc.tolist())
        self.assertEqual(sat, 0)
        self.assertEqual(LiteDSPBeamformer(with_csr=False).latency, 3)
        self.assertIsNone(dut.latency)

    # verify-tier: bound — a plane wave from 20 degrees on a half-wavelength 8-element array with
    # the beam steered to it: the output equals the element amplitude within 1 % (unity array
    # gain through the 1/N weights); a wave from the first null (sin = sin 20 + 1/4) is >= 20 dB
    # down; the reset (broadside) weights sum the elements.
    def test_steering_gain_and_null(self):
        N, A = 8, 20000
        def wave(sin_theta, n=32):
            return [([int(round(A*math.cos(2*math.pi*0.5*e*sin_theta + 2*math.pi*0.05*k)))
                                           for k in range(n)],
                     [int(round(A*math.sin(2*math.pi*0.5*e*sin_theta + 2*math.pi*0.05*k)))
                                           for k in range(n)]) for e in range(N)]
        re, im = steering_weights(N, 20.0, 0.5, "rect")
        def run(xs):
            dut = LiteDSPBeamformer(n_elements=N, n_beams=1, with_csr=False)
            def loader():
                for e in range(N):
                    yield dut.weight_index.eq(e); yield dut.weight_re.eq(
                        re[e]); yield dut.weight_im.eq(im[e]); yield dut.weight_we.eq(1)
                    yield
                yield dut.weight_we.eq(0); yield dut.commit.eq(1)
                yield
                yield dut.commit.eq(0)
            out = simulate(dut, xs, 32, controls=[loader()], start=16)
            y = np.array([signed(b["i"], 16) + 1j*signed(b["q"], 16) for b in out[8:]])
            return np.mean(np.abs(y))
        s0 = math.sin(math.radians(20.0))
        main = run(wave(s0))
        null = run(wave(s0 + 1/(0.5*N)))
        self.assertLessEqual(abs(main/A - 1.0), 0.01)
        self.assertGreaterEqual(20*math.log10(main/max(null, 1)), 20.0)
        # Reset weights: broadside average of identical elements passes the amplitude.
        dut = LiteDSPBeamformer(n_elements=N, n_beams=1, with_csr=False)
        out = simulate(dut, wave(0.0), 32)
        self.assertLessEqual(abs(np.mean(
            np.abs([signed(b["i"], 16) + 1j*signed(b["q"], 16) for b in out[8:]]))/A - 1.0), 0.01)

    # verify-tier: bound — a commit issued mid-sample takes effect exactly at the next sample
    # boundary (both beams of a sample use the same weight set); the saturation flag is sticky.
    def test_commit_atomicity_and_saturation(self):
        prng = random.Random(4)
        n    = 40
        xs   = [([prng.randint(-20000, 20000) for _ in range(n)],
                 [prng.randint(-20000, 20000) for _ in range(n)]) for _ in range(2)]
        dut  = LiteDSPBeamformer(n_elements=2, n_beams=2, with_csr=False)
        w_new = ([1 << 14, 0], [0, 0])                             # Beam 0/1 <- element 0 only, x2.
        def loader():
            for _ in range(60):
                yield
            for b in range(2):
                for e in range(2):
                    yield dut.weight_index.eq(b*2 + e); yield dut.weight_re.eq(
                        w_new[0][e]); yield dut.weight_im.eq(0); yield dut.weight_we.eq(1)
                    yield
            yield dut.weight_we.eq(0); yield dut.commit.eq(1)
            yield
            yield dut.commit.eq(0)
        out = simulate(dut, xs, 2*n, ready_rate=0.5, controls=[loader()])
        w0 = int(round((1 << 14)/2))
        (old_i, _, _), _ = beamformer_model(xs, [([w0, w0], [0, 0])]*2)
        (new_i, _, _), _ = beamformer_model(xs, [w_new]*2)
        got = [signed(b["i"], 16) for b in out]
        k = next(i for i in range(0, 2*n, 2) if got[i] != old_i[i])
        self.assertEqual(k % 2, 0)
        self.assertEqual(got[:k], old_i[:k].tolist())
        self.assertEqual(got[k:], new_i[k:].tolist())
        self.assertGreater(k, 0)
        xs_big = [([30000]*8, [0]*8), ([30000]*8, [0]*8)]
        # x2 gain: saturates.
        dut = LiteDSPBeamformer(n_elements=2, n_beams=1, shift=13, with_csr=False)
        self.sat = None
        def watch():
            while True:
                self.sat = (yield dut.saturated)
                yield
        simulate(dut, xs_big, 8, controls=[passive(watch)()])
        self.assertEqual(self.sat, 1)
        for kwargs in ({"n_elements": 17}, {"n_beams": 9}, {"weight_frac": 16}, {"shift": 40}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPBeamformer(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
