#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import random
import unittest

import numpy as np

from litedsp.filter.fir import (LiteDSPFIRFilter, LiteDSPFIRFilterComplex,
    LiteDSPFIRCoefficientsPort)

from test.common import run_stream, column, snr_db
from test.models import fir_model, fir_complex_model

def design_lowpass(n_taps, cutoff=0.25, data_width=16):
    """Hamming-windowed-sinc low-pass, normalized to unity DC gain, quantized to Q1.(N-1)."""
    m = np.arange(n_taps) - (n_taps - 1)/2
    h = np.sinc(2*cutoff*m)*np.hamming(n_taps)
    h = h/h.sum()
    scale = (1 << (data_width - 1)) - 1
    return [int(round(c*scale)) for c in h]

class TestFIR(unittest.TestCase):
    def run_real_fir(self, coeffs, x, n_taps, data_width=16, symmetric=False,
        architecture="classic"):
        dut = LiteDSPFIRFilter(n_taps=n_taps, data_width=data_width, symmetric=symmetric,
            architecture=architecture)
        for t in range(n_taps):
            dut.coeffs[t].reset = coeffs[t]  # Signed; do not mask (would corrupt negatives).
        samples  = [{"data": int(v)} for v in x]
        captured = run_stream(dut, samples, len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        return column(captured, "data", data_width)

    def test_direct_bit_exact(self):
        n_taps = 33
        coeffs = design_lowpass(n_taps)
        prng   = random.Random(1)
        x      = [prng.randint(-30000, 30000) for _ in range(256)]
        got    = self.run_real_fir(coeffs, x, n_taps, symmetric=False)
        ref    = fir_model(x, coeffs)[:len(got)]
        self.assertTrue(np.array_equal(got, ref))

    def test_symmetric_matches_direct(self):
        # Symmetric folding must be bit-identical to the direct form for symmetric taps.
        for n_taps in [32, 33]:
            coeffs = design_lowpass(n_taps)
            prng   = random.Random(2)
            x      = [prng.randint(-30000, 30000) for _ in range(256)]
            got    = self.run_real_fir(coeffs, x, n_taps, symmetric=True)
            ref    = fir_model(x, coeffs)[:len(got)]
            self.assertTrue(np.array_equal(got, ref), f"symmetric mismatch n_taps={n_taps}")

    def test_pipelined_tree_bit_exact(self):
        # Odd/even and direct/folded trees exercise every registered reduction shape. The
        # initiation rate remains one sample per clock; only the declared latency changes.
        for n_taps, symmetric in [(32, False), (33, False), (32, True), (33, True)]:
            coeffs = design_lowpass(n_taps)
            prng   = random.Random(30 + n_taps + symmetric)
            x      = [prng.randint(-30000, 30000) for _ in range(192)]
            got    = self.run_real_fir(coeffs, x, n_taps, symmetric=symmetric,
                architecture="pipelined")
            ref    = fir_model(x, coeffs)[:len(got)]
            self.assertTrue(np.array_equal(got, ref),
                f"pipelined mismatch n_taps={n_taps} symmetric={symmetric}")
            n_products = (n_taps + 1)//2 if symmetric else n_taps
            dut = LiteDSPFIRFilter(n_taps=n_taps, symmetric=symmetric,
                architecture="pipelined")
            self.assertEqual(dut.latency, 3 + (n_products - 1).bit_length())

    def test_complex_bit_exact(self):
        n_taps = 17
        coeffs = design_lowpass(n_taps)
        for architecture in ("classic", "pipelined"):
            dut = LiteDSPFIRFilterComplex(n_taps=n_taps, data_width=16,
                coefficients=coeffs, with_csr=False, architecture=architecture)
            prng   = random.Random(3)
            x_i    = [prng.randint(-30000, 30000) for _ in range(200)]
            x_q    = [prng.randint(-30000, 30000) for _ in range(200)]
            samples = [{"i": x_i[k], "q": x_q[k]} for k in range(200)]
            captured = run_stream(dut, samples, 200, ["i", "q"], ["i", "q"],
                sink_throttle=0.2, source_ready_rate=0.7)
            gi = column(captured, "i", 16)
            gq = column(captured, "q", 16)
            ri, rq = fir_complex_model(x_i, x_q, coeffs)
            self.assertTrue(np.array_equal(gi, ri[:len(gi)]), architecture)
            self.assertTrue(np.array_equal(gq, rq[:len(gq)]), architecture)

    def test_lowpass_response(self):
        # In-band tone passes, out-of-band tone is strongly attenuated.
        n_taps = 63
        coeffs = design_lowpass(n_taps, cutoff=0.15)
        n      = 1024
        def tone(bin_k, amp=20000):
            t = np.arange(n)
            return (amp*np.cos(2*np.pi*bin_k*t/n)).astype(int)
        pass_in  = self.run_real_fir(coeffs, tone(40),  n_taps)   # f ~ 0.039 fs (in band).
        stop_in  = self.run_real_fir(coeffs, tone(300), n_taps)   # f ~ 0.29 fs (out of band).
        # Steady-state RMS (skip filter fill transient).
        pass_rms = np.sqrt(np.mean(pass_in[n_taps:].astype(float)**2))
        stop_rms = np.sqrt(np.mean(stop_in[n_taps:].astype(float)**2))
        self.assertGreater(pass_rms, 10000)               # In-band largely preserved.
        self.assertLess(stop_rms, pass_rms/50)            # Out-of-band >34 dB down.

if __name__ == "__main__":
    unittest.main()


class TestFIRMac(unittest.TestCase):
    """The serial MAC architecture must be sample-exact vs the classic architecture."""

    def run_mac(self, coeffs, x, n_taps, n_macs, data_width=16):
        dut = LiteDSPFIRFilter(n_taps=n_taps, data_width=data_width, architecture="mac",
            n_macs=n_macs)
        for t in range(n_taps):
            dut.coeffs[t].reset = coeffs[t]
        samples  = [{"data": int(v)} for v in x]
        captured = run_stream(dut, samples, len(x), ["data"], ["data"],
            sink_throttle=0.2, source_ready_rate=0.7)
        return column(captured, "data", data_width)

    def test_mac_bit_exact(self):
        n_taps = 63
        coeffs = design_lowpass(n_taps)
        prng   = random.Random(5)
        x      = [prng.randint(-30000, 30000) for _ in range(200)]
        got    = self.run_mac(coeffs, x, n_taps, n_macs=4)
        ref    = fir_model(x, coeffs)[:len(got)]
        self.assertTrue(len(got) >= 150)
        self.assertTrue(np.array_equal(got, ref))

    def test_mac_odd_units_bit_exact(self):
        # A non-dividing MAC count (63 taps / 5 units) exercises the zero-padded chunk tail.
        n_taps = 63
        coeffs = design_lowpass(n_taps)
        prng   = random.Random(6)
        x      = [prng.randint(-30000, 30000) for _ in range(160)]
        got    = self.run_mac(coeffs, x, n_taps, n_macs=5)
        ref    = fir_model(x, coeffs)[:len(got)]
        self.assertTrue(np.array_equal(got, ref))

    def test_mac_complex_bit_exact(self):
        n_taps = 33
        coeffs = design_lowpass(n_taps)
        dut = LiteDSPFIRFilterComplex(n_taps=n_taps, coefficients=coeffs, with_csr=False,
            architecture="mac", n_macs=4)
        prng = random.Random(7)
        xi = [prng.randint(-20000, 20000) for _ in range(128)]
        xq = [prng.randint(-20000, 20000) for _ in range(128)]
        samples = [{"i": xi[k], "q": xq[k]} for k in range(len(xi))]
        cap = run_stream(dut, samples, len(xi), ["i", "q"], ["i", "q"],
            sink_throttle=0.2, source_ready_rate=0.7)
        gi, gq = column(cap, "i", 16), column(cap, "q", 16)
        ri, rq = fir_model(xi, coeffs)[:len(gi)], fir_model(xq, coeffs)[:len(gq)]
        self.assertTrue(np.array_equal(gi, ri))
        self.assertTrue(np.array_equal(gq, rq))


class TestFIRCoefficientsPort(unittest.TestCase):
    def test_autoincrement_load(self):
        from migen import run_simulation
        n_taps = 8
        taps   = [100*(i + 1)*(1 if i % 2 == 0 else -1) for i in range(n_taps)]
        dut    = LiteDSPFIRCoefficientsPort(n_taps=n_taps, data_width=16)
        got    = []

        def gen():
            yield dut._index.storage.eq(2)     # Load starting at index 2.
            yield dut._index.re.eq(1)
            yield
            yield dut._index.re.eq(0)
            for t in taps[2:]:
                yield dut._value.storage.eq(t & 0xffff)
                yield dut._value.re.eq(1)
                yield
            yield dut._value.re.eq(0)
            yield
            for i in range(n_taps):
                got.append((yield dut.values[i]))

        run_simulation(dut, [gen()])
        self.assertEqual(got[0], (1 << 15) - 1)     # Unit-impulse reset retained.
        self.assertEqual(got[1], 0)
        self.assertEqual(got[2:], taps[2:])
