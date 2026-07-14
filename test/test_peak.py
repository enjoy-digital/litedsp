#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPEnvelopeDetector tests, bit-exact against ``envelope_detector_model``.

verify-tier: model

The model is a per-sample recurrence and matches the HW bit-for-bit for gap-free input
(``sink_throttle=0``): the HW envelope register also steps on input-idle cycles (re-evaluating
the stale magnitude while the pipeline advances), i.e. it converges in cycle time rather than
sample time. Output-side backpressure freezes the whole pipeline, so randomized backpressure
is applied on the source side only.
"""

import random
import unittest

import numpy as np

from litedsp.level.peak import LiteDSPEnvelopeDetector

from test.common import run_stream, column
from test.models import envelope_detector_model

def tone(n, f, amp):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestEnvelope(unittest.TestCase):
    def run_env(self, xi, xq, attack, release):
        dut = LiteDSPEnvelopeDetector(data_width=16, attack=attack, release=release, with_csr=False)
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi), ["i", "q"], ["data"], sink_throttle=0.0)  # Gap-free input (see docstring).
        return column(cap, "data")  # Envelope is unsigned (W = data_width + 1 bits).

    def test_bit_exact(self):
        n = 400
        for attack, release in [(2, 6), (3, 3), (0, 8)]:
            prng = random.Random(attack*16 + release)
            # Amplitude bursts (attack and release both exercised) + full-scale corners.
            amps = [0, 20000, 500, 32000, 0, 9000]
            x    = np.concatenate([tone(n//len(amps), 0.013, a) for a in amps])
            xi   = np.round(x.real).astype(int).tolist() + [-32768, 32767, -32768, 0]
            xq   = np.round(x.imag).astype(int).tolist() + [-32768, -32768, 32767, 0]
            xi  += [prng.randint(-32768, 32767) for _ in range(64)]
            xq  += [prng.randint(-32768, 32767) for _ in range(64)]
            env = self.run_env(xi, xq, attack, release)
            ref = envelope_detector_model(xi, xq, attack=attack, release=release)
            self.assertTrue(np.array_equal(env, ref),
                f"envelope mismatch attack={attack} release={release}")

    def test_tracks_amplitude(self):
        # Functional intent: the envelope settles near the tone amplitude (alpha-max-beta-min
        # magnitude ripples within about -12%..+3% of |x|).
        n   = 2000
        amp = 9000
        x   = tone(n, 0.01, amp)
        env = self.run_env(np.round(x.real).astype(int).tolist(),
                           np.round(x.imag).astype(int).tolist(), attack=3, release=3)
        self.assertAlmostEqual(env[n//2:].mean(), amp, delta=amp*0.15)

if __name__ == "__main__":
    unittest.main()
