#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Reed-Solomon RS(255, k) codec tests.

Model sweeps carry the error-pattern coverage (strided single/double positions at t = 2, random
patterns up to capability and beyond at t = 16, bursts); the RTL runs are kept short and
targeted — bit-exact vs the model including corrected counts and the uncorrectable flag, always
under randomized backpressure. Note the t = 2 code has minimum distance 5, so some 3-error
patterns legitimately *miscorrect* to another codeword (bounded-distance decoding): the tests
pin both a flagged and a miscorrecting pattern, model and RTL agreeing byte-for-byte on each.
"""

import random
import unittest

from migen import run_simulation, passive

from litex.gen import LiteXModule

from litedsp.comm.rs import (
    LiteDSPRSEncoder, LiteDSPRSDecoder,
    LiteDSPCCSDSRSEncoder, LiteDSPCCSDSRSDecoder,
)

from test.common import stream_driver, stream_capture
from test.models import (
    gf_mul, gf_tables, rs_generator, rs_encode_model, rs_decode_model,
    CCSDS_TO_DUAL, CCSDS_TO_CONVENTIONAL,
    ccsds_rs_encode_model, ccsds_rs_decode_model,
)

# Known-answer parity for the ramp message 0, 1, ..., 222 through RS(255, 223) (0x11D, fcr = 0),
# pinned once from the model: regression anchor for the field/generator conventions.
KAT_PARITY = [65, 132, 17, 131, 177, 31, 219, 83, 116, 33, 147, 150, 150, 205, 167, 14,
              29, 181, 200, 102, 132, 175, 34, 37, 100, 184, 156, 198, 6, 159, 23, 46]

# Independent libfec ``encode_rs_ccsds`` result for the dual-basis ramp message 0..222.
CCSDS_KAT_PARITY = [
    0x4f, 0xfb, 0x92, 0xdd, 0x55, 0x7e, 0xc6, 0x7f,
    0x27, 0xfb, 0x89, 0x82, 0xcf, 0x58, 0xf8, 0xfd,
    0x02, 0x8a, 0xd1, 0x17, 0xfc, 0xef, 0x6b, 0x27,
    0x93, 0xd0, 0x41, 0x88, 0x26, 0x57, 0x86, 0x51,
]

def _corrupt(codeword, positions, seed):
    """Flip ``positions`` of ``codeword`` with random nonzero error magnitudes."""
    prng = random.Random(seed)
    out  = list(codeword)
    for p in positions:
        out[p] ^= prng.randrange(1, 256)
    return out

@passive
def _status_monitor(dut, log):
    """Record (corrected, uncorrectable, uncorrectable_count, corrected_total) at each block end."""
    while True:
        if (yield dut.source.valid) and (yield dut.source.ready) and (yield dut.source.last):
            log.append(((yield dut.corrected), (yield dut.uncorrectable),
                        (yield dut.uncorrectable_count), (yield dut.corrected_total)))
        yield

class TestRS(unittest.TestCase):
    def _random_message(self, k, seed):
        prng = random.Random(seed)
        return [prng.randrange(256) for _ in range(k)]

    def _decode_blocks(self, codewords, n, k, architecture="classic"):
        """Run codewords through one RTL decoder; return (bytes, per-block status tuples)."""
        dut = LiteDSPRSDecoder(n=n, k=k, with_csr=False, architecture=architecture)
        cap, status = [], []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for cw in codewords for b in cw], ("data",),
                throttle=0.2),
            stream_capture(dut.source, cap, len(codewords)*k, ("data",), ready_rate=0.7),
            _status_monitor(dut, status),
        ])
        return [c["data"] for c in cap], status

    def _expected_blocks(self, codewords, n, k):
        """Model outputs + per-block status tuples in the monitor's format."""
        out, status = [], []
        total, unc_count = 0, 0
        for cw in codewords:
            msg, corrected, uncorrectable = rs_decode_model(cw, n, k)
            out       += msg
            total     += corrected
            unc_count += 1 if uncorrectable else 0
            status.append((corrected, 1 if unc_count else 0, unc_count, total))
        return out, status

    # verify-tier: model — antilog/log table consistency (x * x^-1 = 1 over the whole field).
    def test_gf_tables_inverse(self):
        exp, log = gf_tables()
        self.assertEqual(exp[255], 1)                      # Wrap entry for 255 - log addressing.
        for x in range(1, 256):
            self.assertEqual(gf_mul(x, exp[255 - log[x]]), 1)

    # verify-tier: model — mathematical validity: encoded codewords evaluate to zero at every
    # generator root alpha^0..alpha^(2t-1) (independent of the LFSR implementation details).
    def test_encode_codeword_roots(self):
        exp, _ = gf_tables()
        def poly_eval(desc, x):                            # Descending-coefficient Horner.
            acc = 0
            for c in desc:
                acc = gf_mul(acc, x) ^ c
            return acc
        for t in (1, 2, 8, 16):
            k = 255 - 2*t
            g = rs_generator(2*t)
            self.assertEqual(len(g), 2*t + 1)
            self.assertEqual(g[-1], 1)                     # Monic.
            msg = self._random_message(k, seed=t)
            cw  = rs_encode_model(msg, 255, k)
            self.assertEqual(cw[:k], msg)                  # Systematic.
            self.assertEqual(len(cw), 255)
            for i in range(2*t):
                self.assertEqual(poly_eval(cw, exp[i]), 0, f"t={t}: nonzero at root alpha^{i}")

    # verify-tier: trace — pinned parity of a fixed message (field/generator convention anchor).
    def test_encode_known_answer(self):
        cw = rs_encode_model([i & 0xFF for i in range(223)], 255, 223)
        self.assertEqual(cw[223:], KAT_PARITY)

    # verify-tier: trace — CCSDS Annex-F basis maps and an independently generated libfec
    # RS(255,223) codeword pin the standard's field/root/dual-basis conventions.
    def test_ccsds_basis_and_known_answer(self):
        samples = {0x00: 0x00, 0x01: 0x7b, 0x02: 0xaf, 0x03: 0xd4,
                   0x55: 0x8b, 0xaa: 0x34, 0xff: 0xbf}
        for conventional, dual in samples.items():
            self.assertEqual(CCSDS_TO_DUAL[conventional], dual)
            self.assertEqual(CCSDS_TO_CONVENTIONAL[dual], conventional)
        for value in range(256):
            self.assertEqual(CCSDS_TO_CONVENTIONAL[CCSDS_TO_DUAL[value]], value)
        message = list(range(223))
        codeword = ccsds_rs_encode_model(message)
        self.assertEqual(codeword[:223], message)
        self.assertEqual(codeword[223:], CCSDS_KAT_PARITY)

    # verify-tier: model — the generalized decoder corrects CCSDS dual-basis symbols and
    # reports the exact number of symbol errors.
    def test_ccsds_model_correction(self):
        message = self._random_message(223, seed=81)
        codeword = ccsds_rs_encode_model(message)
        received = _corrupt(codeword, (0, 57, 222, 254), seed=81)
        self.assertEqual(ccsds_rs_decode_model(received), (message, 4, False))

    # verify-tier: model — exhaustive-ish t = 2 coverage: all strided single and double error
    # positions/magnitudes decode back to the message with the right corrected count.
    def test_model_single_double_errors_t2(self):
        n, k = 255, 251
        for m_seed in (10, 11):
            msg = self._random_message(k, seed=m_seed)
            cw  = rs_encode_model(msg, n, k)
            for p in range(0, n, 7):                       # Single errors, strided positions.
                for mag in (1, 0x80, 0xFF):
                    rx = list(cw)
                    rx[p] ^= mag
                    self.assertEqual(rs_decode_model(rx, n, k), (msg, 1, False), f"single @{p}")
            for p1 in range(0, n - 1, 29):                 # Double errors, strided pairs.
                for dp in (1, 2, 17, 101):
                    p2 = p1 + dp
                    if p2 >= n:
                        continue
                    rx = _corrupt(cw, (p1, p2), seed=p1 + dp)
                    self.assertEqual(rs_decode_model(rx, n, k), (msg, 2, False),
                        f"double @({p1},{p2})")

    # verify-tier: model — RS(255,223): every error count 1..t corrects with an exact count.
    def test_model_t16_up_to_capability(self):
        n, k, t = 255, 223, 16
        prng = random.Random(20)
        msg  = self._random_message(k, seed=20)
        cw   = rs_encode_model(msg, n, k)
        for e in range(1, t + 1):
            for trial in range(2):
                rx = _corrupt(cw, prng.sample(range(n), e), seed=100*e + trial)
                self.assertEqual(rs_decode_model(rx, n, k), (msg, e, False), f"{e} errors")

    # verify-tier: model — t + 1 errors: flagged uncorrectable, message passed through raw,
    # corrected count not corrupted (0). Seeds chosen so the patterns are detected (a t + 1
    # pattern landing within distance t of another codeword would legitimately miscorrect).
    def test_model_t16_beyond_capability(self):
        n, k, t = 255, 223, 16
        msg = self._random_message(k, seed=21)
        cw  = rs_encode_model(msg, n, k)
        for seed in range(6):
            prng = random.Random(seed)
            rx   = _corrupt(cw, prng.sample(range(n), t + 1), seed=seed)
            self.assertEqual(rs_decode_model(rx, n, k), (rx[:k], 0, True), f"seed {seed}")

    # verify-tier: model — a full-capability contiguous burst (t symbols) corrects, including
    # bursts spanning the message/parity boundary and sitting at the block tail.
    def test_model_burst_errors(self):
        n, k, t = 255, 223, 16
        msg = self._random_message(k, seed=22)
        cw  = rs_encode_model(msg, n, k)
        for start in (0, 100, k - 8, n - t):
            rx = _corrupt(cw, [start + i for i in range(t)], seed=start)
            self.assertEqual(rs_decode_model(rx, n, k), (msg, t, False), f"burst @{start}")

    # verify-tier: model — encoder RTL bit-exact vs the model over back-to-back blocks
    # (framing markers included), under randomized backpressure.
    def test_rtl_encoder_matches_model(self):
        n, k = 255, 251
        msgs = [self._random_message(k, seed=s) for s in (30, 31)]
        dut  = LiteDSPRSEncoder(n=n, k=k, with_csr=False)
        cap  = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for m in msgs for b in m], ("data",),
                throttle=0.2),
            stream_capture(dut.source, cap, 2*n, ("data", "first", "last"), ready_rate=0.7),
        ])
        expected = [b for m in msgs for b in rs_encode_model(m, n, k)]
        self.assertEqual([c["data"]  for c in cap], expected)
        self.assertEqual([c["first"] for c in cap], [1 if i % n == 0 else 0 for i in range(2*n)])
        self.assertEqual([c["last"]  for c in cap], [1 if i % n == n - 1 else 0 for i in range(2*n)])

    # verify-tier: model — default RS(255,223) encoder RTL, one full block vs the model.
    def test_rtl_encoder_t16_block(self):
        msg = self._random_message(223, seed=32)
        dut = LiteDSPRSEncoder(with_csr=False)
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for b in msg], ("data",), throttle=0.1),
            stream_capture(dut.source, cap, 255, ("data",), ready_rate=0.9),
        ])
        self.assertEqual([c["data"] for c in cap], rs_encode_model(msg, 255, 223))

    # verify-tier: trace — the dual-basis RTL encoder reproduces the independent libfec KAT.
    def test_rtl_ccsds_encoder_known_answer(self):
        message = list(range(223))
        dut = LiteDSPCCSDSRSEncoder(with_csr=False)
        cap = []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for b in message], ("data",), throttle=0.1),
            stream_capture(dut.source, cap, 255, ("data", "first", "last"), ready_rate=0.8),
        ])
        self.assertEqual([c["data"] for c in cap], message + CCSDS_KAT_PARITY)
        self.assertEqual([c["first"] for c in cap], [1] + [0]*254)
        self.assertEqual([c["last"] for c in cap], [0]*254 + [1])

    # verify-tier: model — decoder RTL over four back-to-back t = 2 blocks: clean, correctable
    # (2 errors), 3-error flagged uncorrectable, 3-error miscorrecting (bounded-distance), each
    # byte-exact vs the model including the per-block status/counters (state re-init coverage).
    def test_rtl_decoder_blocks_t2(self):
        n, k = 255, 251
        msg  = self._random_message(k, seed=1)
        cw   = rs_encode_model(msg, n, k)
        def three_errors(seed):
            prng = random.Random(seed)
            return _corrupt(cw, prng.sample(range(n), 3), seed=seed)
        codewords = [
            list(cw),                                      # Clean.
            _corrupt(cw, (10, 200), seed=40),              # 2 errors: corrected.
            three_errors(seed=1),                          # 3 errors: flagged uncorrectable.
            three_errors(seed=0),                          # 3 errors: legitimate miscorrection.
        ]
        expected, exp_status = self._expected_blocks(codewords, n, k)
        self.assertEqual(exp_status[2][1], 1)              # Vector choice: block 3 does flag.
        got, status = self._decode_blocks(codewords, n, k)
        self.assertEqual(got, expected)
        self.assertEqual(status, exp_status)

    # verify-tier: model — flagship RS(255,223) decoder RTL: one block with t = 16 random
    # errors (all corrected) then one with t + 1 = 17 (flagged, message passed through raw),
    # byte-exact vs the model including status. This runs the implementation-selected pipeline
    # at its maximum correction depth (see cycles_per_block).
    def test_rtl_decoder_t16_full(self):
        n, k, t = 255, 223, 16
        prng = random.Random(7)
        msg  = self._random_message(k, seed=7)
        cw   = rs_encode_model(msg, n, k)
        c_t  = _corrupt(cw, prng.sample(range(n), t),     seed=50)
        c_t1 = _corrupt(cw, prng.sample(range(n), t + 1), seed=51)
        expected, exp_status = self._expected_blocks([c_t, c_t1], n, k)
        self.assertEqual(exp_status, [(t, 0, 0, t), (0, 1, 1, t)])  # Vector choice: flags.
        self.assertEqual(expected, msg + c_t1[:k])
        got, status = self._decode_blocks([c_t, c_t1], n, k, architecture="pipelined")
        self.assertEqual(got, expected)
        self.assertEqual(status, exp_status)

    # verify-tier: model — minimum-t edge (t = 1, RS(255,253)): decoder RTL corrects a single
    # error and matches the model byte-exactly including status.
    def test_rtl_decoder_t1_edge(self):
        n, k = 255, 253
        msg  = self._random_message(k, seed=70)
        rx   = list(rs_encode_model(msg, n, k))
        rx[42] ^= 0x99
        expected, exp_status = self._expected_blocks([rx], n, k)
        self.assertEqual((expected, exp_status), (msg, [(1, 0, 0, 1)]))
        got, status = self._decode_blocks([rx], n, k)
        self.assertEqual(got, expected)
        self.assertEqual(status, exp_status)

    def test_rtl_decoder_pipelined_t2(self):
        n, k = 255, 251
        msg  = self._random_message(k, seed=71)
        rx   = _corrupt(rs_encode_model(msg, n, k), (13, 219), seed=71)
        expected, exp_status = self._expected_blocks([rx], n, k)
        got, status = self._decode_blocks([rx], n, k, architecture="pipelined")
        self.assertEqual(got, expected)
        self.assertEqual(status, exp_status)
        classic = LiteDSPRSDecoder(n=n, k=k, with_csr=False)
        pipelined = LiteDSPRSDecoder(n=n, k=k, with_csr=False, architecture="pipelined")
        t = (n - k)//2
        self.assertEqual(pipelined.cycles_per_block, classic.cycles_per_block + 3*n + 7*t)

    # verify-tier: model — the pipelined CCSDS wrapper corrects dual-basis channel symbols
    # byte-exactly and preserves the generic decoder status interface.
    def test_rtl_ccsds_decoder(self):
        message = self._random_message(223, seed=82)
        received = _corrupt(ccsds_rs_encode_model(message), (7, 199), seed=82)
        expected = ccsds_rs_decode_model(received)
        self.assertEqual(expected, (message, 2, False))
        dut = LiteDSPCCSDSRSDecoder(with_csr=False, architecture="pipelined")
        cap, status = [], []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for b in received], ("data",), throttle=0.1),
            stream_capture(dut.source, cap, 223, ("data",), ready_rate=0.8),
            _status_monitor(dut, status),
        ])
        self.assertEqual([c["data"] for c in cap], message)
        self.assertEqual(status, [(2, 0, 0, 2)])

    # verify-tier: model — the compact Chien schedule also applies the nonzero-fcr Forney
    # factor correctly (the implementation target above uses the pipelined schedule).
    def test_rtl_ccsds_decoder_classic(self):
        message = self._random_message(223, seed=83)
        received = _corrupt(ccsds_rs_encode_model(message), (254,), seed=83)
        dut = LiteDSPCCSDSRSDecoder(with_csr=False, architecture="classic")
        cap, status = [], []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for b in received], ("data",)),
            stream_capture(dut.source, cap, 223, ("data",)),
            _status_monitor(dut, status),
        ])
        self.assertEqual([c["data"] for c in cap], message)
        self.assertEqual(status, [(1, 0, 0, 1)])

    # verify-tier: model — RTL encoder -> RTL decoder chain (t = 2): framing interoperates and
    # the message round-trips exactly with clean status.
    def test_rtl_chain_t2(self):
        n, k = 255, 251
        msg  = self._random_message(k, seed=60)

        class Chain(LiteXModule):
            def __init__(self):
                self.enc = LiteDSPRSEncoder(n=n, k=k, with_csr=False)
                self.dec = LiteDSPRSDecoder(n=n, k=k, with_csr=False)
                self.sink, self.source = self.enc.sink, self.dec.source
                self.comb += self.enc.source.connect(self.dec.sink)

        dut = Chain()
        cap, status = [], []
        run_simulation(dut, [
            stream_driver(dut.sink, [{"data": b} for b in msg], ("data",), throttle=0.2),
            stream_capture(dut.source, cap, k, ("data",), ready_rate=0.7),
            _status_monitor(dut.dec, status),
        ])
        self.assertEqual([c["data"] for c in cap], msg)
        self.assertEqual(status, [(0, 0, 0, 0)])

    # verify-tier: model — invalid (n, k) rejected with ValueError (n fixed, even n - k, t <= 16).
    def test_invalid_params(self):
        for kwargs in ({"n": 254}, {"k": 222}, {"k": 221}, {"k": 0}, {"k": 255}):
            with self.assertRaises(ValueError):
                LiteDSPRSEncoder(with_csr=False, **kwargs)
            with self.assertRaises(ValueError):
                LiteDSPRSDecoder(with_csr=False, **kwargs)

if __name__ == "__main__":
    unittest.main()
