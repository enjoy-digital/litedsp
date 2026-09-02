#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.motor.transforms import (LiteDSPClarke, LiteDSPInverseClarke, LiteDSPSinCos,
    LiteDSPAngleRamp, LiteDSPPark, LiteDSPInversePark)

from test.common import run_stream, stream_driver, stream_capture, column, assert_snr
from test.models import (clarke_model, inverse_clarke_model, sincos_model, angle_ramp_model,
    park_model, inverse_park_model)

AW = 16                                        # Angle width: full turn = 2**16.

def balanced_abc(theta, amp):
    """Three-phase balanced set of peak ``amp`` at electrical angles ``theta`` (radians)."""
    a = np.round(amp*np.cos(theta)).astype(np.int64)
    b = np.round(amp*np.cos(theta - 2*np.pi/3)).astype(np.int64)
    c = np.round(amp*np.cos(theta + 2*np.pi/3)).astype(np.int64)
    return a, b, c

def run_park(dut, iq, angles, n, throttle=(0.2, 0.3), ready_rate=0.7):
    """Drive the two sinks of a Park/inverse-Park block independently; return (i, q)."""
    captured = []
    run_simulation(dut, [
        stream_driver(dut.sink, [{"i": int(i), "q": int(q)} for i, q in zip(*iq)], ["i", "q"],
            seed=11, throttle=throttle[0]),
        stream_driver(dut.sink_angle, [{"angle": int(a)} for a in angles], ["angle"],
            seed=12, throttle=throttle[1]),
        stream_capture(dut.source, captured, n, ["i", "q"], seed=13, ready_rate=ready_rate),
    ])
    return column(captured, "i", 16), column(captured, "q", 16)

class TestClarke(unittest.TestCase):
    # verify-tier: model — one rounding per output; bit-exact under randomized backpressure.
    def test_bit_exact(self):
        n    = 300
        prng = random.Random(1)
        a, b, c = ([prng.randint(-30000, 30000) for _ in range(n)] for _ in range(3))
        for three_wire in (False, True):
            with self.subTest(three_wire=three_wire):
                dut = LiteDSPClarke(data_width=16, three_wire=three_wire, with_csr=False)
                cap = run_stream(dut, [{"a": a[k], "b": b[k], "c": c[k]} for k in range(n)], n,
                    ["a", "b", "c"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
                ra, rb = clarke_model(a, b, c, three_wire=three_wire)
                self.assertTrue(np.array_equal(column(cap, "i", 16), ra))
                self.assertTrue(np.array_equal(column(cap, "q", 16), rb))
                self.assertEqual(dut.latency, 1)

    # verify-tier: bound — a balanced set of peak A must map to a vector of magnitude A
    # (amplitude invariance): the 3 input roundings (0.5 LSB each, scaled by the 2/3 and
    # 1/sqrt(3) constants) plus one output rounding bound the radius error at ~2 LSB.
    def test_balanced_set_maps_to_circle(self):
        n, amp = 2000, 20000
        theta   = 2*np.pi*np.arange(n)*7/n
        a, b, c = balanced_abc(theta, amp)
        for three_wire in (False, True):
            with self.subTest(three_wire=three_wire):
                dut = LiteDSPClarke(data_width=16, three_wire=three_wire, with_csr=False)
                cap = run_stream(dut, [{"a": int(a[k]), "b": int(b[k]), "c": int(c[k])}
                    for k in range(n)], n, ["a", "b", "c"], ["i", "q"],
                    sink_throttle=0.0, source_ready_rate=1.0)
                v = column(cap, "i", 16) + 1j*column(cap, "q", 16)
                self.assertLess(np.max(np.abs(np.abs(v) - amp)), 2.5)
                # Space-vector angle tracks the electrical angle (no phase offset).
                err = np.angle(v*np.exp(-1j*theta))
                self.assertLess(np.max(np.abs(err)), 3e-4)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            LiteDSPClarke(three_wire="yes", with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPClarke(data_width=2, with_csr=False)

class TestInverseClarke(unittest.TestCase):
    # verify-tier: model.
    def test_bit_exact(self):
        n    = 300
        prng = random.Random(2)
        i = [prng.randint(-30000, 30000) for _ in range(n)]
        q = [prng.randint(-30000, 30000) for _ in range(n)]
        dut = LiteDSPInverseClarke(data_width=16, with_csr=False)
        cap = run_stream(dut, [{"i": i[k], "q": q[k]} for k in range(n)], n, ["i", "q"],
            ["a", "b", "c"], sink_throttle=0.2, source_ready_rate=0.7)
        ra, rb, rc = inverse_clarke_model(i, q)
        for f, r in (("a", ra), ("b", rb), ("c", rc)):
            self.assertTrue(np.array_equal(column(cap, f, 16), r), f)
        self.assertEqual(dut.latency, 1)

    # verify-tier: bound — abc -> Clarke -> inverse Clarke round trip within 1 LSB (two
    # rounding points; the input set sums to zero so the reconstruction is exact in theory).
    def test_round_trip(self):
        n, amp = 2000, 24000
        theta   = 2*np.pi*np.arange(n)*5/n
        a, b, c = balanced_abc(theta, amp)
        alpha, beta = clarke_model(a, b, c)
        dut = LiteDSPInverseClarke(data_width=16, with_csr=False)
        cap = run_stream(dut, [{"i": int(alpha[k]), "q": int(beta[k])} for k in range(n)], n,
            ["i", "q"], ["a", "b", "c"], sink_throttle=0.0, source_ready_rate=1.0)
        for f, ref in (("a", a), ("b", b), ("c", c)):
            self.assertLessEqual(np.max(np.abs(column(cap, f, 16) - ref)), 1, f)

class TestSinCos(unittest.TestCase):
    def run_sincos(self, angles, method="rom", lut_depth=1024, free=False):
        dut = LiteDSPSinCos(data_width=16, angle_width=AW, lut_depth=lut_depth, method=method,
            with_csr=False)
        cap = run_stream(dut, [{"angle": int(a)} for a in angles], len(angles), ["angle"],
            ["i", "q"], sink_throttle=0.0 if free else 0.2, source_ready_rate=1.0 if free else 0.7)
        return dut, column(cap, "i", 16), column(cap, "q", 16)

    # verify-tier: model — both methods bit-exact vs their models under backpressure.
    def test_bit_exact(self):
        prng   = random.Random(3)
        angles = [prng.randint(-(1 << (AW - 1)), (1 << (AW - 1)) - 1) for _ in range(300)]
        for method, latency in (("rom", 1), ("cordic", 18)):
            with self.subTest(method=method):
                dut, gc, gs = self.run_sincos(angles, method=method)
                rc, rs = sincos_model(angles, method=method)
                self.assertTrue(np.array_equal(gc, rc))
                self.assertTrue(np.array_equal(gs, rs))
                self.assertEqual(dut.latency, latency)

    # verify-tier: bound — vs the float unit circle. ROM: for LUT-exact angles only the Q1.15
    # amplitude quantization remains (~98 dB); for arbitrary angles the one-sided 10-bit
    # phase truncation dominates: error uniform in [0, 2pi/1024) -> RMS = delta/sqrt(3) =
    # 3.54e-3 rad -> 49.0 dB (measured 49.5 at LITEDSP_SEED=0). CORDIC: ~78 dB as in
    # test_cordic. Gates 3 dB under the seed-0 measurements (feedforward, stall-invariant).
    def test_full_circle_snr(self):
        amp    = (1 << 15) - 1
        exact  = np.arange(-(1 << (AW - 1)), (1 << (AW - 1)), 1 << (AW - 10))   # LUT-exact.
        prng   = random.Random(4)
        arb    = np.array([prng.randint(-(1 << (AW - 1)), (1 << (AW - 1)) - 1) for _ in range(512)])
        for method, angles, min_db in (("rom", exact, 95.0), ("rom", arb, 46.5),
                                       ("cordic", arb, 74.0)):
            with self.subTest(method=method, n=len(angles)):
                _, gc, gs = self.run_sincos(angles, method=method, free=True)
                ref = amp*np.exp(1j*2*np.pi*angles/(1 << AW))
                assert_snr(self, ref, gc.astype(float) + 1j*gs.astype(float), min_db, method)

    def test_invalid(self):
        for kwargs in ({"method": "table"}, {"lut_depth": 1000}, {"lut_depth": 4},
                       {"lut_depth": 1 << 17}, {"stages": 0, "method": "cordic"}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPSinCos(with_csr=False, **kwargs)

class TestAngleRamp(unittest.TestCase):
    # verify-tier: model — accumulator wrap and the top-bit angle slice, under backpressure.
    def test_bit_exact(self):
        n = 200
        for phase_inc in ((1 << 32)//360, 0x1234_5678, 0xF000_0000):
            with self.subTest(phase_inc=phase_inc):
                dut = LiteDSPAngleRamp(angle_width=AW, phase_bits=32, with_csr=False)
                dut.phase_inc.reset = phase_inc
                cap = run_stream(dut, None, n, None, ["angle"], source_ready_rate=0.7)
                self.assertTrue(np.array_equal(column(cap, "angle", AW),
                    angle_ramp_model(phase_inc, n, AW, 32)))
        self.assertIsNone(dut.latency)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            LiteDSPAngleRamp(angle_width=16, phase_bits=8, with_csr=False)

class TestPark(unittest.TestCase):
    # verify-tier: model — join of two independently throttled sinks; the composite is the
    # sin/cos model feeding the mixer model, bit-exact.
    def test_bit_exact_under_backpressure(self):
        n    = 300
        prng = random.Random(5)
        alpha  = [prng.randint(-30000, 30000) for _ in range(n)]
        beta   = [prng.randint(-30000, 30000) for _ in range(n)]
        angles = [prng.randint(-(1 << (AW - 1)), (1 << (AW - 1)) - 1) for _ in range(n)]
        for cls, model in ((LiteDSPPark, park_model), (LiteDSPInversePark, inverse_park_model)):
            for method in ("rom", "cordic"):
                with self.subTest(block=cls.__name__, method=method):
                    dut = cls(data_width=16, angle_width=AW, method=method, with_csr=False)
                    gi, gq = run_park(dut, (alpha, beta), angles, n)
                    ri, rq = model(alpha, beta, angles, method=method)
                    self.assertTrue(np.array_equal(gi, ri))
                    self.assertTrue(np.array_equal(gq, rq))
                    self.assertEqual(dut.latency, 2)

    # verify-tier: bound — Park then inverse Park with the same angle is the identity up to
    # two roundings and the ROM full-scale gain (32767/32768)**2 = 1 - 6.1e-5, i.e. <= 1.2 LSB
    # at |v| = 20000 plus 1 LSB of rounding: gate 3 LSB.
    def test_rotation_round_trip(self):
        n, amp = 2000, 20000
        theta  = 2*np.pi*np.arange(n)*3/n
        alpha  = np.round(amp*np.cos(theta)).astype(np.int64)
        beta   = np.round(amp*np.sin(theta)).astype(np.int64)
        angles = np.array([random.Random(6).randint(-(1 << (AW - 1)), (1 << (AW - 1)) - 1)
                           for _ in range(n)])
        d, q       = park_model(alpha, beta, angles)
        park       = LiteDSPPark(data_width=16, with_csr=False)
        gd, gq     = run_park(park, (alpha, beta), angles, n, throttle=(0.0, 0.0), ready_rate=1.0)
        self.assertTrue(np.array_equal(gd, d) and np.array_equal(gq, q))
        inv        = LiteDSPInversePark(data_width=16, with_csr=False)
        ga, gb     = run_park(inv, (d, q), angles, n, throttle=(0.0, 0.0), ready_rate=1.0)
        self.assertLessEqual(np.max(np.abs(ga - alpha)), 3)
        self.assertLessEqual(np.max(np.abs(gb - beta)), 3)

    # verify-tier: bound — a balanced three-phase current set at the rotor angle is a DC
    # vector in the rotor frame: d = A, q = 0. With LUT-exact angles the residual is the
    # Clarke (<= 1 LSB per axis) and mixer (<= 0.5 LSB) roundings: gate 3 LSB.
    def test_dc_current_is_constant_in_dq(self):
        n, amp = 1024, 16000
        angles = ((np.arange(n)*11*(1 << (AW - 10))) & ((1 << AW) - 1))      # LUT-exact ramp.
        angles = np.where(angles >= (1 << (AW - 1)), angles - (1 << AW), angles)
        theta  = 2*np.pi*angles/(1 << AW)
        a, b, c = balanced_abc(theta, amp)

        class Chain(LiteXModule):
            def __init__(self):
                self.clarke = LiteDSPClarke(data_width=16, with_csr=False)
                self.park   = LiteDSPPark(data_width=16, angle_width=AW, with_csr=False)
                self.sink, self.sink_angle, self.source = \
                    self.clarke.sink, self.park.sink_angle, self.park.source
                self.comb += self.clarke.source.connect(self.park.sink)

        dut = Chain()
        captured = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"a": int(a[k]), "b": int(b[k]), "c": int(c[k])}
                for k in range(n)], ["a", "b", "c"], seed=21, throttle=0.1),
            stream_driver(dut.sink_angle, [{"angle": int(x)} for x in angles], ["angle"],
                seed=22, throttle=0.1),
            stream_capture(dut.source, captured, n, ["i", "q"], seed=23, ready_rate=0.8),
        ])
        d, q = column(captured, "i", 16), column(captured, "q", 16)
        self.assertLessEqual(np.max(np.abs(d - amp)), 3)
        self.assertLessEqual(np.max(np.abs(q)), 3)

if __name__ == "__main__":
    unittest.main()
