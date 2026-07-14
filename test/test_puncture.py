#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPPuncturer/LiteDSPDepuncturer tests, bit-exact against the models.

Both directions are checked against ``puncture_model``/``depuncture_model`` for every DVB-S
pattern constant under randomized backpressure, the runtime pattern-phase reset is exercised
in both blocks, and the full RX path is closed with a puncture -> AWGN -> depuncture ->
soft-Viterbi loopback at rates 2/3 and 3/4 (moderate noise, exact message recovery).

verify-tier: model
"""

import unittest

import numpy as np

from migen import run_simulation, passive

from litex.gen import LiteXModule

from litedsp.comm.puncture import (LiteDSPPuncturer, LiteDSPDepuncturer, PUNCTURE_1_2,
    PUNCTURE_2_3, PUNCTURE_3_4, PUNCTURE_5_6, PUNCTURE_7_8)
from litedsp.comm.viterbi  import LiteDSPViterbiDecoder

from test.common import run_stream, stream_capture
from test.models import puncture_model, depuncture_model, viterbi_model

PATTERNS = [("1/2", PUNCTURE_1_2), ("2/3", PUNCTURE_2_3), ("3/4", PUNCTURE_3_4),
            ("5/6", PUNCTURE_5_6), ("7/8", PUNCTURE_7_8)]

# Python reference encoder (mirrors LiteDSPConvEncoder; kept local to avoid a test import cycle).
def conv_encode(bits, constraint=7, polys=(0o171, 0o133)):
    reg, out = 0, []
    for b in bits:
        full = b | (reg << 1)
        sym  = 0
        for k, g in enumerate(polys):
            sym |= (bin(g & full).count("1") & 1) << k
        out.append(sym)
        reg = full & ((1 << (constraint - 1)) - 1)
    return out

class TestPuncture(unittest.TestCase):
    # verify-tier: model — puncturer bit-exact vs puncture_model for every DVB-S pattern,
    # under randomized backpressure.
    def test_puncturer_bit_exact(self):
        rng = np.random.default_rng(1)
        for name, pattern in PATTERNS:
            symbols = [int(s) for s in rng.integers(0, 4, 90)]
            ref     = puncture_model(symbols, pattern)
            dut     = LiteDSPPuncturer(pattern=pattern, with_csr=False)
            cap     = run_stream(dut, [{"data": s} for s in symbols], len(ref),
                                 ["data"], ["data"])
            self.assertEqual([c["data"] for c in cap], ref, f"puncturer mismatch rate {name}")

    # verify-tier: model — depuncturer bit-exact vs depuncture_model (erasure = LLR 0 at
    # punctured slots) for every DVB-S pattern, under randomized backpressure.
    def test_depuncturer_bit_exact(self):
        rng = np.random.default_rng(2)
        for name, pattern in PATTERNS:
            for llr_bits in [3, 4]:
                mask = (1 << llr_bits) - 1
                llrs = [int(l) for l in rng.integers(-(1 << (llr_bits - 1)),
                                                     1 << (llr_bits - 1), 120)]
                ref  = depuncture_model(llrs, pattern, llr_bits=llr_bits)
                dut  = LiteDSPDepuncturer(pattern=pattern, llr_bits=llr_bits, with_csr=False)
                cap  = run_stream(dut, [{"llrs": l & mask} for l in llrs], len(ref),
                                  ["llrs"], ["llrs"])
                self.assertEqual([c["llrs"] for c in cap], ref,
                    f"depuncturer mismatch rate {name} llr_bits={llr_bits}")

    # verify-tier: model — runtime pattern-phase reset: after a phase_rst pulse the puncturer
    # restarts at pattern column 0 (the model run with phase=0 on the post-reset stream).
    def test_puncturer_phase_reset(self):
        pattern = PUNCTURE_3_4
        first   = [3, 1, 2, 0]                             # Leaves the phase at column 1.
        second  = [1, 3, 0, 2, 3, 1]
        ref     = puncture_model(first, pattern) + puncture_model(second, pattern, phase=0)
        dut     = LiteDSPPuncturer(pattern=pattern, with_csr=False)
        cap     = []

        @passive
        def sequence():
            for group, rst in [(first, True), (second, False)]:
                for s in group:
                    yield dut.sink.data.eq(s)
                    yield dut.sink.valid.eq(1)
                    yield
                    while (yield dut.sink.ready) == 0:
                        yield
                yield dut.sink.valid.eq(0)
                if rst:
                    yield dut.phase_rst.eq(1)
                    yield
                    yield dut.phase_rst.eq(0)
            while True:
                yield

        run_simulation(dut, [sequence(), stream_capture(dut.source, cap, len(ref), ("data",))])
        self.assertEqual([c["data"] for c in cap], ref)

    # verify-tier: model — depuncturer phase reset drops the partially assembled symbol and
    # restarts at pattern column 0.
    def test_depuncturer_phase_reset(self):
        pattern = PUNCTURE_3_4
        first   = [3, -4, 5, -6, 2]                        # 5th LLR starts column 0 (partial).
        second  = [1, -2, 3, -4, 5, -6, 7, -8]
        ref     = (depuncture_model(first, pattern) +      # Trailing partial LLR dropped.
                   depuncture_model(second, pattern, phase=0))
        dut     = LiteDSPDepuncturer(pattern=pattern, llr_bits=4, with_csr=False)
        cap     = []

        @passive
        def sequence():
            for group, rst in [(first, True), (second, False)]:
                for l in group:
                    yield dut.sink.llrs.eq(l & 0xF)
                    yield dut.sink.valid.eq(1)
                    yield
                    while (yield dut.sink.ready) == 0:
                        yield
                yield dut.sink.valid.eq(0)
                if rst:
                    yield dut.phase_rst.eq(1)
                    yield
                    yield dut.phase_rst.eq(0)
            while True:
                yield

        run_simulation(dut, [sequence(), stream_capture(dut.source, cap, len(ref), ("llrs",))])
        self.assertEqual([c["llrs"] for c in cap], ref)

    # verify-tier: model — RX chain loopback at rates 2/3 and 3/4: TX (conv_encode +
    # puncture_model) -> BPSK/AWGN at Eb/N0 = 5 dB (raw channel BER ~0.5-2%) -> 4-bit LLRs
    # -> RTL depuncturer -> RTL soft Viterbi decoder recovers the message exactly, under
    # randomized backpressure.
    def test_puncture_depuncture_soft_decode_loopback(self):
        for name, pattern, rate in [("2/3", PUNCTURE_2_3, 2/3), ("3/4", PUNCTURE_3_4, 3/4)]:
            rng   = np.random.default_rng(3)
            bits  = [int(b) for b in rng.random(300) < 0.5]
            tx    = puncture_model(conv_encode(bits), pattern)
            sigma = np.sqrt(1.0/(2*rate*10**(5.0/10)))
            y     = (1 - 2*np.array(tx, dtype=float)) + sigma*rng.normal(size=len(tx))
            llrs  = np.clip(np.round((2.0/sigma**2)*y), -7, 7).astype(int)

            class Chain(LiteXModule):
                def __init__(self):
                    self.dep = LiteDSPDepuncturer(pattern=pattern, llr_bits=4, with_csr=False)
                    self.dec = LiteDSPViterbiDecoder(llr_bits=4, with_csr=False)
                    self.sink, self.source = self.dep.sink, self.dec.source
                    self.comb += self.dep.source.connect(self.dec.sink)

            dut   = Chain()
            n_out = len(bits) - dut.dec.traceback - 4
            cap   = run_stream(dut, [{"llrs": int(l) & 0xF} for l in llrs], n_out,
                               ["llrs"], ["data"])
            got   = [c["data"] for c in cap]
            self.assertEqual(got, bits[:n_out], f"loopback decode failed at rate {name}")
            # The RTL chain also matches the model chain bit-for-bit.
            words = depuncture_model([int(l) for l in llrs], pattern)
            self.assertEqual(got, viterbi_model(words, llr_bits=4)[:n_out])

if __name__ == "__main__":
    unittest.main()
