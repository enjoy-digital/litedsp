#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Bypass contract: with ``bypass`` set, every bypass-capable block is an exact passthrough."""

import random
import unittest

import numpy as np

from litedsp.flow import registry
from litedsp.flow.metadata import _accepts_with_csr

from test.common import run_stream, column

# Blocks with a boolean ``bypass`` control (the mixer's 2-bit input-select bypass is tested
# in test_mixer.py; the capture scope's bypass in test_capture.py).
BYPASS_BLOCKS = [
    "gain", "fir_real", "fir_complex", "clipper", "saturate", "dc_offset", "iq_balance",
    "dc_blocker", "moving_average", "iir_biquad", "notch", "comb_filter", "allpass",
]

class TestBypass(unittest.TestCase):
    def test_identity(self):
        reg  = registry.registry()
        prng = random.Random(1)
        for key in BYPASS_BLOCKS:
            with self.subTest(block=key):
                spec   = reg[key]
                kwargs = dict(spec.kwargs)
                if _accepts_with_csr(spec.cls):
                    kwargs["with_csr"] = False
                dut = spec.cls(**kwargs)
                self.assertTrue(hasattr(dut, "bypass"), f"{key} has no bypass")
                dut.bypass.reset = 1
                fields = ["i", "q"] if hasattr(dut.sink, "i") else ["data"]
                data   = [{f: prng.randint(-30000, 30000) for f in fields} for _ in range(80)]
                cap = run_stream(dut, data, len(data), fields, fields,
                    sink_throttle=0.2, source_ready_rate=0.7)
                for f in fields:
                    self.assertTrue(np.array_equal(column(cap, f, 16), [d[f] for d in data]),
                        f"{key}: {f} not passed through under bypass")

if __name__ == "__main__":
    unittest.main()
