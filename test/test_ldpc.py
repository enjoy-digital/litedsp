#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LDPC (802.11n rate-1/2, n=648, z=27) codec tests.

The model sweeps carry the coding-performance coverage (encoder validity H*c^T = 0 against
the expanded parity-check matrix, AWGN waterfall of the quantized layered min-sum); the RTL
runs are kept short and targeted — bit-exact vs the model including iteration counts and the
parity/failure status, always under randomized backpressure. Measured model waterfall
(4-bit LLRs = clip(round(4y), -7, 7), BPSK/AWGN, max_iters = 8, 400-1200 blocks per point):

    Eb/N0    1.0 dB   1.5 dB   2.0 dB   2.5 dB   3.0 dB
    BER     1.2e-1   5.1e-2   9.8e-3   6.7e-4   < 2.6e-6 (0 errors)
    FER     0.86     0.50     0.14     0.015    0.000

The in-suite sweep below re-measures three points with few blocks (fixed seed, deterministic)
and gates on the monotonic drop; the full table above is the reference measurement.
"""

import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.comm.ldpc import LiteDSPLDPCEncoder, LiteDSPLDPCDecoder, LDPC_BASE
from litedsp.comm.ldpc_parallel import LiteDSPLDPCDecoderZParallel

from test.common import stream_driver, stream_capture
from test.models import (ldpc_encode_model, ldpc_decode_model, ldpc_expand_h,
                         ldpc_check_parity, ldpc_layer_edges,
                         LDPC_BASE as LDPC_BASE_MODEL, LDPC_N, LDPC_K, LDPC_Z)

# First 27 parity bits (block p0) of the ramp message bit(i) = i & 1, pinned once from the
# model: regression anchor for the base-matrix/shift conventions.
KAT_P0 = [0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1]

def _random_message(seed):
    return [int(b) for b in np.random.default_rng(seed).integers(0, 2, LDPC_K)]

def _awgn_llrs(codeword, ebno_db, seed, llr_bits=4):
    """BPSK + AWGN, quantized to signed llr_bits (positive = bit 0): clip(round(4y))."""
    rng   = np.random.default_rng(seed)
    sigma = np.sqrt(1/(2*0.5*10**(ebno_db/10)))
    y     = (1 - 2*np.asarray(codeword, dtype=np.float64)) + rng.normal(0, sigma, len(codeword))
    lmax  = (1 << (llr_bits - 1)) - 1
    return [int(v) for v in np.clip(np.round(4*y), -lmax, lmax)]

@passive
def _status_monitor(dut, log):
    """Record (iterations, parity_ok, failures) at each block's last output bit."""
    while True:
        if (yield dut.source.valid) and (yield dut.source.ready) and (yield dut.source.last):
            log.append(((yield dut.iterations), (yield dut.parity_ok), (yield dut.failures)))
        yield

class TestLDPC(unittest.TestCase):
    def _decode_blocks(self, llr_blocks, llr_bits=4, max_iters=8, throttle=0.2, ready_rate=0.7,
        decoder_cls=LiteDSPLDPCDecoder):
        """Run LLR blocks through one RTL decoder; return (bits, per-block status tuples)."""
        dut = decoder_cls(llr_bits=llr_bits, max_iters=max_iters, with_csr=False)
        mask = (1 << llr_bits) - 1
        cap, status = [], []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"llrs": v & mask} for blk in llr_blocks for v in blk],
                ("llrs",), throttle=throttle),
            stream_capture(dut.source, cap, len(llr_blocks)*LDPC_K, ("data",),
                ready_rate=ready_rate),
            _status_monitor(dut, status),
        ])
        return [c["data"] for c in cap], status

    # verify-tier: model — base-matrix structure: 802.11n dimensions, 88 nonzero blocks, the
    # dual-diagonal parity part, no 4-cycles in the expanded graph (min-sum quality
    # precondition), and the gateware constant matches the model's independent copy.
    def test_base_matrix_structure(self):
        self.assertEqual(LDPC_BASE, LDPC_BASE_MODEL)
        self.assertEqual((len(LDPC_BASE), len(LDPC_BASE[0])), (12, 24))
        self.assertEqual(sum(len(l) for l in ldpc_layer_edges()), 88)
        # Column 12 (h) shifts (1, 0, 1) at rows (0, 6, 11); bidiagonal of 0-shifts after it.
        col12 = [(i, row[12]) for i, row in enumerate(LDPC_BASE) if row[12] >= 0]
        self.assertEqual(col12, [(0, 1), (6, 0), (11, 1)])
        for r in range(12):
            for c in range(13, 24):
                expected = 0 if c - 13 <= r <= c - 12 else -1
                self.assertEqual(LDPC_BASE[r][c], expected, f"parity part @({r},{c})")
        H = ldpc_expand_h()
        self.assertEqual((H.shape, int(H.sum())), (((324, 648)), 88*27))
        gram = H.astype(np.int32) @ H.astype(np.int32).T
        np.fill_diagonal(gram, 0)
        self.assertEqual(int((gram >= 2).sum()), 0, "expanded H has 4-cycles")

    # verify-tier: model — mathematical validity: H*c^T = 0 over GF(2) for encoded random
    # messages (independent of the back-substitution implementation), systematic prefix.
    def test_encode_parity(self):
        for seed in range(8):
            msg = _random_message(seed)
            cw  = ldpc_encode_model(msg)
            self.assertEqual(len(cw), LDPC_N)
            self.assertEqual(cw[:LDPC_K], msg)                 # Systematic.
            self.assertTrue(ldpc_check_parity(cw), f"H*c != 0 (seed {seed})")

    # verify-tier: trace — pinned parity block of a fixed message (shift-convention anchor).
    def test_encode_known_answer(self):
        cw = ldpc_encode_model([i & 1 for i in range(LDPC_K)])
        self.assertEqual(cw[LDPC_K:LDPC_K + LDPC_Z], KAT_P0)

    # verify-tier: model — AWGN waterfall (few-block re-measurement of the reference table in
    # the module docstring; fixed seeds, deterministic): errors drop monotonically and
    # vanish at the top of the waterfall, average iterations shrink with SNR.
    def test_model_waterfall(self):
        errs, iters = {}, {}
        points = ((1.5, 10), (2.5, 10), (3.0, 8))
        for ebno, n_blocks in points:
            e = it = 0
            for t in range(n_blocks):
                msg = _random_message(1000 + t)
                llr = _awgn_llrs(ldpc_encode_model(msg), ebno, seed=2000 + t)
                bits, used, ok = ldpc_decode_model(llr)
                e  += sum(b != m for b, m in zip(bits, msg))
                it += used
            errs[ebno], iters[ebno] = e, it/n_blocks
        self.assertGreater(errs[1.5], 20*max(errs[2.5], 1))    # Steep drop into the waterfall.
        self.assertEqual(errs[3.0], 0)                         # Clean at the top.
        self.assertLess(iters[3.0], iters[1.5])                # Early termination engages.

    # verify-tier: model — moderate-noise correction: blocks whose raw hard decisions carry
    # bit errors decode back to the exact message with converged status.
    def test_model_correction(self):
        corrected = 0
        for t in range(6):
            msg = _random_message(3020 + t)
            llr = _awgn_llrs(ldpc_encode_model(msg), 3.0, seed=4020 + t)
            raw = [1 if v < 0 else 0 for v in llr[:LDPC_K]]
            self.assertGreater(sum(b != m for b, m in zip(raw, msg)), 0)  # Channel did err.
            bits, used, ok = ldpc_decode_model(llr)
            self.assertTrue(ok)
            self.assertEqual(bits, msg, f"block {t} not corrected")
            corrected += 1
        self.assertEqual(corrected, 6)

    # verify-tier: model — encoder RTL bit-exact vs the model over two back-to-back blocks
    # (framing markers included), under randomized backpressure.
    def test_rtl_encoder_matches_model(self):
        msgs = [_random_message(seed) for seed in (10, 11)]
        dut  = LiteDSPLDPCEncoder(with_csr=False)
        cap  = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for m in msgs for b in m], ("data",),
                throttle=0.2),
            stream_capture(dut.source, cap, 2*LDPC_N, ("data", "first", "last"),
                ready_rate=0.7),
        ])
        expected = [b for m in msgs for b in ldpc_encode_model(m)]
        self.assertEqual([c["data"]  for c in cap], expected)
        n = LDPC_N
        self.assertEqual([c["first"] for c in cap], [1 if i % n == 0 else 0 for i in range(2*n)])
        self.assertEqual([c["last"]  for c in cap], [1 if i % n == n - 1 else 0 for i in range(2*n)])

    # verify-tier: model — clean strong LLRs: decoder RTL terminates after one iteration
    # with parity_ok, output bit-exact vs model and message.
    def test_rtl_decoder_clean_early_termination(self):
        msg = _random_message(20)
        llr = [7*(1 - 2*b) for b in ldpc_encode_model(msg)]
        bits_m, it_m, ok_m = ldpc_decode_model(llr)
        self.assertEqual((bits_m, it_m, ok_m), (msg, 1, True))  # Vector choice.
        bits, status = self._decode_blocks([llr])
        self.assertEqual(bits, msg)
        self.assertEqual(status, [(1, 1, 0)])

    # verify-tier: model — noisy blocks: decoder RTL bit-exact vs the model (same LLRs ->
    # same bits, same iteration count, same parity status) under randomized backpressure,
    # back-to-back (covers the per-block state/check-RAM re-init). Vectors chosen (asserted)
    # to need several — and distinct — iteration counts and to correct the channel errors,
    # so this is also the RTL correction spot-check backing the model sweep.
    def test_rtl_decoder_noisy_matches_model(self):
        blocks, expected, exp_status = [], [], []
        for ebno, m_seed, l_seed in ((2.5, 54, 64), (2.0, 52, 62)):
            msg = _random_message(m_seed)
            llr = _awgn_llrs(ldpc_encode_model(msg), ebno, seed=l_seed)
            raw = [1 if v < 0 else 0 for v in llr[:LDPC_K]]
            self.assertGreater(sum(b != m for b, m in zip(raw, msg)), 0)  # Channel did err.
            bits_m, it_m, ok_m = ldpc_decode_model(llr)
            self.assertTrue(ok_m and it_m > 1)                  # Vector choice: works > 1 iter.
            self.assertEqual(bits_m, msg)                       # Vector choice: corrects.
            blocks.append(llr)
            expected += bits_m
            exp_status.append((it_m, 1, 0))
        self.assertNotEqual(exp_status[0][0], exp_status[1][0])  # Distinct iteration counts.
        bits, status = self._decode_blocks(blocks)
        self.assertEqual(bits, expected)
        self.assertEqual(status, exp_status)

    # verify-tier: model — garbage input: the decoder exhausts max_iters, flags the failure
    # (parity_ok = 0, failure counter increments) and still matches the model bit-for-bit.
    # max_iters = 2 keeps the exhaustive-iteration RTL run short and exercises the parameter.
    def test_rtl_decoder_failure_flag(self):
        rng = np.random.default_rng(50)
        llr = [int(v) for v in rng.integers(-7, 8, LDPC_N)]
        bits_m, it_m, ok_m = ldpc_decode_model(llr, max_iters=2)
        self.assertEqual((it_m, ok_m), (2, False))              # Vector choice: does fail.
        bits, status = self._decode_blocks([llr], max_iters=2)
        self.assertEqual(bits, bits_m)
        self.assertEqual(status, [(2, 0, 1)])

    def test_z_parallel_decoder_matches_model(self):
        # The 27-lane core must preserve the serial core/model trajectory while cutting the
        # lifted-row factor from the iteration schedule. Cover one converged noisy block and
        # one deliberately uncorrectable block, including status and randomized handshakes.
        msg = _random_message(54)
        llr = _awgn_llrs(ldpc_encode_model(msg), 2.5, seed=64)
        bits_m, it_m, ok_m = ldpc_decode_model(llr)
        self.assertTrue(ok_m and it_m > 1)
        bits, status = self._decode_blocks([llr], decoder_cls=LiteDSPLDPCDecoderZParallel)
        self.assertEqual(bits, bits_m)
        self.assertEqual(status, [(it_m, 1, 0)])

        rng = np.random.default_rng(50)
        bad = [int(v) for v in rng.integers(-7, 8, LDPC_N)]
        bad_m, bad_it, bad_ok = ldpc_decode_model(bad, max_iters=2)
        bits, status = self._decode_blocks([bad], max_iters=2,
            decoder_cls=LiteDSPLDPCDecoderZParallel)
        self.assertEqual((bad_it, bad_ok), (2, False))
        self.assertEqual(bits, bad_m)
        self.assertEqual(status, [(2, 0, 1)])

        dut = LiteDSPLDPCDecoderZParallel(with_csr=False)
        self.assertEqual(dut.parallelism, LDPC_Z)
        self.assertEqual(dut.cycles_per_iteration, 464)
        self.assertLess(dut.cycles_per_block,
            LiteDSPLDPCDecoder(with_csr=False).cycles_per_block/9)

    # verify-tier: model — invalid parameters rejected with ValueError.
    def test_invalid_params(self):
        for decoder_cls in (LiteDSPLDPCDecoder, LiteDSPLDPCDecoderZParallel):
            for kwargs in ({"llr_bits": 1}, {"max_iters": 0}, {"max_iters": 32}):
                with self.assertRaises(ValueError):
                    decoder_cls(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
