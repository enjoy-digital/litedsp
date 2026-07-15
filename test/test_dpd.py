#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""DPD actuator + host-side adaptation tests.

The actuator is verified bit-exactly against ``test.models.dpd_model`` (identity default,
random LUT contents under backpressure, CSR-programmed LUTs via a mock bus); the host-side
indirect-learning adaptation (:mod:`litedsp.software.dpd`) is verified closed-loop, entirely
in Python, against a synthetic Saleh + memory PA: fit on the bit-exact actuator model, apply,
and gate the measured ACLR/EVM improvement.
"""

import random
import unittest

import numpy as np

from migen import run_simulation, passive

from litedsp.level.dpd        import LiteDSPDPD
from litedsp.software.dpd     import DPDAdapter, simulate_pa
from litedsp.software.drivers import DPDDriver

from test.common import SEED, run_stream, column, stream_capture
from test.models import dpd_model, dpd_identity_luts

# Helpers ------------------------------------------------------------------------------------------

def random_luts(prng, n_taps=3, lut_depth=64, coeff_frac=14):
    """Full-range random LUT contents (signed Q2.coeff_frac per component)."""
    lo, hi = -(1 << (coeff_frac + 1)), (1 << (coeff_frac + 1)) - 1
    return [(np.array([prng.randint(lo, hi) for _ in range(lut_depth)], np.int64),
             np.array([prng.randint(lo, hi) for _ in range(lut_depth)], np.int64))
            for _ in range(n_taps)]

def lut_words(luts, coeff_frac=14):
    """Per-tap packed {Q, I} LUT words as the hardware write bus expects them."""
    width = coeff_frac + 2
    mask  = (1 << width) - 1
    return [[((int(gq) & mask) << width) | (int(gi) & mask) for gi, gq in zip(*lut)]
            for lut in luts]

@passive
def lut_and_stream_driver(dut, luts, samples, coeff_frac=14, seed=None, throttle=0.25):
    """Load LUTs through the sequential write bus, then feed samples (with random gaps)."""
    prng = random.Random(SEED if seed is None else seed)
    for tap, words in enumerate(lut_words(luts, coeff_frac)):
        yield dut.lut_tap.eq(tap)
        yield dut.lut_rst.eq(1)
        yield
        yield dut.lut_rst.eq(0)
        for w in words:
            yield dut.lut_data.eq(w)
            yield dut.lut_we.eq(1)
            yield
        yield dut.lut_we.eq(0)
    for (i, q) in samples:
        while throttle and (prng.random() < throttle):
            yield dut.sink.valid.eq(0)
            yield
        yield dut.sink.i.eq(int(i))
        yield dut.sink.q.eq(int(q))
        yield dut.sink.valid.eq(1)
        yield
        while (yield dut.sink.ready) == 0:
            yield
    yield dut.sink.valid.eq(0)

# Stimulus / metrics for the closed-loop test --------------------------------------------------------

def bandlimited(n, cutoff=0.08, rms=5000, seed=0):
    """Band-limited complex noise (windowed-sinc filtered), RMS in LSBs, peaks <= 3.2x RMS."""
    rng = np.random.default_rng(seed)
    k = np.arange(129)
    h = np.sinc(2*cutoff*(k - 64))*(0.54 - 0.46*np.cos(2*np.pi*k/128))
    h /= h.sum()
    w = rng.standard_normal(n + 256) + 1j*rng.standard_normal(n + 256)
    x = np.convolve(w, h, mode="same")[128:128 + n]
    x *= rms/np.sqrt(np.mean(np.abs(x)**2))
    r = np.abs(x)
    x = np.where(r > 3.2*rms, x*3.2*rms/r, x)                 # PAPR clip (headroom for DPD gain).
    return np.round(x.real).astype(np.int64), np.round(x.imag).astype(np.int64)

def aclr_db(x, f_ch=0.10, f_adj=(0.13, 0.30), nfft=1024):
    """Channel (|f| <= f_ch) to adjacent-band (f_adj) power ratio, Hann periodogram average."""
    x = np.asarray(x, np.complex128)
    n = (len(x)//nfft)*nfft
    p = np.mean(np.abs(np.fft.fft(x[:n].reshape(-1, nfft)*np.hanning(nfft), axis=1))**2, axis=0)
    f = np.fft.fftfreq(nfft)
    return 10*np.log10(p[np.abs(f) <= f_ch].sum() /
                       p[(np.abs(f) >= f_adj[0]) & (np.abs(f) <= f_adj[1])].sum())

def evm_db(reference, measured):
    return 10*np.log10(np.sum(np.abs(measured - reference)**2) /
                       np.sum(np.abs(reference)**2))

# Tests ----------------------------------------------------------------------------------------------

class TestDPD(unittest.TestCase):
    # verify-tier: model — reset LUTs are the identity (tap 0 = 1.0 + 0j, memory taps = 0)
    # and the single rescale is exact for x * 1.0, so the default block is a bit-exact
    # passthrough.
    def test_identity_by_default(self):
        dut  = LiteDSPDPD(with_csr=False)
        prng = random.Random(SEED + 40)
        data = [{"i": prng.randint(-32768, 32767), "q": prng.randint(-32768, 32767)}
                for _ in range(200)]
        cap = run_stream(dut, data, len(data), ["i", "q"], ["i", "q"])
        for f in ("i", "q"):
            np.testing.assert_array_equal(column(cap, f, 16), [d[f] for d in data])

    # verify-tier: model — full-range random LUT contents (loaded through the sequential
    # write bus) under input gaps + output backpressure must match test.models.dpd_model
    # bit-exactly; full-scale samples exercise the top-bin index clamp.
    def test_bit_exact_random_luts_backpressure(self):
        prng = random.Random(SEED + 41)
        luts = random_luts(prng)
        dut  = LiteDSPDPD(with_csr=False)
        x    = [(prng.randint(-32768, 32767), prng.randint(-32768, 32767)) for _ in range(300)]
        cap  = []
        run_simulation(dut, [
            lut_and_stream_driver(dut, luts, x, seed=SEED + 42),
            stream_capture(dut.source, cap, len(x), ["i", "q"], seed=SEED + 43, ready_rate=0.7),
        ])
        mi, mq = dpd_model([i for i, _ in x], [q for _, q in x], luts)
        np.testing.assert_array_equal(column(cap, "i", 16), mi)
        np.testing.assert_array_equal(column(cap, "q", 16), mq)

    # verify-tier: bound — closed-loop linearization, entirely in Python: synthetic PA
    # (Saleh TWT AM/AM + AM/PM, classic parameters alpha_a/beta_a = 1.9638/0.9945,
    # alpha_p/beta_p = 2.5293/2.8168, plus a mild (1.0, 0.08, 0.02) memory FIR —
    # Hammerstein), band-limited noise drive at ~0.15 FS RMS. The DPDAdapter fits by
    # indirect learning on the bit-exact actuator model (two capture/fit iterations, the
    # standard workflow) and the measured ACLR/EVM improvement is gated. Typical numbers:
    # ACLR +15 dB (34 -> 50 dB), EVM +25 dB; gates at +10 dB leave >= 5 dB margin.
    def test_closed_loop_linearization(self):
        n = 16384
        xi, xq = bandlimited(n, seed=0)                       # Deterministic stimulus.
        x = (xi + 1j*xq)/32768.0                              # Float domain for the PA.
        y = simulate_pa(x)
        aclr0 = aclr_db(y)
        adapter = DPDAdapter(n_taps=3, lut_depth=64, coeff_frac=14)
        ui, uq = xi, xq                                       # PA drive (actuator output).
        for _ in range(2):                                    # Iterative indirect learning.
            adapter.fit(ui + 1j*uq, y*32768.0)
            di, dq = dpd_model(xi, xq, adapter.luts)          # Apply on the bit-exact model.
            ai, aq = adapter.apply(xi, xq)                    # Host prediction must agree.
            np.testing.assert_array_equal(di, ai)
            np.testing.assert_array_equal(dq, aq)
            y = simulate_pa((di + 1j*dq)/32768.0)
            ui, uq = di, dq
        aclr1 = aclr_db(y)
        self.assertGreaterEqual(aclr1 - aclr0, 10.0,
            f"ACLR improvement {aclr1 - aclr0:.1f} dB < 10 dB ({aclr0:.1f} -> {aclr1:.1f} dB)")
        # EVM vs the linear reference gain*x must improve by >= 10 dB too.
        ref = adapter.gain*(xi + 1j*xq)
        evm0 = evm_db(ref, simulate_pa(x)*32768.0)
        evm1 = evm_db(ref, y*32768.0)
        self.assertGreaterEqual(evm0 - evm1, 10.0,
            f"EVM improvement {evm0 - evm1:.1f} dB < 10 dB ({evm0:.1f} -> {evm1:.1f} dB)")

    # verify-tier: model — RTL spot-check with adaptation-fitted LUTs: the DPDDriver
    # programs a mock bus, the recorded register writes are replayed onto the CSR-side LUT
    # write bus, and the streamed RTL output must equal dpd_model with the same LUTs.
    def test_rtl_with_fitted_luts_via_mock_bus(self):
        # Small fit (speed): same PA, shorter record.
        xi, xq = bandlimited(4096, seed=3)
        y = simulate_pa((xi + 1j*xq)/32768.0)
        adapter = DPDAdapter()
        adapter.fit(xi + 1j*xq, y*32768.0)
        # Program through the driver onto a recording mock bus.
        log = []

        class _Reg:
            def __init__(self, name):
                self.name, self.value = name, 0
            def read(self):
                return self.value
            def write(self, value):
                self.value = value
                log.append((self.name, value))

        class _Regs:
            pass

        class _Bus:
            regs = _Regs()

        for r in DPDDriver.regs:
            setattr(_Bus.regs, f"dpd_{r}", _Reg(r))
        adapter.program(DPDDriver(_Bus(), "dpd"))

        # Replay the recorded CSR writes onto the LUT write bus, then stream.
        prng = random.Random(SEED + 44)
        x = [(prng.randint(-32768, 32767), prng.randint(-32768, 32767)) for _ in range(200)]
        dut = LiteDSPDPD(with_csr=False)

        @passive
        def replay_and_stream(dut):
            for name, value in log:
                if name == "lut_tap":
                    yield dut.lut_tap.eq(value)
                elif name == "lut_reset":
                    yield dut.lut_rst.eq(1)
                    yield
                    yield dut.lut_rst.eq(0)
                    continue
                elif name == "lut":
                    yield dut.lut_data.eq(value)
                    yield dut.lut_we.eq(1)
                    yield
                    yield dut.lut_we.eq(0)
                    continue
                yield
            for (i, q) in x:
                yield dut.sink.i.eq(i)
                yield dut.sink.q.eq(q)
                yield dut.sink.valid.eq(1)
                yield
                while (yield dut.sink.ready) == 0:
                    yield
            yield dut.sink.valid.eq(0)

        cap = []
        run_simulation(dut, [replay_and_stream(dut),
            stream_capture(dut.source, cap, len(x), ["i", "q"], seed=SEED + 45, ready_rate=0.8)])
        mi, mq = dpd_model([i for i, _ in x], [q for _, q in x], adapter.luts)
        np.testing.assert_array_equal(column(cap, "i", 16), mi)
        np.testing.assert_array_equal(column(cap, "q", 16), mq)

    # verify-tier: model — non-default geometry (2 taps, 32 bins, Q2.12) stays bit-exact.
    def test_bit_exact_alt_geometry(self):
        prng = random.Random(SEED + 46)
        luts = random_luts(prng, n_taps=2, lut_depth=32, coeff_frac=12)
        dut  = LiteDSPDPD(n_taps=2, lut_depth=32, coeff_frac=12, with_csr=False)
        x    = [(prng.randint(-32768, 32767), prng.randint(-32768, 32767)) for _ in range(200)]
        cap  = []
        run_simulation(dut, [
            lut_and_stream_driver(dut, luts, x, coeff_frac=12, seed=SEED + 47),
            stream_capture(dut.source, cap, len(x), ["i", "q"], seed=SEED + 48, ready_rate=0.6),
        ])
        mi, mq = dpd_model([i for i, _ in x], [q for _, q in x], luts, coeff_frac=12)
        np.testing.assert_array_equal(column(cap, "i", 16), mi)
        np.testing.assert_array_equal(column(cap, "q", 16), mq)

if __name__ == "__main__":
    unittest.main()
