#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import *

from litex.gen import *

from litedsp.analysis.fft import LiteDSPFFT, bit_reverse
from litedsp.analysis.psd import LiteDSPPSD, PSD_MODE_LINEAR, PSD_MODE_MAX

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import psd_model

class _FFTPSD(LiteXModule):
    def __init__(self, N, data_width=16, avg_log2=2):
        self.fft = LiteDSPFFT(N, data_width=data_width, with_csr=False)
        self.psd = LiteDSPPSD(N, fft_latency=self.fft.latency, data_width=data_width,
            avg_log2=avg_log2, with_csr=False)
        self.comb += self.fft.source.connect(self.psd.sink)
        self.sink   = self.fft.sink
        self.source = self.psd.source

def _set_mode(dut, mode):
    """Drive dut.mode (with_csr=False) before the first sample is accepted."""
    yield dut.mode.eq(mode)
    yield

def _pulse_clear(dut, captured, after):
    """Pulse dut.clear once `after` outputs have been captured (between spectra)."""
    while len(captured) < after:
        yield
    yield dut.clear.eq(1)
    yield
    yield dut.clear.eq(0)
    yield

class TestPSD(unittest.TestCase):
    def test_tone_spectrum(self):
        N, avg_log2 = 64, 2
        k0  = 11
        t   = np.arange(N)
        fi  = np.round(9000*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq  = np.round(9000*np.sin(2*np.pi*k0*t/N)).astype(int)
        # Enough input for the skip + accumulation of one spectrum (+margin).
        nfr     = (1 << avg_log2) + 3
        xi      = list(fi)*nfr + list(fi)  # extra margin
        xq      = list(fq)*nfr + list(fq)
        dut     = _FFTPSD(N, data_width=16, avg_log2=avg_log2)
        samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]
        cap     = run_stream(dut, samples, N, ["i", "q"], ["data"],
            sink_throttle=0.0, source_ready_rate=1.0)
        spec = column(cap, "data")           # One spectrum (natural bin order).
        self.assertEqual(len(spec), N)
        self.assertEqual(int(np.argmax(spec)), k0)
        self.assertGreater(spec[k0]/max(np.sort(spec)[-2], 1), 100.0)  # >20 dB above next bin.

    def test_backpressure(self):
        N, avg_log2 = 64, 2
        k0  = 5
        t   = np.arange(N)
        fi  = np.round(9000*np.cos(2*np.pi*k0*t/N)).astype(int)
        fq  = np.round(9000*np.sin(2*np.pi*k0*t/N)).astype(int)
        nfr = (1 << avg_log2) + 4
        xi  = list(fi)*nfr
        xq  = list(fq)*nfr
        dut = _FFTPSD(N, data_width=16, avg_log2=avg_log2)
        samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(len(xi))]
        cap = run_stream(dut, samples, N, ["i", "q"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.6)
        spec = column(cap, "data")
        self.assertEqual(int(np.argmax(spec)), k0)

    def test_modes_bit_exact(self):
        # Each combining mode against the golden model (PSD driven directly, fft_latency=0).
        N, avg_log2 = 16, 2
        rng = np.random.default_rng(42)
        n   = 2*(1 << avg_log2)*N  # Two spectra.
        xi  = rng.integers(-2**15, 2**15, n)
        xq  = rng.integers(-2**15, 2**15, n)
        for mode in range(4):
            dut     = LiteDSPPSD(N, fft_latency=0, data_width=16, avg_log2=avg_log2, with_csr=False)
            samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(n)]
            cap     = run_stream(dut, samples, 2*N, ["i", "q"], ["data"],
                extra=[_set_mode(dut, mode)], sink_throttle=0.2, source_ready_rate=0.8)
            got = column(cap, "data")
            ref = np.concatenate(psd_model(xi, xq, N, avg_log2=avg_log2, mode=mode))
            self.assertEqual(got.tolist(), ref.tolist(), f"mode {mode} mismatch vs psd_model")

    def test_max_hold_transient(self):
        # A single-frame transient survives max-hold but is smeared by linear averaging.
        N, avg_log2 = 16, 2
        p, amp = 3, 20000                # Transient at frame position p (bin bit_reverse(p)).
        rng = np.random.default_rng(7)
        n   = (1 << avg_log2)*N
        xi  = rng.integers(-400, 400, n)
        xq  = rng.integers(-400, 400, n)
        xi[N + p] = amp                  # One strong sample in frame 1 only.
        specs = {}
        for mode in (PSD_MODE_LINEAR, PSD_MODE_MAX):
            dut     = LiteDSPPSD(N, fft_latency=0, data_width=16, avg_log2=avg_log2, with_csr=False)
            samples = [{"i": int(xi[k]), "q": int(xq[k])} for k in range(n)]
            cap     = run_stream(dut, samples, N, ["i", "q"], ["data"],
                extra=[_set_mode(dut, mode)], sink_throttle=0.0, source_ready_rate=1.0)
            specs[mode] = column(cap, "data")
        k = bit_reverse(p, N.bit_length() - 1)
        self.assertEqual(int(np.argmax(specs[PSD_MODE_MAX])), k)
        self.assertGreaterEqual(specs[PSD_MODE_MAX][k], amp**2)          # Full transient power.
        self.assertGreater(specs[PSD_MODE_MAX][k], 3*specs[PSD_MODE_LINEAR][k])  # Linear smears /4.

    def test_clear_resets(self):
        # Max-hold retains a strong tone across spectra; a clear pulse discards it.
        N, avg_log2 = 16, 2
        p, amp = 5, 20000
        rng = np.random.default_rng(11)
        n   = 2*(1 << avg_log2)*N
        xi  = rng.integers(-300, 300, n)
        xq  = rng.integers(-300, 300, n)
        half = n//2
        xi[:half][p::N] = amp            # Strong tone in every frame of the first spectrum only.
        k = bit_reverse(p, N.bit_length() - 1)
        for clear, retained in [(False, True), (True, False)]:
            dut      = LiteDSPPSD(N, fft_latency=0, data_width=16, avg_log2=avg_log2, with_csr=False)
            samples  = [{"i": int(xi[j]), "q": int(xq[j])} for j in range(n)]
            captured = []
            # Manual generator set (not run_stream): the clear pulse is timed off the shared
            # capture list, right after spectrum 1 completes.
            generators = [
                stream_driver(dut.sink, samples, ["i", "q"], throttle=0.0),
                stream_capture(dut.source, captured, 2*N, ["data"], ready_rate=1.0),
                _set_mode(dut, PSD_MODE_MAX),
            ]
            if clear:
                generators.append(_pulse_clear(dut, captured, N))
            run_simulation(dut, generators)
            spec1, spec2 = column(captured[:N], "data"), column(captured[N:], "data")
            self.assertGreaterEqual(spec1[k], amp**2)  # Spectrum 1 always holds the tone.
            if retained:
                self.assertGreaterEqual(spec2[k], amp**2, "max-hold lost the tone without clear")
            else:
                self.assertLess(spec2[k], (amp**2)//10, "clear did not reset the max-hold trace")

if __name__ == "__main__":
    unittest.main()
