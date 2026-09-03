#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import itertools
import random
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.comm.bch    import LiteDSPBCHEncoder, LiteDSPBCHDecoder
from litedsp.comm.design import bch_generator, gf_tables, gf_mul_int

from test.common import run_stream, column
from test.models import bch_encode_model, bch_decode_model

class TestBCHModels(unittest.TestCase):
    # verify-tier: model — codewords of (15,7), (31,21) and (63,45) have alpha^1..2t as roots;
    # every pattern of <= t errors on (15,7) is corrected (exhaustive); random <= t errors on
    # (31,21) / (63,45) are corrected; t + 1 errors are flagged or mis-corrected to another
    # codeword only (never a silent wrong message with a "corrected" flag on a valid word).
    def test_models(self):
        prng = random.Random(2)
        for m, t in ((4, 2), (5, 2), (6, 3)):
            with self.subTest(m=m, t=t):
                g, n, k = bch_generator(m, t)
                exp, _ = gf_tables(m)
                msgs = [prng.randint(0, 1) for _ in range(4*k)]
                cw, _, _ = bch_encode_model(msgs, m, t)
                for b in range(4):
                    w = cw[b*n:(b + 1)*n].tolist()
                    for i in range(1, 2*t + 1):
                        acc = 0
                        for bit in w:
                            acc = gf_mul_int(acc, exp[i], m) ^ bit
                        self.assertEqual(acc, 0)
                    for _ in range(12):
                        e = prng.randint(0, t)
                        r = list(w)
                        for p in prng.sample(range(n), e):
                            r[p] ^= 1
                        dec, fl = bch_decode_model(r, m, t)
                        self.assertEqual(dec.tolist(), w[:k]); self.assertEqual(fl[0], (1, 0) if e else (0, 0))
                    r = list(w)
                    for p in prng.sample(range(n), t + 1):
                        r[p] ^= 1
                    dec, fl = bch_decode_model(r, m, t)
                    if fl[0] == (1, 0):                                 # Mis-correction lands on a codeword.
                        recw, _, _ = bch_encode_model(dec.tolist(), m, t)
                        self.assertNotEqual(recw.tolist(), w)
        g, n, k = bch_generator(4, 2)
        w = bch_encode_model([1, 0, 1, 1, 0, 0, 1], 4, 2)[0].tolist()
        for e in range(3):
            for pos in itertools.combinations(range(n), e):
                r = list(w)
                for p in pos:
                    r[p] ^= 1
                dec, fl = bch_decode_model(r, 4, 2)
                self.assertEqual(dec.tolist(), w[:k])

class TestBCHRTL(unittest.TestCase):
    # verify-tier: model — the (15,7) encoder streams 30 codewords bit-exact with the framing; the
    # decoder is bit-exact against the model on blocks carrying 0..3 errors (correction, the
    # clean fast path and the flagged uncorrectable case) under backpressure with the counters;
    # the (31,21) pair round-trips with t errors per block.
    def test_rtl(self):
        prng = random.Random(3)
        for m, t, blocks in ((4, 2, 30), (5, 2, 8)):
            with self.subTest(m=m, t=t):
                g, n, k = bch_generator(m, t)
                bits = [prng.randint(0, 1) for _ in range(blocks*k)]
                enc = LiteDSPBCHEncoder(m=m, t=t, with_csr=False)
                cap = run_stream(enc, [{"data": b} for b in bits], blocks*n, ["data"], ["data", "first", "last"], sink_throttle=0.2, source_ready_rate=0.7)
                cw, first, last = bch_encode_model(bits, m, t)
                self.assertEqual(column(cap, "data").tolist(), cw.tolist())
                self.assertEqual(column(cap, "first").tolist(), first.tolist())
                self.assertEqual(column(cap, "last").tolist(), last.tolist())
                rx = cw.tolist()
                for b in range(blocks):
                    e = b % (t + 2)                                     # 0 .. t + 1 errors.
                    for p in prng.sample(range(n), e):
                        rx[b*n + p] ^= 1
                dec = LiteDSPBCHDecoder(m=m, t=t, with_csr=False)
                cap = run_stream(dec, [{"data": b} for b in rx], blocks*k, ["data"], ["data", "first", "last"], sink_throttle=0.2, source_ready_rate=0.7,
                    extra=[self._status(dec, 40000)])
                ref, flags = bch_decode_model(rx, m, t)
                self.assertEqual(column(cap, "data").tolist(), ref.tolist())
                self.assertEqual(column(cap, "first").tolist(), [int(i % k == 0) for i in range(blocks*k)])
                self.assertEqual(self.corrected_total, sum(f[0] for f in flags))
                self.assertEqual(self.uncorrectable_count, sum(f[1] for f in flags))
                self.assertEqual(self.blocks, blocks)
        with self.assertRaises(ValueError):
            LiteDSPBCHEncoder(m=4, t=8, with_csr=False)

    def _status(self, dut, cycles):
        def gen():
            for _ in range(cycles):
                self.corrected_total = (yield dut.corrected_total)
                self.uncorrectable_count = (yield dut.uncorrectable_count)
                self.blocks = (yield dut.blocks)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
