#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from litedsp.analysis.fft import FFT, bit_reverse

from test.common import run_stream, column, snr_db
from test.models import fft_model

def reorder_bitrev(frame, bits):
    """Reorder a bit-reversed FFT output frame into natural order."""
    return np.array([frame[bit_reverse(k, bits)] for k in range(len(frame))])

class TestFFT(unittest.TestCase):
    def run_fft(self, xi, xq, N, data_width=16, throttle=0.0, ready=1.0):
        dut = FFT(N=N, data_width=data_width, with_csr=False)
        samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]
        captured = run_stream(dut, samples, len(xi) - 1, ["i", "q"], ["i", "q"],
            sink_throttle=throttle, source_ready_rate=ready)
        return column(captured, "i", data_width) + 1j*column(captured, "q", data_width)

    def best_frame_snr(self, out, ref, N, bits):
        best = -np.inf
        for off in range(len(out) - N):
            nat = reorder_bitrev(out[off:off + N], bits)
            best = max(best, snr_db(ref, nat))
        return best

    def test_random_snr(self):
        for N in [16, 64, 256]:
            bits = N.bit_length() - 1
            rng  = np.random.RandomState(N)
            fi   = rng.randint(-8000, 8000, N)
            fq   = rng.randint(-8000, 8000, N)
            nfr  = 6
            out  = self.run_fft(list(fi)*nfr, list(fq)*nfr, N)
            ref  = fft_model(fi, fq)
            snr  = self.best_frame_snr(out, ref, N, bits)
            self.assertGreater(snr, 45.0, f"N={N} SNR={snr:.1f} dB")

    def test_tone_bin(self):
        # A pure complex tone at bin k0 must concentrate energy in bin k0.
        N    = 64
        bits = 6
        k0   = 9
        t    = np.arange(N)
        fi   = np.round(10000*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq   = np.round(10000*np.sin(2*np.pi*k0*t/N)).astype(int)
        out  = self.run_fft(list(fi)*6, list(fq)*6, N)
        ref  = fft_model(fi, fq)
        # Find aligned frame, check peak bin.
        best_off, best = 0, -np.inf
        for off in range(len(out) - N):
            nat = reorder_bitrev(out[off:off + N], bits)
            s   = snr_db(ref, nat)
            if s > best:
                best, best_off = s, off
        nat  = reorder_bitrev(out[best_off:best_off + N], bits)
        mag  = np.abs(nat)
        self.assertEqual(int(np.argmax(mag)), k0)
        self.assertGreater(mag[k0]/np.sort(mag)[-2], 50.0)  # >34 dB above next bin.

    def test_backpressure(self):
        # The SDF state must advance only on real transfers: result must survive stalls.
        N    = 64
        bits = 6
        rng  = np.random.RandomState(7)
        fi   = rng.randint(-8000, 8000, N)
        fq   = rng.randint(-8000, 8000, N)
        out  = self.run_fft(list(fi)*8, list(fq)*8, N, throttle=0.3, ready=0.6)
        ref  = fft_model(fi, fq)
        snr  = self.best_frame_snr(out, ref, N, bits)
        self.assertGreater(snr, 45.0, f"backpressure SNR={snr:.1f} dB")

if __name__ == "__main__":
    unittest.main()
