#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

from litedsp.comm.diff import LiteDSPDifferentialEncoder, LiteDSPDifferentialDecoder

from test.common import run_stream, column

class TestDifferential(unittest.TestCase):
    def test_roundtrip(self):
        M = 4
        enc = LiteDSPDifferentialEncoder(modulus=M, with_csr=False)
        prng = random.Random(5)
        syms = [prng.randint(0, M - 1) for _ in range(80)]
        cap_e = run_stream(enc, [{"data": s} for s in syms], len(syms), ["data"], ["data"],
            sink_throttle=0.1, source_ready_rate=0.8)
        enc_out = list(column(cap_e, "data"))
        dec = LiteDSPDifferentialDecoder(modulus=M, with_csr=False)
        cap_d = run_stream(dec, [{"data": int(s)} for s in enc_out], len(enc_out), ["data"], ["data"],
            sink_throttle=0.1, source_ready_rate=0.8)
        dec_out = list(column(cap_d, "data"))
        # First decoded symbol depends on initial state; rest must match.
        self.assertEqual(dec_out[1:], syms[1:len(dec_out)])

if __name__ == "__main__":
    unittest.main()
