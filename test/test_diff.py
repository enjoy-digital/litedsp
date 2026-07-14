#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Differential encoder/decoder tests, bit-exact against ``diff_encode_model`` /
``diff_decode_model`` (mod-M recurrences), plus a known vector and an exact round-trip.

verify-tier: model
"""

import random
import unittest

import numpy as np

from litedsp.comm.diff import LiteDSPDifferentialEncoder, LiteDSPDifferentialDecoder

from test.common import run_stream, column
from test.models import diff_encode_model, diff_decode_model

class TestDifferential(unittest.TestCase):
    def run_block(self, dut, syms):
        cap = run_stream(dut, [{"data": int(s)} for s in syms], len(syms), ["data"], ["data"])
        return column(cap, "data")  # Default randomized backpressure.

    def test_encoder_bit_exact(self):
        for M in [2, 3, 4, 8]:  # Includes a non-power-of-two modulus.
            prng = random.Random(M)
            syms = [prng.randint(0, M - 1) for _ in range(120)]
            enc  = self.run_block(LiteDSPDifferentialEncoder(modulus=M, with_csr=False), syms)
            self.assertTrue(np.array_equal(enc, diff_encode_model(syms, M)), f"encode M={M}")

    def test_decoder_bit_exact(self):
        for M in [2, 3, 4, 8]:
            prng = random.Random(M + 100)
            syms = [prng.randint(0, M - 1) for _ in range(120)]
            dec  = self.run_block(LiteDSPDifferentialDecoder(modulus=M, with_csr=False), syms)
            self.assertTrue(np.array_equal(dec, diff_decode_model(syms, M)), f"decode M={M}")

    def test_known_vector(self):
        # DQPSK hand-computed vector (encoder acc and decoder prev both reset to 0).
        syms = [1, 2, 3, 0, 1, 3, 2]
        enc  = self.run_block(LiteDSPDifferentialEncoder(modulus=4, with_csr=False), syms)
        self.assertTrue(np.array_equal(enc, [1, 3, 2, 2, 3, 2, 0]))
        dec  = self.run_block(LiteDSPDifferentialDecoder(modulus=4, with_csr=False), list(enc))
        self.assertTrue(np.array_equal(dec, syms))

    def test_roundtrip(self):
        # Functional intent: decoder inverts encoder exactly (both reset, so from symbol 0).
        M    = 4
        prng = random.Random(5)
        syms = [prng.randint(0, M - 1) for _ in range(80)]
        enc  = self.run_block(LiteDSPDifferentialEncoder(modulus=M, with_csr=False), syms)
        dec  = self.run_block(LiteDSPDifferentialDecoder(modulus=M, with_csr=False), list(enc))
        self.assertTrue(np.array_equal(dec, syms))

if __name__ == "__main__":
    unittest.main()
