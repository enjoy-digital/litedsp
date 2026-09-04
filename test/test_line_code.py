#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import importlib.util
import random
import pathlib
import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.comm.line_code import LiteDSPLineEncoder, LiteDSPLineDecoder, CODES

from test.common import run_stream, column
from test.models import line_encode_model, line_decode_model

class TestLineCodes(unittest.TestCase):
    # verify-tier: model — 200 random bits through every encoder and its decoder (round trip)
    # under backpressure, bit-exact against the models; NRZI-S equals the AIS example's encoder;
    # Manchester chips always transition mid-bit and are DC balanced; latency 1.
    def test_codes(self):
        prng = random.Random(6)
        bits = [prng.randint(0, 1) for _ in range(200)]
        for code in CODES:
            with self.subTest(code=code):
                enc = LiteDSPLineEncoder(code=code, with_csr=False)
                n_chips = 200*(2 if "manchester" in code else 1)
                cap = run_stream(enc, [{"data": b} for b in bits], n_chips, ["data"], ["data"], sink_throttle=0.2, source_ready_rate=0.7)
                chips = column(cap, "data").tolist()
                self.assertEqual(chips, line_encode_model(bits, code).tolist())
                dec = LiteDSPLineDecoder(code=code, with_csr=False)
                cap = run_stream(dec, [{"data": c} for c in chips], 200, ["data"], ["data"], sink_throttle=0.2, source_ready_rate=0.7,
                    extra=[self._status(dec)])
                self.assertEqual(column(cap, "data").tolist(), bits)
                self.assertEqual(column(cap, "data").tolist(), line_decode_model(chips, code)[0].tolist())
                self.assertEqual(self.viol, 0)
                self.assertEqual((enc.latency, dec.latency), (1, 1))
                if "manchester" in code:
                    pairs = np.array(chips).reshape(-1, 2)
                    self.assertTrue(np.all(pairs[:, 0] != pairs[:, 1]))
                    self.assertEqual(int(np.sum(chips)), len(chips)//2)
        spec = importlib.util.spec_from_file_location("ais", pathlib.Path("examples/ais_receiver.py"))
        ais = importlib.util.module_from_spec(spec); spec.loader.exec_module(ais)
        levels = ais.nrzi_encode(bits, initial=1)
        self.assertEqual(line_encode_model(bits, "nrzi_s").tolist(), [int(l < 0) for l in levels])

    # verify-tier: bound — Manchester chip pairs without a transition are counted as violations
    # (sticky flag, cleared), the decoded bit takes the first chip; inversion; invalid code.
    def test_violations_and_invert(self):
        chips = [1, 0, 1, 1, 0, 1, 0, 0, 0, 1]
        dec = LiteDSPLineDecoder(code="manchester", with_csr=False)
        cap = run_stream(dec, [{"data": c} for c in chips], 5, ["data"], ["data"], sink_throttle=0.0, source_ready_rate=1.0, extra=[self._status(dec)])
        self.assertEqual(column(cap, "data").tolist(), [1, 1, 0, 0, 0])
        self.assertEqual((self.viol, self.flag), (2, 1))
        enc = LiteDSPLineEncoder(code="nrzi_m", invert=True, with_csr=False)
        cap = run_stream(enc, [{"data": b} for b in [1, 0, 1, 1]], 4, ["data"], ["data"])
        self.assertEqual(column(cap, "data").tolist(), line_encode_model([1, 0, 1, 1], "nrzi_m", 1).tolist())
        with self.assertRaises(ValueError):
            LiteDSPLineEncoder(code="rz", with_csr=False)

    def _status(self, dut):
        @passive
        def gen():
            while True:
                self.viol = (yield dut.violations)
                self.flag = (yield dut.violation)
                yield
        return gen()

if __name__ == "__main__":
    unittest.main()
