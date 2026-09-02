#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import *

from litedsp.motor.resolver import LiteDSPResolverDigital

from test.common import stream_driver, stream_capture, column
from test.models import resolver_model, resolver_stimulus

AW   = 16
TURN = 1 << AW

def run_resolver(dut, sin_in, cos_in, n_out, throttle=0.2, exc_ready=0.7, ready_rate=0.7,
    extra=None):
    """Drive the windings, capture the excitation stream and the tracked angles."""
    exc, ang = [], []
    run_simulation(dut, [
        stream_driver(dut.sink, [{"i": int(s), "q": int(c)} for s, c in zip(sin_in, cos_in)],
            ["i", "q"], seed=1, throttle=throttle),
        stream_capture(dut.source_exc, exc, len(sin_in) - 8, ["data"], seed=2, ready_rate=exc_ready),
        stream_capture(dut.source, ang, n_out, ["angle"], seed=3, ready_rate=ready_rate),
    ] + (extra or []))
    return column(exc, "data", 16), column(ang, "angle", AW)

class TestResolverDigital(unittest.TestCase):
    # verify-tier: model — excitation ROM, delayed-reference demodulation, exact boxcar,
    # CORDIC at the accumulator width and the tracking loop, bit-exact under backpressure on
    # both sources (the DAC stream paces the input).
    def test_bit_exact(self):
        D, n = 16, 16*40
        prng = random.Random(4)
        s = [prng.randint(-30000, 30000) for _ in range(n)]
        c = [prng.randint(-30000, 30000) for _ in range(n)]
        dut = LiteDSPResolverDigital(data_width=16, angle_width=AW, decimation=D, with_csr=False)
        dut.phase_offset.reset = 3
        exc, ang = run_resolver(dut, s, c, n//D - 2)
        r_exc, _, r_ang = resolver_model(s, c, D, phase_offset=3)
        self.assertTrue(np.array_equal(exc, r_exc[:len(exc)]))
        self.assertTrue(np.array_equal(ang, r_ang[:len(ang)]))
        self.assertEqual(dut.latency, 20)

    # verify-tier: bound — rotating shaft (2.5 degrees per period) through a 3-sample analog
    # delay compensated by phase_offset = D - 3: the boxcar demodulation measures the angle
    # at the window center and the type-II tracker (kp 3 / ki 8: lock ~6*2**5 = 192 periods)
    # follows the ramp with no lag; over the last 100 periods the error vs the window-mean
    # angle stays within 0.5 degrees (CORDIC + ROM quantization).
    def test_tracks_rotating_shaft(self):
        D, delay, n_per = 32, 3, 400
        n     = D*n_per
        theta = np.arange(n)*(2*np.pi/144)/D                     # 2.5 degrees per period.
        s, c  = resolver_stimulus(theta, D, delay=delay)
        dut   = LiteDSPResolverDigital(data_width=16, angle_width=AW, decimation=D, with_csr=False)
        dut.phase_offset.reset = D - delay
        _, ang = run_resolver(dut, s, c, n_per - 2, throttle=0.0, exc_ready=1.0, ready_rate=1.0)
        truth = np.round(theta.reshape(n_per, D).mean(axis=1)/(2*np.pi)*TURN).astype(np.int64)[:len(ang)]
        err   = ((ang % TURN) - (truth % TURN) + TURN//2) % TURN - TURN//2
        self.assertLess(np.max(np.abs(err[-100:]))/TURN*360, 0.5)

    # verify-tier: bound — with the wrong demodulation offset the demodulated amplitude drops
    # by cos(2*pi*delay/D) (0.38 for 3 of 16 samples) while the demodulated angle stays
    # unbiased: checked on the raw_mag / raw_angle status at D = 16 (ratio < 0.5, angle
    # within 1 degree of the 0.7 rad shaft angle).
    def test_phase_offset_calibration(self):
        D, delay, n_per = 16, 3, 40
        n     = D*n_per
        theta = np.full(n, 0.7)
        s, c  = resolver_stimulus(theta, D, delay=delay)
        mags  = {}
        for offset in (D - delay, 0):
            dut = LiteDSPResolverDigital(data_width=16, angle_width=AW, decimation=D, with_csr=False)
            dut.phase_offset.reset = offset
            seen = []

            @passive
            def watch(dut=dut, seen=seen):
                while True:
                    seen.append(((yield dut.raw_mag), (yield dut.raw_angle)))
                    yield

            run_resolver(dut, s, c, n_per - 2, throttle=0.0, exc_ready=1.0, ready_rate=1.0,
                extra=[watch()])
            mags[offset] = seen[-1][0]
            raw = seen[-1][1]
            raw = raw - TURN if raw >= TURN//2 else raw
            err = (raw - round(0.7/(2*np.pi)*TURN) + TURN//2) % TURN - TURN//2
            self.assertLess(abs(err)/TURN*360, 1.0, f"offset {offset}: raw angle biased")
        self.assertLess(mags[0], 0.5*mags[D - delay])

    def test_invalid(self):
        for kwargs in ({"decimation": 2}, {"data_width": 2}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                LiteDSPResolverDigital(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
