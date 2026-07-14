#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.analysis.fft import LiteDSPFFT, bit_reverse

from test.common import run_stream, column, snr_db
from test.models import fft_bfp_model, fft_fixed_model

def run_bfp(xi, xq, N, throttle=0.0, ready=1.0, data_width=16):
    """Run a BFP FFT on the given samples, capturing i/q and the exp param field."""
    dut = LiteDSPFFT(N=N, data_width=data_width, scaling="bfp", with_csr=False)
    samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]
    return run_stream(dut, samples, len(xi) - 1, ["i", "q"], ["i", "q", "exp"],
        sink_throttle=throttle, source_ready_rate=ready)

def reorder_bitrev(frame, bits):
    """Reorder a bit-reversed FFT output frame into natural order."""
    return np.array([frame[bit_reverse(k, bits)] for k in range(len(frame))])

# Frame-hopping amplitudes: tiny -> huge exercises the one-frame-delayed decision both ways
# (a hot frame after a cold one saturates with exp 0; the following frame gets the shifts).
AMPS = [40, 30000, 8000, 100, 16000, 32000]

class TestFFTBFPBitExact(unittest.TestCase):
    def check_bit_exact(self, N, throttle=0.0, ready=1.0):
        rng  = np.random.RandomState(N)
        bits = N.bit_length() - 1
        xi   = np.concatenate([rng.randint(-a, a, N) for a in AMPS])
        xq   = np.concatenate([rng.randint(-a, a, N) for a in AMPS])
        cap  = run_bfp(xi, xq, N, throttle=throttle, ready=ready)
        i, q = column(cap, "i", 16), column(cap, "q", 16)
        e    = column(cap, "exp")
        mi, mq, mexp = fft_bfp_model(xi, xq, N)
        nfr = (len(i) - (N - 1))//N          # Complete frames captured (first at beat N-1).
        self.assertGreaterEqual(nfr, len(AMPS) - 1)
        for k in range(nfr):
            s = (N - 1) + k*N
            np.testing.assert_array_equal(i[s:s + N], mi[k*N:(k + 1)*N], f"N={N} frame {k} I")
            np.testing.assert_array_equal(q[s:s + N], mq[k*N:(k + 1)*N], f"N={N} frame {k} Q")
            self.assertTrue(np.all(e[s:s + N] == mexp[k]),
                f"N={N} frame {k}: exp {sorted(set(e[s:s + N]))} != {mexp[k]}")
            # Fully-shifted frames must reproduce "scaled"-mode arithmetic bit-exactly.
            if mexp[k] == bits:
                fi, fq = fft_fixed_model(xi[k*N:(k + 1)*N], xq[k*N:(k + 1)*N])
                np.testing.assert_array_equal(i[s:s + N], fi, f"N={N} frame {k} != scaled I")
                np.testing.assert_array_equal(q[s:s + N], fq, f"N={N} frame {k} != scaled Q")
        # The stimulus must actually exercise the adaptation (some shifted, some not).
        self.assertIn(0,    mexp[:nfr])
        self.assertIn(bits, mexp[:nfr])

    # verify-tier: model — frames + per-frame exponents bit-exact vs fft_bfp_model.
    def test_bit_exact(self):
        for N in [16, 64, 256]:
            self.check_bit_exact(N)

    # verify-tier: model — SDF/BFP state must advance only on real transfers: identical
    # frames + exponents under input gaps and output backpressure.
    def test_backpressure(self):
        self.check_bit_exact(64, throttle=0.3, ready=0.6)

    def test_invalid_scaling_rejected(self):
        with self.assertRaises(ValueError):
            LiteDSPFFT(N=64, scaling="auto", with_csr=False)

class TestFFTBFPSmallSignal(unittest.TestCase):
    # verify-tier: bound — small-signal benefit of BFP over "scaled": a -40 dBFS tone through
    # N=256 keeps ~6 more amplitude bits (settled exp 2 vs 8), measured 18.7 dB SNR gain after
    # exp renormalization at LITEDSP_SEED=0 (capture is handshake-invariant); gate 3 dB under.
    def test_small_signal_gain(self):
        N, bits, k0, nfr = 256, 8, 37, 8
        t   = np.arange(N)
        amp = 32767*10**(-40/20)             # -40 dBFS.
        fi  = np.round(amp*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq  = np.round(amp*np.sin(2*np.pi*k0*t/N)).astype(int)
        xi, xq = list(fi)*nfr, list(fq)*nfr
        ref = np.fft.fft(fi + 1j*fq)/N       # Float reference, 1/N-scaled.
        s   = (N - 1) + (nfr - 2)*N          # A settled frame (adaptation done by frame 1).
        # Scaled mode.
        dut = LiteDSPFFT(N=N, with_csr=False)
        cap = run_stream(dut, [{"i": int(a), "q": int(b)} for a, b in zip(xi, xq)],
            len(xi) - 1, ["i", "q"], ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
        out = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        snr_scaled = snr_db(ref, reorder_bitrev(out[s:s + N], bits))
        # BFP mode, renormalized by the frame exponent to the same 1/N reference scale.
        cap = run_bfp(xi, xq, N)
        out = column(cap, "i", 16) + 1j*column(cap, "q", 16)
        exp = int(column(cap, "exp")[s])
        self.assertLess(exp, bits, "BFP kept no headroom on a small signal")
        snr_bfp = snr_db(ref, reorder_bitrev(out[s:s + N], bits)*2.0**exp/N)
        gain = snr_bfp - snr_scaled
        self.assertGreaterEqual(gain, 15.7, f"BFP gain {gain:.1f} dB (scaled {snr_scaled:.1f}, "
            f"bfp {snr_bfp:.1f} dB, exp {exp})")

if __name__ == "__main__":
    unittest.main()
