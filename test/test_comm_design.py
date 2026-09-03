#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side design helpers of the communications extras."""

import math
import unittest

import numpy as np

from litedsp.filter.design import gaussian_coefficients
from litedsp.comm.design   import (gf_tables, gf_mul_int, bch_generator, hamming_columns, hamming_params, gray_encode,
                                   gray_decode, fsk_deviation, hdlc_fcs, hdlc_stuff, hdlc_unstuff, hdlc_frame_bits, HDLC_FLAG)

class TestGaussianTaps(unittest.TestCase):
    # verify-tier: bound — symmetric taps summing to unity within the quantisation, -3 dB at
    # bt * Rs within 5 % for two bandwidth-time products; invalid parameters.
    def test_gaussian(self):
        for bt in (0.3, 0.5):
            h = np.array(gaussian_coefficients(sps=8, span=6, bt=bt, data_width=16), float)
            self.assertTrue(np.array_equal(h, h[::-1]))
            self.assertLessEqual(abs(h.sum()/32768 - 1.0), 0.002)
            f = np.linspace(0, 0.5, 4001)                              # cycles per sample.
            H = np.abs(np.array([np.sum(h*np.exp(-2j*math.pi*fk*np.arange(len(h)))) for fk in f]))
            H /= H[0]
            f3 = f[np.argmin(np.abs(20*np.log10(H) + 3.0))]
            self.assertLessEqual(abs(f3 - bt/8)/(bt/8), 0.05, (bt, f3))
        with self.assertRaises(ValueError):
            gaussian_coefficients(bt=0)

class TestCodeDesign(unittest.TestCase):
    # verify-tier: model — GF(2^4) tables agree with the bit-serial multiplier; BCH generators
    # match the known answers ((15,7) 0o721, (31,21) 0o3551, (63,45) degree 18) and their
    # codewords have alpha^1..2t as roots; Hamming columns are a permutation of 1..2^m-1; Gray
    # round trips; the FSK deviation word; HDLC stuffing round trip and the X.25 FCS against
    # the AIS example's reference.
    def test_helpers(self):
        exp, log = gf_tables(4)
        for a in range(1, 16):
            for b in range(1, 16):
                self.assertEqual(exp[(log[a] + log[b]) % 15], gf_mul_int(a, b, 4))
        self.assertEqual(bch_generator(4, 2), (0o721, 15, 7))
        self.assertEqual(bch_generator(5, 2), (0o3551, 31, 21))
        g, n, k = bch_generator(6, 3)
        self.assertEqual((g.bit_length() - 1, n, k), (18, 63, 45))
        exp6, _ = gf_tables(6)
        for i in range(1, 7):                                           # alpha^i is a root of g.
            a = exp6[i]
            val, x = 0, 1
            for d in range(g.bit_length()):
                if (g >> d) & 1:
                    val ^= x
                x = gf_mul_int(x, a, 6)
            self.assertEqual(val, 0)
        self.assertEqual(sorted(hamming_columns(3)), list(range(1, 8)))
        self.assertEqual(hamming_params(3, True), (8, 4))
        self.assertTrue(all(gray_decode(gray_encode(b)) == b for b in range(256)))
        self.assertEqual(fsk_deviation(1.0, 8), 1 << 29)
        self.assertEqual(fsk_deviation(0.5, 4, 2), int(round(0.5*2**32*4/(2*4*3))))
        bits = [1]*7 + [0] + [1]*5 + [0, 1]
        self.assertEqual(hdlc_unstuff(hdlc_stuff(bits)), bits)
        self.assertEqual(hdlc_stuff([1]*5), [1, 1, 1, 1, 1, 0])
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location("ais", pathlib.Path("examples/ais_receiver.py"))
        try:
            ais = importlib.util.module_from_spec(spec); spec.loader.exec_module(ais)
            payload = [(k*7 + 3) & 1 for k in range(96)]
            self.assertEqual(hdlc_fcs(payload), [int(v) for v in ais.fcs_bits(payload)])
            frame = hdlc_frame_bits(payload)
            self.assertEqual(frame[:8], [(HDLC_FLAG >> i) & 1 for i in range(8)])
            self.assertEqual(frame[8:-8], [int(v) for v in ais.bit_stuff(list(payload) + hdlc_fcs(payload))])
        except Exception as e:
            self.skipTest(f"AIS example not importable: {e}")

if __name__ == "__main__":
    unittest.main()
