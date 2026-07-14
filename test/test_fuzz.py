#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Reset-mid-stream fuzzing: after a reset pulse, a block must behave as freshly built.

Drives a first random sequence, pulses ``dut.reset`` (all blocks are ``@ResetInserter()``-
wrapped), then drives a second sequence and requires the post-reset output to bit-match the
golden model run on the second sequence alone. Catches state that is not on the reset tree
(e.g. an integrator or delay line that survives reset) — a classic IP-quality escape that
functional tests never see.
"""

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.filter.fir        import LiteDSPFIRFilterComplex
from litedsp.filter.iir_biquad import LiteDSPIIRBiquad
from litedsp.filter.dc_blocker import LiteDSPDCBlocker
from litedsp.filter.moving_average import LiteDSPMovingAverage
from litedsp.level.gain        import LiteDSPGain
from litedsp.correction.dc_offset import LiteDSPDCOffset

from test import models
from test.common import column

# (name, factory, model(xi, xq) -> (ri, rq)).
CASES = [
    ("fir_complex",
     lambda: LiteDSPFIRFilterComplex(n_taps=8, data_width=16, with_csr=False),
     lambda xi, xq: models.fir_complex_model(xi, xq,
         [(1 << 15) - 1] + [0]*7)),
    ("iir_biquad",
     lambda: LiteDSPIIRBiquad(data_width=16, with_csr=False),
     lambda xi, xq: (models.iir_biquad_model(xi, {"b0": 1 << 14, "b1": 0, "b2": 0,
                                                  "a1": 0, "a2": 0}),
                     models.iir_biquad_model(xq, {"b0": 1 << 14, "b1": 0, "b2": 0,
                                                  "a1": 0, "a2": 0}))),
    ("dc_blocker",
     lambda: LiteDSPDCBlocker(data_width=16, with_csr=False),
     lambda xi, xq: (models.dc_blocker_model(xi), models.dc_blocker_model(xq))),
    ("moving_average",
     lambda: LiteDSPMovingAverage(data_width=16, length_log2=3, with_csr=False),
     lambda xi, xq: (models.moving_average_model(xi, 3), models.moving_average_model(xq, 3))),
    ("gain",
     lambda: LiteDSPGain(data_width=16, with_csr=False),
     lambda xi, xq: models.gain_model(xi, xq, 1 << 14, 0)),
    ("dc_offset",
     lambda: LiteDSPDCOffset(data_width=16, mu=8, with_csr=False),
     lambda xi, xq: (models.dc_offset_model(xi, 8), models.dc_offset_model(xq, 8))),
]

def _run_with_reset(dut, seq_a, seq_b, n_out):
    """Drive seq_a, pulse reset, drive seq_b; return outputs captured after the reset."""
    captured = []
    post     = []

    def sequencer():
        prng = random.Random(11)
        # Phase 1: drive seq_a with gaps.
        for s in seq_a:
            while prng.random() < 0.2:
                yield dut.sink.valid.eq(0)
                yield
            yield dut.sink.i.eq(s["i"])
            yield dut.sink.q.eq(s["q"])
            yield dut.sink.valid.eq(1)
            yield
            while (yield dut.sink.ready) == 0:
                yield
        yield dut.sink.valid.eq(0)
        for _ in range(4):
            yield
        # Reset pulse (2 cycles), then mark the post-reset boundary.
        yield dut.reset.eq(1)
        yield
        yield
        yield dut.reset.eq(0)
        yield
        post.append(len(captured))
        # Phase 2: drive seq_b.
        for s in seq_b:
            while prng.random() < 0.2:
                yield dut.sink.valid.eq(0)
                yield
            yield dut.sink.i.eq(s["i"])
            yield dut.sink.q.eq(s["q"])
            yield dut.sink.valid.eq(1)
            yield
            while (yield dut.sink.ready) == 0:
                yield
        yield dut.sink.valid.eq(0)
        while len(captured) < n_out + post[0]:
            yield

    @passive
    def capture():
        prng = random.Random(12)
        while True:
            yield dut.source.ready.eq(1 if prng.random() < 0.8 else 0)
            yield
            if (yield dut.source.valid) and (yield dut.source.ready):
                captured.append({"i": (yield dut.source.i), "q": (yield dut.source.q)})

    run_simulation(dut, [sequencer(), capture()])
    return captured[post[0]:]

class TestResetFuzz(unittest.TestCase):
    def test_reset_restores_fresh_behavior(self):
        prng = random.Random(9)
        for name, factory, model in CASES:
            with self.subTest(block=name):
                seq_a = [{"i": prng.randint(-30000, 30000), "q": prng.randint(-30000, 30000)}
                         for _ in range(60)]
                seq_b = [{"i": prng.randint(-30000, 30000), "q": prng.randint(-30000, 30000)}
                         for _ in range(60)]
                dut   = factory()
                n_out = 50
                got   = _run_with_reset(dut, seq_a, seq_b, n_out)[:n_out]
                bi    = [s["i"] for s in seq_b]
                bq    = [s["q"] for s in seq_b]
                ri, rq = model(bi, bq)
                gi = column(got, "i", 16)
                gq = column(got, "q", 16)
                self.assertTrue(np.array_equal(gi, np.asarray(ri)[:n_out]),
                    f"{name}: post-reset I diverges from fresh-run model (state off the reset tree?)")
                self.assertTrue(np.array_equal(gq, np.asarray(rq)[:n_out]),
                    f"{name}: post-reset Q diverges from fresh-run model")

if __name__ == "__main__":
    unittest.main()
