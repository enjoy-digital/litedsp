#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import unittest

import numpy as np

from migen import passive

from litedsp.filter.equalizer import LiteDSPLMSEqualizer, MODE_TRAINED, MODE_CMA, MODE_DD

from test.common import run_stream, column, to_signed
from test.models import equalizer_model

# Control Sequencing -------------------------------------------------------------------------------

def _set_controls(dut, controls):
    """One-shot generator: program control Signals; the writes land at the first clock edge,
    before the first sample transfer (the stream driver's first valid lands there too)."""
    def gen():
        for name, value in controls.items():
            yield getattr(dut, name).eq(int(value))
        yield
    return gen()

@passive
def _switch_at(dut, n_switch, controls):
    """Program control Signals during the transfer of accepted sample ``n_switch - 1``, so
    they take effect from accepted sample ``n_switch`` on (model arrays split at n_switch)."""
    accepted = 0
    while True:
        if (yield dut.sink.valid) and (yield dut.sink.ready):
            accepted += 1
            if accepted == n_switch:
                for name, value in controls.items():
                    yield getattr(dut, name).eq(int(value))
        yield

# Stimulus -----------------------------------------------------------------------------------------

def _qpsk_channel(N, seed=0, amp=7000, h=(1.0, 0.45)):
    """QPSK symbols (+/-amp +/-j*amp) through an ISI channel; returns (sym, i, q) int arrays."""
    rng = np.random.RandomState(seed)
    sym = ((2*rng.randint(0, 2, N) - 1) + 1j*(2*rng.randint(0, 2, N) - 1))*amp
    x   = np.convolve(sym, np.asarray(h, float))[:N]
    return sym, np.round(x.real).astype(int), np.round(x.imag).astype(int)

def _sink_samples(i, q, d_i=None, d_q=None):
    n = len(i)
    z = np.zeros(n, int)
    d_i = z if d_i is None else d_i
    d_q = z if d_q is None else d_q
    return [{"i": int(i[k]), "q": int(q[k]), "d_i": int(d_i[k]), "d_q": int(d_q[k])}
            for k in range(n)]

def _r2(amp, data_width=16):
    """CMA target for QPSK at per-axis amplitude ``amp`` (see the gateware derivation)."""
    return round(2*amp*amp / 2**(data_width - 1))

class TestLMSEqualizer(unittest.TestCase):
    # verify-tier: bound — converged MSE gated against the Wiener floor: for h = [1, 0.45,
    # -0.25, 0.1], the optimal 7-tap delay-3 linear equalizer has MMSE = 0.135*amp**2 (solve
    # R w = p with R[a,b] = Es*sum_m h[m]*h[m+a-b], p[a] = Es*h[delay-a], Es = 2*amp**2,
    # MMSE = Es - w.p). The LMS (mu_shift=20) measured at 0.99x MMSE (LITEDSP_SEED=0);
    # gate at 1.5x. Eye opening measured at 0.25*amp; gate at amp/8.
    def test_trained_isi(self):
        n_taps = 7
        delay  = n_taps//2
        amp    = 7000
        N      = 6000
        rng    = np.random.RandomState(0)
        sym    = (2*rng.randint(0, 2, N) - 1) + 1j*(2*rng.randint(0, 2, N) - 1)   # QPSK +/-1+/-1j.
        sym   *= amp
        h      = np.array([1.0, 0.45, -0.25, 0.1])                                # ISI channel.
        x      = np.convolve(sym, h)[:N]
        d      = np.concatenate([np.zeros(delay, complex), sym])[:N]              # Desired = delayed symbols.

        dut = LiteDSPLMSEqualizer(n_taps=n_taps, data_width=16, wfrac=14, mu_shift=20, with_csr=False)
        samples = [{"i": int(round(x[k].real)), "q": int(round(x[k].imag)),
                    "d_i": int(round(d[k].real)), "d_q": int(round(d[k].imag))} for k in range(N)]
        cap = run_stream(dut, samples, N, ["i", "q", "d_i", "d_q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0)
        y = to_signed(column(cap, "i"), 16) + 1j*to_signed(column(cap, "q"), 16)

        # After convergence: decisions on the equalized output match the (delayed) symbols.
        tail = slice(N - 1000, len(y))
        dec  = np.sign(y[tail].real) + 1j*np.sign(y[tail].imag)
        ref  = np.sign(d[tail].real) + 1j*np.sign(d[tail].imag)
        ser  = np.mean(dec != ref)
        self.assertLess(ser, 0.02)

        # Equalization actually helped: residual error well below the raw ISI distortion
        # (measured ratio ~32x at LITEDSP_SEED=0; gate at 16x).
        err_eq  = np.mean(np.abs(y[tail] - d[tail])**2)
        err_raw = np.mean(np.abs(x[N-1000:] - d[N-1000:])**2)
        self.assertLess(err_eq, err_raw/16)

        # Converged MSE sits at the Wiener floor (derivation above the test).
        self.assertLess(err_eq, 1.5*0.135*amp**2)

        # Eye opening: every post-convergence decision clears the slicer threshold by amp/8.
        eye = min(np.min(np.abs(y[tail].real)), np.min(np.abs(y[tail].imag)))
        self.assertGreater(eye, amp/8)

    # Bit-exact short trajectories vs test.models.equalizer_model, one per mode, under
    # randomized backpressure (the update is xfer-gated, so the per-accepted-sample sequence
    # is handshake-invariant). Aggressive step sizes so the weights move (and, for CMA, the
    # pre-mu error saturation is exercised) within the short run.
    def _run_bit_exact(self, samples, model_kwargs, controls, n_taps=5, mu_shift=12,
        cma_egain=0, extra=None, architecture="classic", adaptation_delay=1,
        update_pipeline=False, stream_kwargs=None):
        N   = len(samples)
        dut = LiteDSPLMSEqualizer(n_taps=n_taps, data_width=16, wfrac=14, mu_shift=mu_shift,
            cma_egain=cma_egain, architecture=architecture, update_pipeline=update_pipeline,
            with_csr=False)
        gens = [_set_controls(dut, controls)] + (extra or [])
        cap  = run_stream(dut, samples, N, ["i", "q", "d_i", "d_q"], ["i", "q"],
            extra=gens, **(stream_kwargs or {}))
        y_i  = to_signed(column(cap, "i"), 16)
        y_q  = to_signed(column(cap, "q"), 16)
        m_i, m_q = equalizer_model(
            [s["i"] for s in samples], [s["q"] for s in samples],
            [s["d_i"] for s in samples], [s["d_q"] for s in samples],
            n_taps=n_taps, data_width=16, wfrac=14, mu_shift=mu_shift, cma_egain=cma_egain,
            adaptation_delay=adaptation_delay, **model_kwargs)
        np.testing.assert_array_equal(y_i, m_i)
        np.testing.assert_array_equal(y_q, m_q)

    def test_trained_bit_exact(self):
        N = 400
        sym, i, q = _qpsk_channel(N, seed=2)
        d = np.concatenate([np.zeros(2, complex), sym])[:N]
        self._run_bit_exact(_sink_samples(i, q, np.round(d.real).astype(int),
            np.round(d.imag).astype(int)), {"mode": MODE_TRAINED}, {})

    def test_cma_bit_exact(self):
        # Large amplitude against a small (mismatched) R2 with a big error gain: |dm| is huge,
        # so the CMA error saturates on most samples — the stability-critical path is covered
        # bit-exactly (the trajectory itself may be wild; only exactness matters here).
        N = 400
        sym, i, q = _qpsk_channel(N, seed=3, amp=18000)
        r2 = _r2(6000)
        self._run_bit_exact(_sink_samples(i, q), {"mode": MODE_CMA, "cma_r2": r2},
            {"mode": MODE_CMA, "cma_r2": r2}, mu_shift=16, cma_egain=8)
        # And a well-scaled operating point (no permanent saturation).
        sym, i, q = _qpsk_channel(N, seed=4)
        r2 = _r2(7000)
        self._run_bit_exact(_sink_samples(i, q), {"mode": MODE_CMA, "cma_r2": r2},
            {"mode": MODE_CMA, "cma_r2": r2}, mu_shift=16, cma_egain=6)

    def test_dd_bit_exact(self):
        N = 400
        sym, i, q = _qpsk_channel(N, seed=5)
        self._run_bit_exact(_sink_samples(i, q), {"mode": MODE_DD, "dd_level": 7000},
            {"mode": MODE_DD, "dd_level": 7000})

    # verify-tier: model — the full-rate adaptation pipeline delays updates by exactly eight
    # accepted samples in trained, CMA and decision-directed modes.
    def test_pipelined_modes_bit_exact(self):
        N = 240
        sym, i, q = _qpsk_channel(N, seed=21)
        d = np.concatenate([np.zeros(2, complex), sym])[:N]
        common = {"architecture": "pipelined", "adaptation_delay": 8}
        self.assertEqual(LiteDSPLMSEqualizer(architecture="pipelined", with_csr=False).latency, 3)
        self._run_bit_exact(_sink_samples(i, q, np.round(d.real).astype(int),
            np.round(d.imag).astype(int)), {"mode": MODE_TRAINED}, {}, **common)
        r2 = _r2(7000)
        self._run_bit_exact(_sink_samples(i, q), {"mode": MODE_CMA, "cma_r2": r2},
            {"mode": MODE_CMA, "cma_r2": r2}, mu_shift=16, cma_egain=6, **common)
        self._run_bit_exact(_sink_samples(i, q), {"mode": MODE_DD, "dd_level": 7000},
            {"mode": MODE_DD, "dd_level": 7000}, **common)

    def test_pipelined_update_modes_bit_exact(self):
        N = 240
        sym, i, q = _qpsk_channel(N, seed=22)
        d = np.concatenate([np.zeros(2, complex), sym])[:N]
        common = {"n_taps": 7, "architecture": "pipelined", "update_pipeline": True,
                  "adaptation_delay": 9,
                  "stream_kwargs": {"sink_seed": 2, "source_seed": 3}}
        dut = LiteDSPLMSEqualizer(architecture="pipelined", update_pipeline=True,
            with_csr=False)
        self.assertEqual(dut.latency, 3)
        self.assertEqual(dut.adaptation_delay, 9)
        self._run_bit_exact(_sink_samples(i, q, np.round(d.real).astype(int),
            np.round(d.imag).astype(int)), {"mode": MODE_TRAINED}, {}, **common)
        r2 = _r2(7000)
        self._run_bit_exact(_sink_samples(i, q), {"mode": MODE_CMA, "cma_r2": r2},
            {"mode": MODE_CMA, "cma_r2": r2}, mu_shift=16, cma_egain=6, **common)
        self._run_bit_exact(_sink_samples(i, q), {"mode": MODE_DD, "dd_level": 7000},
            {"mode": MODE_DD, "dd_level": 7000}, **common)

    def test_pipelined_update_trained_convergence(self):
        # The extra recurrence boundary changes the adaptation trajectory, so pin its quality
        # independently of the short RTL/model identity vectors above.
        n_taps, delay, amp, N = 7, 3, 7000, 6000
        rng = np.random.RandomState(23)
        sym = ((2*rng.randint(0, 2, N) - 1) + 1j*(2*rng.randint(0, 2, N) - 1))*amp
        h   = np.array([1.0, 0.45, -0.25, 0.1])
        x   = np.convolve(sym, h)[:N]
        d   = np.concatenate([np.zeros(delay, complex), sym])[:N]
        y_i, y_q = equalizer_model(np.round(x.real).astype(int), np.round(x.imag).astype(int),
            np.round(d.real).astype(int), np.round(d.imag).astype(int), n_taps=n_taps,
            mu_shift=20, adaptation_delay=9)
        y = y_i + 1j*y_q
        tail = slice(N - 1000, N)
        dec = np.sign(y[tail].real) + 1j*np.sign(y[tail].imag)
        ref = np.sign(d[tail].real) + 1j*np.sign(d[tail].imag)
        self.assertLess(np.mean(dec != ref), 0.02)
        self.assertLess(np.mean(np.abs(y[tail] - d[tail])**2),
            np.mean(np.abs(x[N-1000:] - d[N-1000:])**2)/16)

    def test_pipelined_dd_queue_collision(self):
        # This fixed valid/ready pattern fills two pending-error slots, then consumes and pushes
        # on the same edge. It guards the conflict-free queue move independently of the rotating
        # nightly LITEDSP_SEED campaign.
        N = 240
        _, i, q = _qpsk_channel(N, seed=21)
        self._run_bit_exact(_sink_samples(i, q), {"mode": MODE_DD, "dd_level": 7000},
            {"mode": MODE_DD, "dd_level": 7000}, architecture="pipelined",
            adaptation_delay=8, stream_kwargs={"sink_seed": 2, "source_seed": 3})

    def test_invalid_architecture(self):
        with self.assertRaises(ValueError):
            LiteDSPLMSEqualizer(architecture="invalid", with_csr=False)
        with self.assertRaises(ValueError):
            LiteDSPLMSEqualizer(update_pipeline=True, with_csr=False)

    # verify-tier: bound — blind CMA on a 2-tap ISI channel, no training data at all: the
    # constant-modulus dispersion (|y|^2 - R2)^2 must fall and the eye must open. Measured at
    # LITEDSP_SEED=0 (model-identical, gates seed-independent): head/tail dispersion ratio
    # 9.3x (gate at 3x), tail eye 5345 = 0.76*amp (gate at amp/2).
    def test_cma_blind_convergence(self):
        N, amp = 8000, 7000
        sym, i, q = _qpsk_channel(N, amp=amp)
        r2  = _r2(amp)
        dut = LiteDSPLMSEqualizer(n_taps=7, data_width=16, wfrac=14, mu_shift=20, cma_egain=6,
            with_csr=False)
        cap = run_stream(dut, _sink_samples(i, q), N, ["i", "q", "d_i", "d_q"], ["i", "q"],
            sink_throttle=0.0, source_ready_rate=1.0,
            extra=[_set_controls(dut, {"mode": MODE_CMA, "cma_r2": r2})])
        y = to_signed(column(cap, "i"), 16) + 1j*to_signed(column(cap, "q"), 16)

        disp = (np.abs(y)**2 - 2*amp*amp)**2               # Constant-modulus dispersion.
        self.assertLess(np.mean(disp[-1000:]), np.mean(disp[:500])/3)
        eye = min(np.min(np.abs(y[-1000:].real)), np.min(np.abs(y[-1000:].imag)))
        self.assertGreater(eye, amp/2)

    # verify-tier: bound — blind CMA acquisition, then runtime switch to decision-directed:
    # the decision MSE must improve (DD tracks the actual constellation points instead of just
    # the modulus) while staying locked. Measured at LITEDSP_SEED=0: DD tail decision-MSE
    # improves 10.2x over the late-CMA segment (gate at 2x), DD eye 6303 (gate at amp/2).
    # The whole trajectory is also compared bit-exactly against the model with the per-sample
    # mode split, pinning the switch alignment.
    def test_cma_to_dd_switchover(self):
        N1, N2, amp = 6000, 3000, 7000
        N = N1 + N2
        sym, i, q = _qpsk_channel(N, seed=1, amp=amp)
        r2  = _r2(amp)
        dut = LiteDSPLMSEqualizer(n_taps=7, data_width=16, wfrac=14, mu_shift=20, cma_egain=6,
            with_csr=False)
        cap = run_stream(dut, _sink_samples(i, q), N, ["i", "q", "d_i", "d_q"], ["i", "q"],
            extra=[_set_controls(dut, {"mode": MODE_CMA, "cma_r2": r2, "dd_level": amp}),
                   _switch_at(dut, N1, {"mode": MODE_DD})])
        y = to_signed(column(cap, "i"), 16) + 1j*to_signed(column(cap, "q"), 16)

        # Bit-exact against the model with the same mode schedule.
        mode = np.concatenate([np.full(N1, MODE_CMA), np.full(N2, MODE_DD)])
        m_i, m_q = equalizer_model(i, q, n_taps=7, mu_shift=20, cma_egain=6,
            mode=mode, cma_r2=r2, dd_level=amp)
        np.testing.assert_array_equal(y.real.astype(np.int64), m_i)
        np.testing.assert_array_equal(y.imag.astype(np.int64), m_q)

        # DD refines the blind solution: decision MSE improves, eye stays open.
        dec = (np.sign(y.real) + 1j*np.sign(y.imag))*amp   # Nearest QPSK point.
        mse = np.abs(y - dec)**2
        cma_mse = np.mean(mse[N1-1000:N1])
        dd_mse  = np.mean(mse[-1000:])
        self.assertLess(dd_mse, cma_mse/2)
        eye = min(np.min(np.abs(y[-1000:].real)), np.min(np.abs(y[-1000:].imag)))
        self.assertGreater(eye, amp/2)

    # verify-tier: bound — freeze (train=0): weights hold while filtering continues. After
    # training, the reference is removed (d=0) *and* train is dropped; a still-adapting
    # equalizer would slew its weights toward 0 on e = -y (measured tail SER 0.64 in the
    # model when left adapting) while the frozen one keeps equalizing (tail SER 0.000,
    # gate at 0.02). The trajectory is also bit-exact against the model with the per-sample
    # train split, which pins the weights as static.
    def test_freeze(self):
        N1, N2, amp = 4000, 2000, 7000
        N     = N1 + N2
        delay = 3
        sym, i, q = _qpsk_channel(N, seed=6, amp=amp)
        d = np.concatenate([np.zeros(delay, complex), sym])[:N]
        d[N1:] = 0                                         # Reference removed after freeze.
        d_i = np.round(d.real).astype(int)
        d_q = np.round(d.imag).astype(int)
        dut = LiteDSPLMSEqualizer(n_taps=7, data_width=16, wfrac=14, mu_shift=20, with_csr=False)
        cap = run_stream(dut, _sink_samples(i, q, d_i, d_q), N, ["i", "q", "d_i", "d_q"],
            ["i", "q"], extra=[_switch_at(dut, N1, {"train": 0})])
        y = to_signed(column(cap, "i"), 16) + 1j*to_signed(column(cap, "q"), 16)

        # Bit-exact against the model with the same train schedule (weights provably static).
        train = np.concatenate([np.ones(N1, int), np.zeros(N2, int)])
        m_i, m_q = equalizer_model(i, q, d_i, d_q, n_taps=7, mu_shift=20, train=train)
        np.testing.assert_array_equal(y.real.astype(np.int64), m_i)
        np.testing.assert_array_equal(y.imag.astype(np.int64), m_q)

        # Output is still filtered with the converged weights: decisions keep matching the
        # (delayed) symbols long after adaptation stopped.
        ref  = np.concatenate([np.zeros(delay, complex), sym])[:N]
        tail = slice(N - 1000, N)
        ser  = np.mean((np.sign(y[tail].real) != np.sign(ref[tail].real)) |
                       (np.sign(y[tail].imag) != np.sign(ref[tail].imag)))
        self.assertLess(ser, 0.02)

if __name__ == "__main__":
    unittest.main()
