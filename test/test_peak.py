#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.level.peak import LiteDSPEnvelopeDetector

from test.common import run_stream, column

def tone(n, f, amp):
    return amp*np.exp(1j*2*np.pi*f*np.arange(n))

class TestEnvelope(unittest.TestCase):
    def test_tracks_amplitude(self):
        n = 2000
        amp = 9000
        dut = LiteDSPEnvelopeDetector(data_width=16, attack=3, release=3, with_csr=False)
        x   = tone(n, 0.01, amp)
        cap = run_stream(dut, [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x],
            n, ["i", "q"], ["data"], sink_throttle=0.0, source_ready_rate=1.0)
        env = column(cap, "data")[n//2:]
        self.assertAlmostEqual(env.mean(), amp, delta=amp*0.15)

if __name__ == "__main__":
    unittest.main()
