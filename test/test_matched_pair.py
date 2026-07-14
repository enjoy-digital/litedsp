#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""TX-RRC -> RX-RRC matched-pair signoff: composite raised-cosine ISI and EVM.

``LiteDSPPulseShaper`` (TX, interpolating RRC) and ``rrc_coefficients`` are tested individually
elsewhere; here the *pair* is validated as a system, the way it is deployed: TX shaper followed
by an RX matched filter (``LiteDSPFIRFilterComplex`` loaded with the same unit-energy RRC taps).
The composite response must be a raised cosine (Nyquist: near-zero ISI at symbol-spaced
instants), the eye must be open at the optimal sampling instant, and the EVM of random QPSK
symbols through the full fixed-point chain must sit at the RRC truncation floor.
"""

import math
import random
import unittest

import numpy as np

from litex.gen import LiteXModule

from litedsp.filter.pulse_shape import LiteDSPPulseShaper
from litedsp.filter.fir         import LiteDSPFIRFilterComplex
from litedsp.filter.design      import rrc_coefficients

from test.common import run_stream, column

# Matched Pair -------------------------------------------------------------------------------------

class MatchedPair(LiteXModule):
    """TX RRC pulse shaper -> RX RRC matched filter (composite raised cosine).

    The RX filter uses the same unit-energy RRC taps as the TX shaper (a matched filter) with
    ``shift = (data_width-1) + log2(sps)``: the TX shaper has an effective gain of ``sps``
    (interpolation-loss compensation), so the extra ``log2(sps)`` renormalizes the composite
    gain to ~1.0 — a symbol of amplitude A comes out at amplitude A.
    """
    def __init__(self, sps, span, beta, data_width=16):
        n_taps  = sps*span + 1
        self.tx = LiteDSPPulseShaper(sps=sps, span=span, beta=beta, data_width=data_width,
            with_csr=False)
        self.rx = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=data_width, symmetric=True,
            coefficients=rrc_coefficients(sps, span, beta, data_width=data_width),
            shift=(data_width - 1) + int(math.log2(sps)), with_csr=False)
        self.sink, self.source = self.tx.sink, self.rx.source
        self.comb += self.tx.source.connect(self.rx.sink)

# Test ---------------------------------------------------------------------------------------------

class TestMatchedPair(unittest.TestCase):
    def _run_pair(self, sps, span, beta, symbols):
        """Run complex ``symbols`` through the TX->RX pair; returns the complex output stream."""
        dut  = MatchedPair(sps, span, beta)
        syms = list(symbols) + [0]*(2*span + 4)    # Tail zeros flush both filter memories.
        cap  = run_stream(dut, [{"i": int(s.real), "q": int(s.imag)} for s in syms],
            (len(syms) - 1)*sps, ["i", "q"], ["i", "q"],
            sink_throttle=0.1, source_ready_rate=0.8)
        return column(cap, "i", 16) + 1j*column(cap, "q", 16)

    @staticmethod
    def _align(y, ref, sps):
        """Optimal sampling instant: offset into ``y`` maximizing correlation with ``ref``."""
        best_off, best_c = 0, -1.0
        for off in range(len(y) - sps*(len(ref) - 1)):
            c = abs(np.vdot(ref, y[off::sps][:len(ref)]))
            if c > best_c:
                best_off, best_c = off, c
        return best_off

    # verify-tier: bound — composite (TX RRC -> RX RRC) single-pulse ISI: worst symbol-spaced
    # sidelobe / center of the measured raised-cosine response. The floor is RRC *truncation*
    # (finite span), not Q1.15 quantization: float taps give -39.81 dB (sps=4, span=8,
    # beta=0.35) and -41.99 dB (sps=2, span=10, beta=0.25); the fixed-point chain measures
    # -39.79 dB / -41.94 dB (quantization contribution < 0.1 dB). Gates 3 dB under measured.
    def _isi(self, sps, span, beta, min_db):
        amp  = 8000
        syms = [0]*span + [amp*(1 + 1j)] + [0]*span    # Isolated symbol -> composite RC pulse.
        y    = self._run_pair(sps, span, beta, syms)
        for ch, name in ((y.real, "I"), (y.imag, "Q")):  # Same taps on I and Q; check both.
            c      = int(np.argmax(np.abs(ch)))
            center = abs(ch[c])
            self.assertGreater(center, 0.9*amp)        # Composite gain ~1.0 (matched shift).
            lobes  = np.abs(ch[c % sps::sps])
            lobes  = np.delete(lobes, c//sps)          # Symbol-spaced samples, center excluded.
            isi_db = 20*np.log10(lobes.max()/center)
            self.assertLess(isi_db, min_db,
                f"{name} composite ISI {isi_db:.2f} dB >= {min_db} dB")

    # verify-tier: bound — eye opening and EVM of random QPSK through the pair, sampled at the
    # optimal instant. Fixed data seed (handshake randomization still rotates via LITEDSP_SEED;
    # the datapath is handshake-invariant, so the measurement is deterministic). Measured over
    # 400 symbols: sps=4/span=8/beta=0.35 worst deviation -29.24 dB, EVM -36.47 dB;
    # sps=2/span=10/beta=0.25 worst deviation -31.09 dB, EVM -38.43 dB. The worst deviation is
    # upper-bounded by the composite sum-|ISI| (-29.1 dB / -30.1 dB analytic — the 400-symbol
    # pattern nearly reaches it). Gates 3 dB under the measurements.
    def _eye_evm(self, sps, span, beta, amp, dev_max_db, evm_max_db):
        prng = random.Random(0x600D)
        ref  = np.array([complex(prng.choice((-1, 1)), prng.choice((-1, 1)))
                         for _ in range(400)])
        y    = self._run_pair(sps, span, beta, amp*ref)
        off  = self._align(y, ref, sps)
        err  = y[off::sps][:len(ref)]/amp - ref
        dev_db = 20*np.log10(max(np.abs(err.real).max(), np.abs(err.imag).max()))
        evm_db = 20*np.log10(np.sqrt(np.mean(np.abs(err)**2)/np.mean(np.abs(ref)**2)))
        self.assertLess(dev_db, dev_max_db,
            f"eye worst deviation {dev_db:.2f} dB >= {dev_max_db} dB")
        self.assertLess(evm_db, evm_max_db, f"EVM {evm_db:.2f} dB >= {evm_max_db} dB")

    def test_isi_sps4_span8(self):
        self._isi(sps=4, span=8, beta=0.35, min_db=-36.5)

    def test_isi_sps2_span10(self):
        self._isi(sps=2, span=10, beta=0.25, min_db=-38.5)

    def test_eye_evm_sps4_span8(self):
        self._eye_evm(sps=4, span=8, beta=0.35, amp=8000, dev_max_db=-26.0, evm_max_db=-33.0)

    def test_eye_evm_sps2_span10(self):
        self._eye_evm(sps=2, span=10, beta=0.25, amp=10000, dev_max_db=-28.0, evm_max_db=-35.0)

if __name__ == "__main__":
    unittest.main()
