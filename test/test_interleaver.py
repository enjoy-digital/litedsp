#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPBlockInterleaver/LiteDSPBlockDeinterleaver tests, bit-exact against the models.

Both directions are checked against ``block_interleave_model``/``block_deinterleave_model``
across geometries (including the CCSDS I x 255 byte shape and the degenerate I = 1) under
randomized backpressure, the RTL interleave -> deinterleave round trip is closed (identity),
per-block ``first``/``last`` framing is verified, and the ping-pong buffering is gated for
streaming continuity: back-to-back blocks at full rate drain gaplessly (1 symbol/cycle after
the initial block fill) and the burst-spreading property (a contiguous channel burst lands
spread across the rows) is asserted on the permutation itself.

verify-tier: model
"""

import unittest

import numpy as np

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.comm.interleaver import LiteDSPBlockInterleaver, LiteDSPBlockDeinterleaver

from test.common import run_stream, stream_driver
from test.models import block_interleave_model, block_deinterleave_model

GEOMETRIES = [(2, 3), (3, 5), (5, 17), (1, 8), (4, 1), (5, 255)]  # (rows, cols); last = CCSDS I=5.

class TestBlockInterleaver(unittest.TestCase):
    # verify-tier: model — interleaver bit-exact vs block_interleave_model across geometries
    # (multiple blocks back-to-back), under randomized backpressure.
    def test_interleaver_bit_exact(self):
        rng = np.random.default_rng(1)
        for rows, cols in GEOMETRIES:
            blocks = 3 if rows*cols < 512 else 2
            data   = [int(x) for x in rng.integers(0, 256, blocks*rows*cols)]
            ref    = block_interleave_model(data, rows, cols)
            dut    = LiteDSPBlockInterleaver(rows=rows, cols=cols, width=8, with_csr=False)
            cap    = run_stream(dut, [{"data": d} for d in data], len(ref), ["data"], ["data"])
            self.assertEqual([c["data"] for c in cap], ref,
                f"interleaver mismatch rows={rows} cols={cols}")

    # verify-tier: model — deinterleaver bit-exact vs block_deinterleave_model across
    # geometries, under randomized backpressure.
    def test_deinterleaver_bit_exact(self):
        rng = np.random.default_rng(2)
        for rows, cols in GEOMETRIES:
            blocks = 3 if rows*cols < 512 else 2
            data   = [int(x) for x in rng.integers(0, 256, blocks*rows*cols)]
            ref    = block_deinterleave_model(data, rows, cols)
            dut    = LiteDSPBlockDeinterleaver(rows=rows, cols=cols, width=8, with_csr=False)
            cap    = run_stream(dut, [{"data": d} for d in data], len(ref), ["data"], ["data"])
            self.assertEqual([c["data"] for c in cap], ref,
                f"deinterleaver mismatch rows={rows} cols={cols}")

    # verify-tier: model — the permutation is the CCSDS burst spreader: models invert each
    # other, and a contiguous B-symbol channel burst lands on <= ceil(B/rows) symbols per row.
    def test_permutation_properties(self):
        for rows, cols in GEOMETRIES:
            n    = rows*cols
            data = list(range(n))
            ilv  = block_interleave_model(data, rows, cols)
            self.assertEqual(block_deinterleave_model(ilv, rows, cols), data)
            burst = min(2*rows, n)                       # Contiguous channel-position burst.
            hit   = block_deinterleave_model([1 if burst <= k < 2*burst else 0
                                              for k in range(n)], rows, cols)
            per_row = [sum(hit[r*cols:(r + 1)*cols]) for r in range(rows)]
            self.assertLessEqual(max(per_row), -(-burst//rows),
                f"burst not spread rows={rows} cols={cols}: {per_row}")

    # verify-tier: model — RTL round trip: interleaver -> deinterleaver is the identity
    # (byte-exact over multiple blocks), under randomized backpressure.
    def test_rtl_round_trip(self):
        rng  = np.random.default_rng(3)
        rows, cols = 3, 17
        data = [int(x) for x in rng.integers(0, 256, 4*rows*cols)]

        class RoundTrip(LiteXModule):
            def __init__(self):
                self.ilv  = LiteDSPBlockInterleaver(rows=rows, cols=cols, width=8, with_csr=False)
                self.dilv = LiteDSPBlockDeinterleaver(rows=rows, cols=cols, width=8, with_csr=False)
                self.sink, self.source = self.ilv.sink, self.dilv.source
                self.comb += self.ilv.source.connect(self.dilv.sink)

        dut = RoundTrip()
        cap = run_stream(dut, [{"data": d} for d in data], len(data), ["data"], ["data"])
        self.assertEqual([c["data"] for c in cap], data)

    # verify-tier: model — per-block first/last framing on the source (boundaries counted
    # from reset, every block framed).
    def test_output_framing(self):
        rows, cols = 2, 5
        n    = rows*cols
        data = [{"data": d % 256} for d in range(3*n)]
        for cls in [LiteDSPBlockInterleaver, LiteDSPBlockDeinterleaver]:
            dut = cls(rows=rows, cols=cols, width=8, with_csr=False)
            cap = run_stream(dut, data, 3*n, ["data"], ["data", "first", "last"])
            self.assertEqual([c["first"] for c in cap], ([1] + [0]*(n - 1))*3)
            self.assertEqual([c["last"]  for c in cap], ([0]*(n - 1) + [1])*3)

    # verify-tier: model — ping-pong streaming continuity: with the sink saturated and the
    # source always ready, back-to-back blocks drain gaplessly (1 symbol/cycle: no bubble
    # between a block's last symbol and the next block's first).
    def test_ping_pong_continuity(self):
        rows, cols = 3, 5
        n      = rows*cols
        blocks = 4
        data   = [{"data": d % 256} for d in range(blocks*n)]
        dut    = LiteDSPBlockInterleaver(rows=rows, cols=cols, width=8, with_csr=False)
        times  = []

        def capture_timed():
            cycle = 0
            yield dut.source.ready.eq(1)
            while len(times) < blocks*n:
                yield
                cycle += 1
                if (yield dut.source.valid):
                    times.append(cycle)

        run_simulation(dut, [stream_driver(dut.sink, data, ["data"], throttle=0.0),
                             capture_timed()])
        # After the pipeline's first output, every following symbol arrives on the next cycle
        # — including across block boundaries (the writer refills one bank while the reader
        # drains the other).
        gaps = np.diff(times)
        self.assertTrue(np.all(gaps == 1),
            f"output not gapless: gaps {sorted(set(gaps.tolist()))} at {times[:8]}...")

if __name__ == "__main__":
    unittest.main()
