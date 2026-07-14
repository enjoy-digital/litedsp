#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.generation.cordic import LiteDSPCORDIC

from test.common import run_stream, column, assert_snr

class TestCORDIC(unittest.TestCase):
    # Fixed-point bound: stages = data_width = 16 iterations give ~1 bit of convergence each,
    # but the result is rounded to 16 bits after the Q1.15 1/K gain compensation (and the
    # angle LUT is quantized to angle_width), leaving ~12 effective bits, i.e. ~74 dB. Gates
    # are set 3 dB under the values measured at LITEDSP_SEED=0 (the pipeline is pure
    # feedforward, so the outputs are stall-invariant and stable across seed rotation):
    # rotation 73.9, sincos 77.8/78.7, vectoring mag 74.4, vectoring angle 76.4 dB.

    # verify-tier: bound.
    def test_rotation(self):
        dw, aw = 16, 16
        dut = LiteDSPCORDIC(data_width=dw, angle_width=aw, mode="rotation", with_csr=False)
        prng = random.Random(1)
        n  = 300
        xs = [prng.randint(-12000, 12000) for _ in range(n)]
        ys = [prng.randint(-12000, 12000) for _ in range(n)]
        zs = [prng.randint(-(1 << (aw-1)), (1 << (aw-1)) - 1) for _ in range(n)]
        samples = [{"x": xs[k], "y": ys[k], "z": zs[k]} for k in range(n)]
        cap = run_stream(dut, samples, n, ["x", "y", "z"], ["x", "y"],
            sink_throttle=0.2, source_ready_rate=0.7)
        gx = column(cap, "x", dw).astype(float)
        gy = column(cap, "y", dw).astype(float)
        ang = np.array(zs)/(1 << aw)*2*np.pi
        tx  = np.array(xs)*np.cos(ang) - np.array(ys)*np.sin(ang)
        ty  = np.array(xs)*np.sin(ang) + np.array(ys)*np.cos(ang)
        assert_snr(self, tx + 1j*ty, gx + 1j*gy, 70.5, "rotation")

    # verify-tier: bound.
    def test_sincos(self):
        dw, aw = 16, 16
        dut = LiteDSPCORDIC(data_width=dw, angle_width=aw, mode="rotation", with_csr=False)
        amp = 30000
        zs  = list(np.linspace(-(1 << (aw-1)), (1 << (aw-1)) - 1, 256).astype(int))
        samples = [{"x": amp, "y": 0, "z": int(z)} for z in zs]
        cap = run_stream(dut, samples, len(zs), ["x", "y", "z"], ["x", "y"],
            sink_throttle=0.0, source_ready_rate=1.0)
        gx = column(cap, "x", dw).astype(float)
        gy = column(cap, "y", dw).astype(float)
        ang = np.array(zs)/(1 << aw)*2*np.pi
        assert_snr(self, amp*np.cos(ang), gx, 74.5, "cos")
        assert_snr(self, amp*np.sin(ang), gy, 75.5, "sin")

    # verify-tier: bound.
    def test_vectoring(self):
        dw, aw = 16, 16
        dut = LiteDSPCORDIC(data_width=dw, angle_width=aw, mode="vectoring", with_csr=False)
        prng = random.Random(2)
        n  = 300
        xs = [prng.randint(-15000, 15000) for _ in range(n)]
        ys = [prng.randint(-15000, 15000) for _ in range(n)]
        samples = [{"x": xs[k], "y": ys[k]} for k in range(n)]
        cap = run_stream(dut, samples, n, ["x", "y"], ["mag", "angle"],
            sink_throttle=0.2, source_ready_rate=0.7)
        gmag = column(cap, "mag", dw + 1).astype(float)
        gang = column(cap, "angle", aw).astype(float)/(1 << aw)*2*np.pi
        true_mag = np.hypot(xs, ys)
        true_ang = np.arctan2(ys, xs)
        # Magnitude: high SNR. Angle: compare on the unit circle (wrap-aware), big vectors only.
        assert_snr(self, true_mag, gmag, 71.0, "magnitude")
        big = true_mag > 1500
        assert_snr(self, np.exp(1j*true_ang[big]), np.exp(1j*gang[big]), 73.0, "angle")

if __name__ == "__main__":
    unittest.main()
