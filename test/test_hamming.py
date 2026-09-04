#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest
import itertools

import numpy as np

from migen import *

from litex.gen import *

from litedsp.comm.hamming import LiteDSPHammingEncoder, LiteDSPHammingDecoder

from test.common import run_stream, column
from test.models import hamming_encode_model, hamming_decode_model

class TestHamming(unittest.TestCase):
    # verify-tier: model — exhaustive (7,4) / (8,4) codebooks have minimum distance 3 / 4, every
    # single error is corrected and, with SECDED, every double error is detected without
    # miscorrection (model); the RTL encoder and decoder are bit-exact against the models on 20
    # random blocks with injected errors under backpressure, framing and status counters checked.
    def test_codes(self):
        for m, secded in ((3, False), (3, True)):
            with self.subTest(m=m, secded=secded):
                n, k = (7 + int(secded)), 4
                book = {}
                for msg in itertools.product((0, 1), repeat=k):
                    cw, _, _ = hamming_encode_model(list(msg), m, secded)
                    book[msg] = cw.tolist()
                cws = list(book.values())
                dmin = min(sum(a != b for a, b in zip(u, v)) for u in cws for v in cws if u != v)
                self.assertEqual(dmin, 4 if secded else 3)
                for msg, cw in book.items():
                    for i in range(n):
                        err = list(cw); err[i] ^= 1
                        dec, flags = hamming_decode_model(err, m, secded)
                        self.assertEqual(dec.tolist(), list(msg))
                        # An error in the overall parity bit leaves the data intact (nothing to
                        # correct).
                        self.assertEqual(flags[0], (0, 0) if (secded and i == n - 1) else (1, 0))
                    if secded:
                        for i, j in itertools.combinations(range(n), 2):
                            err = list(cw); err[i] ^= 1; err[j] ^= 1
                            dec, flags = hamming_decode_model(err, m, secded)
                            self.assertEqual(flags[0], (0, 1))
                            self.assertEqual(dec.tolist(), err[:k])
        prng = random.Random(8)
        for m, secded in ((3, False), (3, True), (4, False)):
            with self.subTest(rtl_m=m, secded=secded):
                n, k = (1 << m) - 1 + int(secded), (1 << m) - 1 - m
                bits = [prng.randint(0, 1) for _ in range(20*k)]
                enc = LiteDSPHammingEncoder(m=m, secded=secded, with_csr=False)
                cap = run_stream(enc, [{"data": b} for b in bits], 20*n, ["data"], ["data", "first",
                    "last"], sink_throttle=0.2, source_ready_rate=0.7)
                cw, first, last = hamming_encode_model(bits, m, secded)
                self.assertEqual(column(cap, "data").tolist(), cw.tolist())
                self.assertEqual(column(cap, "first").tolist(), first.tolist())
                self.assertEqual(column(cap, "last").tolist(), last.tolist())
                rx = cw.tolist()
                for b in range(20):                                     # Block b: b % 3 errors.
                    for i in range(b % 3):
                        rx[b*n + (i*3 + b) % n] ^= 1
                dec = LiteDSPHammingDecoder(m=m, secded=secded, with_csr=False)
                cap = run_stream(dec, [{"data": b} for b in rx], 20*k, ["data"], ["data", "first",
                    "last"], sink_throttle=0.2, source_ready_rate=0.7,
                    extra=[self._status(dec)])
                ref, flags = hamming_decode_model(rx, m, secded)
                self.assertEqual(column(cap, "data").tolist(), ref.tolist())
                self.assertEqual(column(cap, "first").tolist(),
                                 [int(i % k == 0) for i in range(20*k)])
                self.assertEqual(self.corrected_total, sum(f[0] for f in flags))
                self.assertEqual(self.uncorrectable_count, sum(f[1] for f in flags))
                self.assertEqual(self.uncorrectable, int(any(f[1] for f in flags)))
                self.assertEqual((enc.cycles_per_block, dec.cycles_per_block), (n + 1, n + 1 + k))
        with self.assertRaises(ValueError):
            LiteDSPHammingEncoder(m=2, with_csr=False)

    def _status(self, dut):
        def gen():
            for _ in range(3000):
                self.corrected_total = (yield dut.corrected_total)
                self.uncorrectable_count = (yield dut.uncorrectable_count)
                self.uncorrectable = (yield dut.uncorrectable)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
