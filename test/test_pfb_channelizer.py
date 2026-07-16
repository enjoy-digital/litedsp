#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""PFB channelizer (critically-sampled uniform DFT filter bank) tests.

verify-tier: model
"""

import random
import unittest

import numpy as np

from litedsp.mixing.pfb_channelizer import LiteDSPPFBChannelizer
from litedsp.filter.design          import firwin_lowpass, report

from test.common import run_stream, column
from test.models import pfb_channelizer_fft_model, pfb_channelizer_model

# Helpers ------------------------------------------------------------------------------------------

def _run_frames(dut, x, n_frames, throttle=0.0, ready_rate=1.0):
    """Feed complex ``x`` and return the first ``n_frames`` output frames as an (n, M) array."""
    M = dut.n_channels
    samples = [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]
    cap = run_stream(dut, samples, n_frames*M, ["i", "q"], ["i", "q"],
        sink_throttle=throttle, source_ready_rate=ready_rate)
    y = column(cap, "i", 16) + 1j*column(cap, "q", 16)
    return y.reshape(n_frames, M)

# Bit-Exact ----------------------------------------------------------------------------------------

class TestPFBChannelizerBitExact(unittest.TestCase):
    def test_bit_exact(self):
        for M, T in [(4, 8), (8, 4), (2, 6)]:
            coeffs = firwin_lowpass(M*T, 0.4/M)
            prng   = random.Random(M*100 + T)
            n      = M*24
            x_i    = [prng.randint(-25000, 25000) for _ in range(n)]
            x_q    = [prng.randint(-25000, 25000) for _ in range(n)]
            dut    = LiteDSPPFBChannelizer(n_channels=M, taps_per_channel=T, data_width=16,
                coefficients=coeffs, with_csr=False)
            samples = [{"i": x_i[j], "q": x_q[j]} for j in range(n)]
            cap = run_stream(dut, samples, n, ["i", "q"], ["i", "q", "first", "last"],
                sink_throttle=0.2, source_ready_rate=0.6)
            ri, rq = pfb_channelizer_model(x_i, x_q, coeffs, M)
            self.assertTrue(np.array_equal(column(cap, "i", 16), ri), f"I M={M} T={T}")
            self.assertTrue(np.array_equal(column(cap, "q", 16), rq), f"Q M={M} T={T}")
            # Framing: first on the frame's channel 0, last on channel M-1.
            pos = np.arange(n) % M
            self.assertTrue(np.array_equal(column(cap, "first"), (pos == 0).astype(int)))
            self.assertTrue(np.array_equal(column(cap, "last"),  (pos == M - 1).astype(int)))

    def test_default_prototype(self):
        # Default prototype = firwin_lowpass(M*T, 0.4/M) (unity DC gain, Q1.15).
        dut = LiteDSPPFBChannelizer(with_csr=False)
        self.assertEqual(dut.coefficients, firwin_lowpass(32, 0.1))

    # verify-tier: model — folded multiply/accumulate states retain the exact full-precision
    # branch and DFT sums under randomized stream stalls.
    def test_folded_bit_exact(self):
        for M, T in [(4, 8), (2, 6)]:
            coeffs = firwin_lowpass(M*T, 0.4/M)
            prng   = random.Random(700 + M*10 + T)
            n      = M*16
            x_i    = [prng.randint(-25000, 25000) for _ in range(n)]
            x_q    = [prng.randint(-25000, 25000) for _ in range(n)]
            dut = LiteDSPPFBChannelizer(n_channels=M, taps_per_channel=T, data_width=16,
                coefficients=coeffs, architecture="folded", with_csr=False)
            cap = run_stream(dut, [{"i": i, "q": q} for i, q in zip(x_i, x_q)], n,
                ["i", "q"], ["i", "q", "first", "last"], sink_throttle=0.2,
                source_ready_rate=0.6)
            ri, rq = pfb_channelizer_model(x_i, x_q, coeffs, M)
            np.testing.assert_array_equal(column(cap, "i", 16), ri)
            np.testing.assert_array_equal(column(cap, "q", 16), rq)
            self.assertEqual(dut.cycles_per_frame, M + M*(2*T + 1) + M*(2*M + 1))

    def test_invalid_architecture(self):
        with self.assertRaises(ValueError):
            LiteDSPPFBChannelizer(architecture="invalid", with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPPFBChannelizer(n_channels=16, architecture="classic", with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPPFBChannelizer(n_channels=8, architecture="fft", with_csr=False)

    # verify-tier: model — M>=16 uses the O(M log M) radix-2 DFT schedule with its explicit
    # per-rank twiddle rounding, natural channel order, framing, and randomized stream stalls.
    def test_fft_architecture_bit_exact(self):
        for M, T in [(16, 4), (32, 2)]:
            coeffs = firwin_lowpass(M*T, 0.4/M)
            prng   = random.Random(900 + M)
            n      = M*8
            x_i    = [prng.randint(-25000, 25000) for _ in range(n)]
            x_q    = [prng.randint(-25000, 25000) for _ in range(n)]
            dut = LiteDSPPFBChannelizer(n_channels=M, taps_per_channel=T, data_width=16,
                coefficients=coeffs, architecture="fft", with_csr=False)
            cap = run_stream(dut, [{"i": i, "q": q} for i, q in zip(x_i, x_q)], n,
                ["i", "q"], ["i", "q", "first", "last"], sink_throttle=0.2,
                source_ready_rate=0.6)
            ri, rq = pfb_channelizer_fft_model(x_i, x_q, coeffs, M)
            np.testing.assert_array_equal(column(cap, "i", 16), ri)
            np.testing.assert_array_equal(column(cap, "q", 16), rq)
            pos = np.arange(n) % M
            np.testing.assert_array_equal(column(cap, "first"), pos == 0)
            np.testing.assert_array_equal(column(cap, "last"),  pos == M - 1)
            self.assertEqual(dut.cycles_per_frame,
                M + M*(T + 1) + 3*M//2*int(np.log2(M)) + M)

# Functional ---------------------------------------------------------------------------------------

class TestPFBChannelizerFunctional(unittest.TestCase):
    # Prototype firwin_lowpass(32, 0.1) (hamming): realized stopband 44.4 dB beyond 0.15
    # (design.report at f_pass=0.1/f_stop=0.15), and the tone-to-tone leak is |H| at the
    # exact channel offsets (|H(0.25)| = -65.7 dB), so the measured isolation clears the
    # worst-case prototype stopband and is floored by the 16-bit output quantization.
    # Measured at LITEDSP_SEED=0 (deterministic, free flow): see each test; gates 3 dB under.
    M, T = 4, 8

    def _dut(self):
        return LiteDSPPFBChannelizer(n_channels=self.M, taps_per_channel=self.T,
            data_width=16, with_csr=False)

    # verify-tier: bound — tones at channel-k/-j centers land in channels k/j; the leak into
    # the other channels is bounded by the prototype stopband at the channel offsets
    # (measured 59.8 dB at LITEDSP_SEED=0 >= the 44.4 dB worst-case stopband, gated 3 dB
    # under the measurement).
    def test_two_tone_channel_isolation(self):
        M     = self.M
        k0, k1 = 1, 3
        n_frames = 96
        n = M*(n_frames + 2)
        t = np.arange(n)
        x = 9000*np.exp(1j*(2*np.pi*k0*t/M + 0.3)) + 9000*np.exp(1j*(2*np.pi*k1*t/M + 1.1))
        y = _run_frames(self._dut(), x, n_frames)[self.T:]  # Drop the filter warm-up frames.
        power = np.mean(np.abs(y)**2, axis=0)
        self.assertEqual(set(np.argsort(power)[-2:]), {k0, k1})
        others    = np.delete(power, [k0, k1])
        isolation = 10*np.log10(min(power[k0], power[k1])/others.max())
        self.assertGreaterEqual(isolation, 56.8,
            f"channel isolation {isolation:.1f} dB (LITEDSP_SEED=0 measured 59.8 dB)")

    # verify-tier: bound — an in-passband tone at k0/M + d emerges in channel k0 as a clean
    # tone at d*M of the channel rate; everything else in that channel's spectrum (decimation
    # aliases of the prototype stopband images) is bounded by the prototype design (measured
    # 88.5 dB at LITEDSP_SEED=0 — quantization floor, aliases below it — gated 3 dB under).
    def test_in_channel_alias_rejection(self):
        M, T  = self.M, self.T
        k0    = 2
        n_fft = 128
        d_out = 40/n_fft                 # Tone at bin 40 of the channel output spectrum...
        f_in  = (k0 + d_out)/M           # ...i.e. k0/M + d_out/M at the input rate (in passband).
        n_frames = n_fft + T + 4
        n = M*(n_frames + 2)
        x = 12000*np.exp(1j*2*np.pi*f_in*np.arange(n))
        y = _run_frames(self._dut(), x, n_frames)
        power = np.mean(np.abs(y[T:])**2, axis=0)
        self.assertEqual(int(np.argmax(power)), k0)
        spectrum = np.abs(np.fft.fft(y[T + 4:T + 4 + n_fft, k0]))**2
        peak = int(np.argmax(spectrum))
        self.assertEqual(peak, 40)
        rejection = 10*np.log10(spectrum[peak]/np.delete(spectrum, peak).max())
        self.assertGreaterEqual(rejection, 85.4,
            f"alias rejection {rejection:.1f} dB (LITEDSP_SEED=0 measured 88.5 dB)")

if __name__ == "__main__":
    unittest.main()
