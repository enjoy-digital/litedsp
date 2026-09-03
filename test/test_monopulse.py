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

from litedsp.radar.beamform import LiteDSPMonopulse

from test.models import monopulse_model

def simulate(dut, a, b, n_out, rates=(1.0, 1.0), ready_rate=1.0, seed=1, tags=False):
    prng = random.Random(seed)
    out  = []
    def driver(ep, x, rate):
        def gen():
            for k, v in enumerate(x):
                yield ep.i.eq(int(v.real)); yield ep.q.eq(int(v.imag)); yield ep.valid.eq(1)
                if tags:
                    yield ep.first.eq(int(k % 8 == 0)); yield ep.last.eq(int(k % 8 == 7))
                yield
                while not (yield ep.ready):
                    yield
                yield ep.valid.eq(0)
                while prng.random() > rate:
                    yield
        return gen()
    def capture():
        cycles = 0
        while len(out) < n_out:
            yield dut.source.ready.eq(int(prng.random() < ready_rate))
            yield
            cycles += 1
            assert cycles < 100000, "watchdog"
            if (yield dut.source.valid) and (yield dut.source.ready):
                out.append(((yield dut.source.angle), (yield dut.source.first), (yield dut.source.last)))
    run_simulation(dut, [driver(dut.sink_a, a, rates[0]), driver(dut.sink_b, b, rates[1]), capture()])
    return out

def signed(v, w):
    return v - (1 << w) if v >= 1 << (w - 1) else v

class TestMonopulse(unittest.TestCase):
    # verify-tier: model — 300 random sample pairs through independently throttled sinks and a
    # throttled source: bit-exact angles against mixer + vectoring-CORDIC models, sink_a's frame
    # tags carried through; pinned latency.
    def test_bit_exact(self):
        prng = random.Random(3)
        a = np.array([complex(prng.randint(-30000, 30000), prng.randint(-30000, 30000)) for _ in range(300)])
        b = np.array([complex(prng.randint(-30000, 30000), prng.randint(-30000, 30000)) for _ in range(300)])
        dut = LiteDSPMonopulse(with_csr=False)
        out = simulate(dut, a, b, 300, rates=(0.7, 0.8), ready_rate=0.7, tags=True)
        ref = monopulse_model(a.real, a.imag, b.real, b.imag)
        self.assertEqual([signed(o[0], 16) for o in out], ref.tolist())
        self.assertEqual([o[1] for o in out], [int(k % 8 == 0) for k in range(300)])
        self.assertEqual([o[2] for o in out], [int(k % 8 == 7) for k in range(300)])
        self.assertEqual(dut.latency, 2 + dut.cordic.latency)

    # verify-tier: bound — b = a * exp(j phi) for phi swept over the circle: the angle is -phi
    # within 2 LSB (16-bit full circle) at 3/4 scale.
    def test_phase_sweep(self):
        phis = np.linspace(-math.pi, math.pi, 64, endpoint=False)
        a = np.array([24000*np.exp(1j*0.3)]*64)
        b = a*np.exp(1j*phis)
        a = np.round(a); b = np.round(b)
        dut = LiteDSPMonopulse(with_csr=False)
        out = simulate(dut, a, b, 64)
        angles = np.array([signed(o[0], 16) for o in out])
        expect = np.round(-phis/(2*math.pi)*65536)
        err = (angles - expect + 32768) % 65536 - 32768
        self.assertLessEqual(int(np.max(np.abs(err))), 2)

if __name__ == "__main__":
    unittest.main()
