#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.generation.cordic import CORDIC

from test.common import run_stream, column, snr_db

class TestCORDIC(unittest.TestCase):
    def test_rotation(self):
        dw, aw = 16, 16
        dut = CORDIC(data_width=dw, angle_width=aw, mode="rotation", with_csr=False)
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
        self.assertGreater(snr_db(tx + 1j*ty, gx + 1j*gy), 40.0)

    def test_sincos(self):
        dw, aw = 16, 16
        dut = CORDIC(data_width=dw, angle_width=aw, mode="rotation", with_csr=False)
        amp = 30000
        zs  = list(np.linspace(-(1 << (aw-1)), (1 << (aw-1)) - 1, 256).astype(int))
        samples = [{"x": amp, "y": 0, "z": int(z)} for z in zs]
        cap = run_stream(dut, samples, len(zs), ["x", "y", "z"], ["x", "y"],
            sink_throttle=0.0, source_ready_rate=1.0)
        gx = column(cap, "x", dw).astype(float)
        gy = column(cap, "y", dw).astype(float)
        ang = np.array(zs)/(1 << aw)*2*np.pi
        self.assertGreater(snr_db(amp*np.cos(ang), gx), 40.0)
        self.assertGreater(snr_db(amp*np.sin(ang), gy), 40.0)

    def test_vectoring(self):
        dw, aw = 16, 16
        dut = CORDIC(data_width=dw, angle_width=aw, mode="vectoring", with_csr=False)
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
        self.assertGreater(snr_db(true_mag, gmag), 40.0)
        big = true_mag > 1500
        self.assertGreater(snr_db(np.exp(1j*true_ang[big]), np.exp(1j*gang[big])), 40.0)

if __name__ == "__main__":
    unittest.main()
