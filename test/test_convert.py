#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.stream.convert import LiteDSPOffsetBinaryToTwos

from test.common import run_stream, column

class TestConvert(unittest.TestCase):
    def test_offset_binary_roundtrip(self):
        prng = random.Random(1)
        xi = [prng.randint(-30000, 30000) for _ in range(64)]
        xq = [prng.randint(-30000, 30000) for _ in range(64)]
        dut = LiteDSPOffsetBinaryToTwos(data_width=16)
        # Feed offset-binary (signed+32768) -> expect signed back.
        ob = [{"i": (xi[k] + 32768), "q": (xq[k] + 32768)} for k in range(len(xi))]
        cap = run_stream(dut, ob, len(xi), ["i", "q"], ["i", "q"],
            sink_throttle=0.1, source_ready_rate=0.8)
        self.assertTrue(np.array_equal(column(cap, "i", 16), xi))
        self.assertTrue(np.array_equal(column(cap, "q", 16), xq))

if __name__ == "__main__":
    unittest.main()
