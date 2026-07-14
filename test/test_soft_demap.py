#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPSoftDemapper tests, bit-exact against ``soft_demap_model``.

Exhaustive constellation sweep (every point + boundaries +/-1 LSB) for QPSK/16-QAM/64-QAM,
sign(LLR) agreement with the hard slicer's Gray-coded decisions, symmetric saturation edges
and the declared latency — all under randomized backpressure.

verify-tier: model
"""

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.comm.soft_demap import LiteDSPSoftDemapper

from test.common import run_stream, column, to_signed
from test.models import soft_demap_model, slicer_model

# QPSK / 16-QAM / 64-QAM sweep configurations.
CONFIGS = [(1, 8000), (2, 6000), (3, 3000)]  # (bits_per_axis, spacing).

def unpack_llrs(packed, bits_per_axis, llr_bits):
    """Per-slot signed LLR columns (i bits LSB-first, then q bits) from packed llrs values."""
    mask = (1 << llr_bits) - 1
    return [to_signed((np.asarray(packed) >> (n*llr_bits)) & mask, llr_bits)
            for n in range(2*bits_per_axis)]

def sweep_vectors(bits_per_axis, spacing):
    """Every constellation point, every boundary +/-1 LSB, extremes and randoms."""
    L    = 1 << bits_per_axis
    prng = random.Random(L)
    levels = [(2*k - (L - 1))*spacing for k in range(L)]
    xi = [li for li in levels for _ in levels]            # Cross product: every point.
    xq = [lq for _ in levels for lq in levels]
    edges = []
    for j in range(L - 1):                                # Boundaries, hit and straddled.
        b = (2*j - L + 2)*spacing
        edges += [b - 1, b, b + 1]
    xi += edges + [-32768, 32767, 0]
    xq += list(reversed(edges)) + [32767, -32768, 0]
    xi += [prng.randint(-32768, 32767) for _ in range(200)]
    xq += [prng.randint(-32768, 32767) for _ in range(200)]
    return xi, xq

class TestSoftDemap(unittest.TestCase):
    def run_demap(self, xi, xq, bits_per_axis, spacing, llr_bits=4, llr_scale=None):
        dut = LiteDSPSoftDemapper(bits_per_axis=bits_per_axis, spacing=spacing,
            llr_bits=llr_bits, data_width=16, with_csr=False)
        if llr_scale is not None:
            dut.llr_scale.reset = llr_scale
        cap = run_stream(dut, [{"i": xi[k], "q": xq[k]} for k in range(len(xi))],
            len(xi), ["i", "q"], ["llrs"])  # Default randomized backpressure.
        return column(cap, "llrs")

    def test_bit_exact(self):
        # Identity scale plus a normalizing and a rounding-heavy scale, per constellation.
        for bits_per_axis, spacing in CONFIGS:
            xi, xq = sweep_vectors(bits_per_axis, spacing)
            for llr_scale in [1 << 15, 7*(1 << 15)//(4*spacing), 3]:
                got = self.run_demap(xi, xq, bits_per_axis, spacing, llr_scale=llr_scale)
                ref = soft_demap_model(xi, xq, bits_per_axis=bits_per_axis, spacing=spacing,
                    llr_scale=llr_scale)
                self.assertTrue(np.array_equal(got, ref),
                    f"llrs mismatch bits_per_axis={bits_per_axis} llr_scale={llr_scale}")

    def test_sign_matches_hard_slicer(self):
        # Wherever an LLR is nonzero, its sign encodes the hard decision (LLR < 0 -> bit 1),
        # matching the Gray label of the slicer's level index. Identity scale keeps every
        # non-boundary sample's LLR nonzero and sign-exact (saturation preserves sign).
        for bits_per_axis, spacing in CONFIGS:
            xi, xq = sweep_vectors(bits_per_axis, spacing)
            got   = self.run_demap(xi, xq, bits_per_axis, spacing)
            slots = unpack_llrs(got, bits_per_axis, llr_bits=4)
            _, _, symbol = slicer_model(xi, xq, bits_per_axis=bits_per_axis, spacing=spacing)
            ki   = symbol & ((1 << bits_per_axis) - 1)
            kq   = symbol >> bits_per_axis
            gray = [ki ^ (ki >> 1), kq ^ (kq >> 1)]
            for n, llr in enumerate(slots):
                axis, j = divmod(n, bits_per_axis)
                bit     = (gray[axis] >> j) & 1
                nz      = llr != 0
                self.assertTrue(np.array_equal((llr[nz] < 0).astype(int), bit[nz]),
                    f"sign/hard-decision mismatch bits_per_axis={bits_per_axis} slot={n}")

    def test_saturation_edges(self):
        # Max scale + extreme inputs: every LLR pins at +/-(2**(llr_bits-1)-1), never at
        # -2**(llr_bits-1) (symmetric saturation), still bit-exact vs the model.
        for llr_bits in [3, 4]:
            hi = (1 << (llr_bits - 1)) - 1
            xi = [-32768, 32767, -32768, 32767]
            xq = [32767, -32768, -32768, 32767]
            got = self.run_demap(xi, xq, 2, 6000, llr_bits=llr_bits, llr_scale=0xFFFF)
            ref = soft_demap_model(xi, xq, bits_per_axis=2, spacing=6000, llr_bits=llr_bits,
                llr_scale=0xFFFF)
            self.assertTrue(np.array_equal(got, ref))
            for llr in unpack_llrs(got, 2, llr_bits):
                self.assertTrue(np.all(np.abs(llr) == hi), f"expected +/-{hi}, got {llr}")

    def test_qpsk_known_mapping(self):
        # Functional intent: QPSK quadrants, scale 7/2**15 (raw 32768 -> LLR 7).
        pts = [(5000, -7000), (-3000, 3000), (32767, 32767), (-32768, -32768)]
        got = self.run_demap([p[0] for p in pts], [p[1] for p in pts], 1, 8000, llr_scale=7)
        llr_i, llr_q = unpack_llrs(got, 1, 4)
        self.assertTrue(np.array_equal(llr_i, [-1,  1, -7,  7]))
        self.assertTrue(np.array_equal(llr_q, [ 1, -1, -7,  7]))

    def test_latency(self):
        # Free-flow: output k emerges exactly self.latency cycles after input k is accepted.
        dut = LiteDSPSoftDemapper(bits_per_axis=2, spacing=6000, with_csr=False)
        in_cycles, out_cycles = [], []
        prng = random.Random(7)

        @passive
        def driver():
            cycle = 0
            yield dut.sink.valid.eq(1)
            while True:
                yield
                if (yield dut.sink.ready):
                    in_cycles.append(cycle)
                    yield dut.sink.i.eq(prng.randint(-32768, 32767))
                    yield dut.sink.q.eq(prng.randint(-32768, 32767))
                cycle += 1

        def capture():
            cycle = 0
            yield dut.source.ready.eq(1)
            while len(out_cycles) < 32:
                yield
                if (yield dut.source.valid):
                    out_cycles.append(cycle)
                cycle += 1

        run_simulation(dut, [driver(), capture()])
        deltas = {out_cycles[k] - in_cycles[k] for k in range(4, len(out_cycles))}
        self.assertEqual(deltas, {dut.latency})

if __name__ == "__main__":
    unittest.main()
