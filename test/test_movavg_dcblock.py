#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.filter.dc_blocker     import LiteDSPDCBlocker
from litedsp.filter.moving_average import LiteDSPMovingAverage

from test.common import run_stream, column
from test.models import dc_blocker_model, moving_average_model

class TestMovingAverage(unittest.TestCase):
    def test_bit_exact(self):
        for length_log2 in [1, 3, 5]:
            dut = LiteDSPMovingAverage(data_width=16, length_log2=length_log2, with_csr=False)
            prng = random.Random(length_log2)
            xi = [prng.randint(-30000, 30000) for _ in range(300)]
            xq = [prng.randint(-30000, 30000) for _ in range(300)]
            samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
            cap = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.7)
            self.assertTrue(np.array_equal(column(cap, "i", 16), moving_average_model(xi, length_log2)))
            self.assertTrue(np.array_equal(column(cap, "q", 16), moving_average_model(xq, length_log2)))

    def test_dc_passes(self):
        # Constant input -> output settles to that constant.
        dut = LiteDSPMovingAverage(data_width=16, length_log2=4, with_csr=False)
        n = 64
        cap = run_stream(dut, [{"i": 5000, "q": -3000} for _ in range(n)], n, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        self.assertEqual(column(cap, "i", 16)[-1], 5000)
        self.assertEqual(column(cap, "q", 16)[-1], -3000)

class TestDCBlocker(unittest.TestCase):
    def test_bit_exact(self):
        for pole_shift in [3, 5, 8]:
            dut = LiteDSPDCBlocker(data_width=16, pole_shift=pole_shift, with_csr=False)
            prng = random.Random(pole_shift)
            xi = [prng.randint(-20000, 20000) for _ in range(300)]
            xq = [prng.randint(-20000, 20000) for _ in range(300)]
            samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
            cap = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.7)
            self.assertTrue(np.array_equal(column(cap, "i", 16), dc_blocker_model(xi, pole_shift)))
            self.assertTrue(np.array_equal(column(cap, "q", 16), dc_blocker_model(xq, pole_shift)))

    def test_removes_dc(self):
        # Tone on a large DC offset: output DC should be strongly attenuated.
        n = 4000
        t = np.arange(n)
        x = (8000 + 4000*np.cos(2*np.pi*0.05*t)).astype(int)
        dut = LiteDSPDCBlocker(data_width=16, pole_shift=6, with_csr=False)
        cap = run_stream(dut, [{"i": int(x[k]), "q": 0} for k in range(n)], n, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        out = column(cap, "i", 16)[n//2:]   # Skip settling.
        self.assertLess(abs(out.mean()), 50)          # DC removed.
        self.assertGreater(out.std(), 2000)           # AC preserved.

    def test_bit_exact_precision(self):
        # verify-tier: model — high-precision mode (wide state + error-feedback requantization)
        # bit-exact vs dc_blocker_model under randomized stalls/backpressure.
        for precision_bits in [4, 8]:
            dut = LiteDSPDCBlocker(data_width=16, pole_shift=5, precision_bits=precision_bits,
                with_csr=False)
            prng = random.Random(precision_bits)
            xi = [prng.randint(-30000, 30000) for _ in range(300)]
            xq = [prng.randint(-30000, 30000) for _ in range(300)]
            samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
            cap = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.7)
            self.assertTrue(np.array_equal(column(cap, "i", 16),
                dc_blocker_model(xi, 5, precision_bits=precision_bits)), f"p={precision_bits}")
            self.assertTrue(np.array_equal(column(cap, "q", 16),
                dc_blocker_model(xq, 5, precision_bits=precision_bits)), f"p={precision_bits}")

    def test_dc_rejection_high_precision(self):
        # verify-tier: model + bound — full-scale DC step + small tone at p=8: steady-state DC
        # residual below -110 dBFS. The documented worst-case bound is
        # -6.02*(data_width - 1 + p - pole_shift) = -108.4 dBFS for pole_shift=5; the measured
        # (deterministic) residual sits far below it because the away-from-zero leak leaves no
        # deadband and the error-feedback requantizer is DC-free (p=0 floors at ~-66 dBFS here).
        n  = 8192
        t  = np.arange(n)
        x  = 31000 + np.round(1000*np.cos(2*np.pi*t/64)).astype(np.int64)  # 64 = window divisor.
        dut = LiteDSPDCBlocker(data_width=16, pole_shift=5, precision_bits=8, with_csr=False)
        cap = run_stream(dut, [{"i": int(v), "q": 0} for v in x], n, ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        out = column(cap, "i", 16)
        self.assertTrue(np.array_equal(out, dc_blocker_model(x, 5, precision_bits=8)))
        tail = out[n//2:]                             # Settled; whole tone periods (4096 = 64*64).
        residual = abs(tail.mean())                   # LSBs of DC left after the notch.
        residual_dbfs = 20*np.log10(max(residual, 1e-9)/32768)
        self.assertLess(residual_dbfs, -110.0,
            f"steady-state DC residual {residual_dbfs:.1f} dBFS >= -110 dBFS")
        self.assertGreater(tail.std(), 500)           # The tone itself passed through.

    def test_no_limit_cycles_on_silence(self):
        # verify-tier: model — after signal then silence, the output must decay to exactly 0
        # and stay there (the away-from-zero leak has no deadband; the error-feedback state
        # alone must not regenerate output LSBs).
        prng = random.Random(42)
        sig  = [prng.randint(-30000, 30000) for _ in range(400)]
        x    = sig + [0]*2600
        dut  = LiteDSPDCBlocker(data_width=16, pole_shift=5, precision_bits=8, with_csr=False)
        cap  = run_stream(dut, [{"i": v, "q": -v} for v in x], len(x), ["i", "q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        for f in ["i", "q"]:
            tail = column(cap, f, 16)[-1000:]
            self.assertTrue(np.all(tail == 0), f"{f}: limit cycle on silence (max |y| = "
                f"{np.abs(tail).max()} after settling)")

if __name__ == "__main__":
    unittest.main()
