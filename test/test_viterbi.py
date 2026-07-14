#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from migen import run_simulation

from litex.gen import LiteXModule

from litedsp.comm.coding  import LiteDSPConvEncoder
from litedsp.comm.viterbi import LiteDSPViterbiDecoder

from test.common import stream_driver, stream_capture
from test.models import viterbi_model, pack_llrs

# Python reference encoder (mirrors LiteDSPConvEncoder) --------------------------------------------

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

# Viterbi ------------------------------------------------------------------------------------------

# Expected decoder output for test_golden_trace_dense_errors, computed once with the current
# implementation (Random(5) message, double-bit flips every 5 symbols). The error pattern is
# beyond the guaranteed correction capability, so the surviving path is implementation-defined:
# this pins the exact ACS/traceback behavior (24/60 bits differ from the clean message). The
# output is deterministic and handshake-invariant (verified under different stall seeds), so it
# is stable across LITEDSP_SEED rotation.
GOLDEN_TRACE = [1, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 0,
                0, 1, 0, 1, 1, 1, 0, 0, 0, 1, 1, 0, 1, 0, 1, 1, 1, 0, 0, 0,
                1, 1, 1, 0, 0, 1, 0, 1, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1]

# BPSK-over-AWGN helper for the soft-decision tests: coded bit b -> +/-1, AWGN at Eb/N0 (rate
# R = 1/2), returning (hard symbols, packed 4-bit LLR words) for the same noise realization.
# LLRs follow the soft_demap convention (positive = bit 0): 2y/sigma^2, saturated to +/-7.
def bpsk_awgn(syms, ebn0_db, rng, llr_bits=4):
    x     = np.array([[1 - 2*((s >> j) & 1) for j in range(2)] for s in syms], dtype=float)
    sigma = np.sqrt(1.0/(2*0.5*10**(ebn0_db/10)))
    y     = x + sigma*rng.normal(size=x.shape)
    hi    = (1 << (llr_bits - 1)) - 1
    llr   = np.clip(np.round((2.0/sigma**2)*y), -hi, hi).astype(int)
    hard  = [int(y[t, 0] < 0) | (int(y[t, 1] < 0) << 1) for t in range(len(syms))]
    return hard, pack_llrs(llr.tolist(), llr_bits)

class TestViterbi(unittest.TestCase):
    def _decode(self, symbols, n_bits, **kwargs):
        dut = LiteDSPViterbiDecoder(with_csr=False, **kwargs)
        field = "data" if dut.llr_bits is None else "llrs"
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{field: s} for s in symbols], (field,), throttle=0.2),
            stream_capture(dut.source, cap, n_bits, ("data",), ready_rate=0.7),
        ])
        return [c["data"] for c in cap]

    # verify-tier: model — exact message recovery through the HW encoder -> HW decoder chain.
    def test_encoder_chain_clean(self):
        # HW encoder -> HW decoder recovers the message exactly.
        prng = random.Random(1)
        bits = [prng.randint(0, 1) for _ in range(400)]

        class Chain(LiteXModule):
            def __init__(self):
                self.enc = LiteDSPConvEncoder(with_csr=False)
                self.dec = LiteDSPViterbiDecoder(with_csr=False)
                self.sink, self.source = self.enc.sink, self.dec.source
                self.comb += self.enc.source.connect(self.dec.sink)

        dut = Chain()
        n_out = len(bits) - dut.dec.traceback - 4
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for b in bits], ("data",), throttle=0.2),
            stream_capture(dut.source, cap, n_out, ("data",), ready_rate=0.7),
        ])
        self.assertEqual([c["data"] for c in cap], bits[:n_out])

    # verify-tier: model — exact message recovery under correctable (sparse) errors.
    def test_corrects_sparse_errors(self):
        # Flip well-separated coded bits: the decoder must still recover the message.
        prng = random.Random(2)
        bits = [prng.randint(0, 1) for _ in range(400)]
        syms = conv_encode(bits)
        for pos in range(40, len(syms) - 60, 45):          # 1 flipped bit every 45 symbols.
            syms[pos] ^= 1 << prng.randint(0, 1)
        n_out = 400 - 56 - 4
        decoded = self._decode(syms, n_out)
        self.assertEqual(decoded, bits[:n_out])

    # verify-tier: trace — fixed-seed exact-output regression (see GOLDEN_TRACE above).
    def test_golden_trace_dense_errors(self):
        prng = random.Random(5)
        bits = [prng.randint(0, 1) for _ in range(120)]
        syms = conv_encode(bits)
        for pos in range(6, len(syms) - 8, 5):             # Both coded bits, every 5 symbols.
            syms[pos] ^= 0b11
        decoded = self._decode(syms, len(GOLDEN_TRACE))
        self.assertEqual(decoded, GOLDEN_TRACE)

    # verify-tier: model — hard model reproduces the RTL-pinned golden trace step-exactly.
    def test_hard_model_matches_golden_trace(self):
        prng = random.Random(5)
        bits = [prng.randint(0, 1) for _ in range(120)]
        syms = conv_encode(bits)
        for pos in range(6, len(syms) - 8, 5):
            syms[pos] ^= 0b11
        self.assertEqual(viterbi_model(syms)[:len(GOLDEN_TRACE)], GOLDEN_TRACE)

    # verify-tier: model — saturated LLRs reduce the max-log metric to a scaled Hamming
    # distance, so the soft decoder must match the hard decoder bit-for-bit (same errors).
    def test_soft_saturated_llrs_match_hard(self):
        prng = random.Random(4)
        bits = [prng.randint(0, 1) for _ in range(240)]
        syms = conv_encode(bits)
        for pos in range(10, len(syms) - 20, 9):           # Sparse coded-bit errors.
            syms[pos] ^= 1 << prng.randint(0, 1)
        words = pack_llrs([[-7 if (s >> j) & 1 else 7 for j in range(2)] for s in syms], 4)
        n_out = len(bits) - 56 - 4
        hard  = self._decode(syms,  n_out)
        soft  = self._decode(words, n_out, llr_bits=4)
        self.assertEqual(soft, hard)
        self.assertEqual(soft, bits[:n_out])               # Sparse errors are also corrected.

    # verify-tier: model — soft RTL bit-exact vs viterbi_model on one noisy AWGN block,
    # under randomized backpressure (spot-check anchoring the model-based BER sweep).
    def test_soft_noisy_rtl_matches_model(self):
        rng  = np.random.default_rng(9)
        bits = list((rng.random(240) < 0.5).astype(int))
        _, words = bpsk_awgn(conv_encode(bits), ebn0_db=2.0, rng=rng)
        n_out = len(bits) - 56 - 4
        got = self._decode(words, n_out, llr_bits=4)
        self.assertEqual(got, viterbi_model(words, llr_bits=4)[:n_out])

    # verify-tier: model — soft-decision BER gain over hard-decision (model-based sweep;
    # the RTL is anchored to the model by test_soft_noisy_rtl_matches_model). Measured with
    # 4-bit LLRs (20k message bits, seed 7): hard BER 1.5e-2 @ 3.5 dB / 6.1e-3 @ 4.0 dB;
    # soft reaches those BERs at ~1.7 dB / ~2.05 dB, i.e. ~1.8-1.9 dB equivalent gain.
    # Gates: soft at (Eb/N0* - 1.5 dB) must not exceed hard at Eb/N0* (>= 1.5 dB gain),
    # and soft at the same Eb/N0* must be at least 4x below hard.
    def test_soft_ber_gain(self):
        ebn0  = 3.5                                        # Hard-decision BER ~1.5e-2 here.
        n_msg = 20000
        rng   = np.random.default_rng(7)
        bits  = list((rng.random(n_msg) < 0.5).astype(int))
        syms  = conv_encode(bits)

        def ber(out):
            n = len(out) - 60                              # Skip the traceback-truncated tail.
            return sum(o != b for o, b in zip(out[:n], bits[:n]))/n

        hard, _        = bpsk_awgn(syms, ebn0, np.random.default_rng(7))
        _, soft_same   = bpsk_awgn(syms, ebn0, np.random.default_rng(7))
        _, soft_minus  = bpsk_awgn(syms, ebn0 - 1.5, np.random.default_rng(7))
        hard_ber       = ber(viterbi_model(hard))
        soft_same_ber  = ber(viterbi_model(soft_same,  llr_bits=4))
        soft_minus_ber = ber(viterbi_model(soft_minus, llr_bits=4))
        # Operating point sanity: hard BER ~1e-2 (statistically meaningful comparison).
        self.assertGreater(hard_ber, 5e-3)
        self.assertLess(hard_ber, 5e-2)
        # >= 1.5 dB equivalent gain: soft with 1.5 dB less SNR still at least as good.
        self.assertLessEqual(soft_minus_ber, hard_ber,
            f"soft@{ebn0 - 1.5}dB BER {soft_minus_ber:.2e} > hard@{ebn0}dB {hard_ber:.2e}")
        # Same-SNR comparison: soft clearly below hard.
        self.assertLessEqual(soft_same_ber, hard_ber/4,
            f"soft@{ebn0}dB BER {soft_same_ber:.2e} vs hard {hard_ber:.2e}")

    # verify-tier: model — HW encoder bit-exact against the conv_encode reference.
    def test_uncoded_reference_model(self):
        # Sanity: the Python reference encoder matches the HW encoder.
        prng = random.Random(3)
        bits = [prng.randint(0, 1) for _ in range(64)]
        enc  = LiteDSPConvEncoder(with_csr=False)
        cap  = []
        run_simulation(enc, [
            stream_driver(enc.sink, [{"data": b} for b in bits], ("data",), throttle=0.1),
            stream_capture(enc.source, cap, len(bits), ("data",), ready_rate=0.9),
        ])
        self.assertEqual([c["data"] for c in cap], conv_encode(bits))

if __name__ == "__main__":
    unittest.main()
