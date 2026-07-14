#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSPOFDMEqualizer tests, bit-exact against ``ofdm_equalizer_model``.

Untrained passthrough (H = 1.0), reference reload + train/retrain sequencing under
randomized backpressure (bit-exact i/q/csi + first/last framing), and an end-to-end OFDM
link: QPSK bins -> IFFT -> CP add -> 2-tap multipath channel -> CP remove -> LiteDSPFFT ->
equalizer (trained on a preamble symbol) with error-free hard decisions, a gated
constellation-MSE improvement over the unequalized bins, and csi tracking |H_k|^2.

verify-tier: model + bound
"""

import random
import unittest

import numpy as np

from migen import run_simulation, passive, Signal, Mux, If

from litex.gen import LiteXModule

from litex.soc.interconnect import stream

from litedsp.common       import iq_layout
from litedsp.comm.ofdm    import LiteDSPCPRemove
from litedsp.comm.ofdm_eq import LiteDSPOFDMEqualizer
from litedsp.analysis.fft import LiteDSPFFT, bit_reverse

from test.common import run_stream, stream_driver, stream_capture, column
from test.models import ofdm_equalizer_model

# Helpers --------------------------------------------------------------------------------------------

def load_ref(eq, codes):
    """Load the 2-bit-per-bin reference RAM through the sequential write interface."""
    yield eq.ref_rst.eq(1)
    yield
    yield eq.ref_rst.eq(0)
    for c in codes:
        yield eq.ref_data.eq(int(c))
        yield eq.ref_we.eq(1)
        yield
    yield eq.ref_we.eq(0)

def pulse_train(eq):
    yield eq.train.eq(1)
    yield
    yield eq.train.eq(0)

@passive
def eq_driver(dut, frames, ref_codes=None, train_pulses=(), seed=0, throttle=0.25):
    """Load the reference RAM, then feed ``frames`` (lists of (i, q)) with random gaps.

    ``train_pulses`` is a set of ``(frame, beat)`` positions: ``train`` is pulsed right after
    beat ``beat`` of frame ``frame`` is accepted (``(f, -1)`` = before frame ``f`` starts),
    so the *next* frame boundary starts a training frame.
    """
    prng = random.Random(seed)
    if ref_codes is not None:
        yield from load_ref(dut, ref_codes)
    for f, frame in enumerate(frames):
        if (f, -1) in train_pulses:
            yield dut.sink.valid.eq(0)
            yield from pulse_train(dut)
        for b, (i, q) in enumerate(frame):
            while throttle and (prng.random() < throttle):
                yield dut.sink.valid.eq(0)
                yield
            yield dut.sink.i.eq(int(i))
            yield dut.sink.q.eq(int(q))
            yield dut.sink.valid.eq(1)
            yield
            while (yield dut.sink.ready) == 0:
                yield
            if (f, b) in train_pulses:
                yield dut.sink.valid.eq(0)
                yield from pulse_train(dut)
    yield dut.sink.valid.eq(0)

def norm_mse(z, ref):
    """Normalized constellation MSE of ``z`` vs ``ref`` after a least-squares scalar fit."""
    alpha = np.vdot(ref, z)/np.vdot(ref, ref)
    return np.mean(np.abs(z - alpha*ref)**2)/np.mean(np.abs(alpha*ref)**2)

def reorder_bitrev(frame, bits):
    """Reorder a bit-reversed FFT-order frame into natural bin order."""
    return np.array([frame[bit_reverse(k, bits)] for k in range(len(frame))])

# Model comparison -------------------------------------------------------------------------------------

class TestOFDMEqualizer(unittest.TestCase):
    # verify-tier: model — untrained block is a unit-gain passthrough (H = 1.0, csi = 1.0).
    def test_untrained_passthrough(self):
        N   = 16
        dut = LiteDSPOFDMEqualizer(fft_size=N, with_csr=False)
        rng = np.random.RandomState(0)
        xi  = rng.randint(-30000, 30000, 4*N)
        xq  = rng.randint(-30000, 30000, 4*N)
        cap = run_stream(dut, [{"i": int(i), "q": int(q)} for i, q in zip(xi, xq)],
            4*N, ["i", "q"], ["i", "q", "csi", "first", "last"])
        self.assertTrue(np.array_equal(column(cap, "i", 16), xi))
        self.assertTrue(np.array_equal(column(cap, "q", 16), xq))
        self.assertTrue(np.array_equal(column(cap, "csi"), np.full(4*N, 1 << 14)))
        self.assertEqual([k for k, c in enumerate(cap) if c["first"]], [0, N, 2*N, 3*N])
        self.assertEqual([k for k, c in enumerate(cap) if c["last"]],
                         [N - 1, 2*N - 1, 3*N - 1, 4*N - 1])

    # verify-tier: model — reference reload, train + mid-frame retrain arming, backpressure.
    def test_bit_exact_vs_model(self):
        N, F  = 32, 7
        train = [True, False, False, True, False, False, False]  # Frames consumed as preamble.
        dut   = LiteDSPOFDMEqualizer(fft_size=N, with_csr=False)
        rng   = np.random.RandomState(42)
        xi    = rng.randint(-30000, 30000, F*N)
        xq    = rng.randint(-30000, 30000, F*N)
        codes = list(rng.randint(0, 4, N))                       # Random QPSK reference.
        frames = [list(zip(xi[f*N:(f + 1)*N], xq[f*N:(f + 1)*N])) for f in range(F)]
        # Frame 0 trains (pulse before it); frame 3 trains, armed mid-frame 2 ("next full
        # frame" semantics: a pulse inside a frame applies at the next frame boundary).
        pulses = {(0, -1), (2, 5)}
        n_out  = (F - sum(train))*N
        cap    = []
        run_simulation(dut, [
            eq_driver(dut, frames, ref_codes=codes, train_pulses=pulses, throttle=0.25),
            stream_capture(dut.source, cap, n_out, ["i", "q", "csi", "first", "last"],
                ready_rate=0.7),
        ])
        ri, rq, rcsi = ofdm_equalizer_model(xi, xq, train, fft_size=N, ref=codes)
        self.assertTrue(np.array_equal(column(cap, "i", 16), ri))
        self.assertTrue(np.array_equal(column(cap, "q", 16), rq))
        self.assertTrue(np.array_equal(column(cap, "csi"), rcsi))
        self.assertEqual([k for k, c in enumerate(cap) if c["first"]],
                         [f*N for f in range(F - sum(train))])

# End-to-end OFDM link ---------------------------------------------------------------------------------

class DropWarmup(LiteXModule):
    """Test shim: drop the FFT's ``N - 1`` pipeline-fill beats so the equalizer's reset-
    counted frames align with FFT frames (same skip the PSD block applies via
    ``fft_latency``; a real receiver aligns via its frame detector, see the CP block docs)."""
    def __init__(self, n, data_width=16):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        cnt  = Signal(max=n + 1)
        done = Signal()
        self.comb += [
            done.eq(cnt == n),
            self.sink.connect(self.source, omit={"valid", "ready"}),
            self.source.valid.eq(self.sink.valid & done),
            self.sink.ready.eq(Mux(done, self.source.ready, 1)),
        ]
        self.sync += If(self.sink.valid & self.sink.ready & ~done, cnt.eq(cnt + 1))

class TestOFDMLink(unittest.TestCase):
    # verify-tier: bound — full RX chain (CP remove -> FFT -> equalizer) over a 2-tap
    # multipath channel at ~40 dB SNR: hard decisions error-free, CSI-normalized
    # constellation-MSE gain gated 3 dB under the measured 21.4 dB, csi-vs-|H_k|^2 tracking
    # gated with margin. The stimulus is RandomState-seeded (deterministic across seed
    # rotation), so the measurement is stable.
    def test_end_to_end(self):
        N, CP, bits = 64, 16, 6
        a       = 600                                            # QPSK axis amplitude per bin.
        n_data  = 6
        rng     = np.random.RandomState(1)
        signs   = rng.randint(0, 2, size=(n_data + 1, N, 2))*2 - 1   # Frame 0 = preamble.
        X       = a*(signs[..., 0] + 1j*signs[..., 1])

        # TX: IFFT (bins -> time, DFT-sum convention) + CP add, quantized.
        tx = []
        for f in range(n_data + 1):
            x = np.fft.ifft(X[f])*N
            tx.append(np.concatenate([x[-CP:], x]))
        tx = np.concatenate(tx)
        tx = (np.clip(np.round(tx.real), -32768, 32767)
              + 1j*np.clip(np.round(tx.imag), -32768, 32767))

        # Channel: 2-tap multipath (well within the CP) + mild AWGN (~40 dB SNR).
        h  = np.array([1.0, 0.3j])
        rx = np.convolve(tx, h)[:len(tx)]
        rx = rx + 45*(rng.randn(len(rx)) + 1j*rng.randn(len(rx)))
        rx = np.concatenate([rx, np.zeros(N + CP)])   # Flush symbol (drains the FFT pipeline).
        ri = np.clip(np.round(rx.real), -32768, 32767).astype(int)
        rq = np.clip(np.round(rx.imag), -32768, 32767).astype(int)

        # RX chain: CP remove -> FFT (bit-reversed frames) -> pipeline-fill drop -> equalizer.
        class RX(LiteXModule):
            def __init__(self):
                self.rem  = LiteDSPCPRemove(fft_size=N, cp_len=CP, with_csr=False)
                self.fft  = LiteDSPFFT(N=N, with_csr=False)
                self.drop = DropWarmup(self.fft.latency)
                self.eq   = LiteDSPOFDMEqualizer(fft_size=N, with_csr=False)
                self.sink, self.source = self.rem.sink, self.eq.source
                self.comb += [
                    self.rem.source.connect(self.fft.sink),
                    self.fft.source.connect(self.drop.sink),
                    self.drop.source.connect(self.eq.sink),
                ]
        dut = RX()

        # Reference RAM in FFT (bit-reversed) frame order: position p holds bin br(p)'s
        # preamble signs — the equalizer itself is bin-order-agnostic.
        codes = [int((signs[0, bit_reverse(p, bits), 0] > 0) |
                    ((signs[0, bit_reverse(p, bits), 1] > 0) << 1)) for p in range(N)]

        @passive
        def control(eq):   # Reference + train pulse, long before the first FFT output beat.
            yield from load_ref(eq, codes)
            yield from pulse_train(eq)

        cap = []
        run_simulation(dut, [
            control(dut.eq),
            stream_driver(dut.sink, [{"i": int(i), "q": int(q)} for i, q in zip(ri, rq)],
                ("i", "q"), throttle=0.1),
            stream_capture(dut.source, cap, n_data*N, ["i", "q", "csi"], ready_rate=0.8),
        ])

        S   = (column(cap, "i", 16) + 1j*column(cap, "q", 16)).reshape(n_data, N)
        csi = column(cap, "csi").astype(float).reshape(n_data, N)
        Xd  = (signs[1:, :, 0] + 1j*signs[1:, :, 1])             # Unit data constellation.
        Hk  = h[0] + h[1]*np.exp(-2j*np.pi*np.arange(N)/N)       # Channel frequency response.

        # De-reverse into natural bin order.
        S   = np.array([reorder_bitrev(S[f],   bits) for f in range(n_data)])
        csi = np.array([reorder_bitrev(csi[f], bits) for f in range(n_data)])

        # Hard decisions error-free (sign-based, invariant to the |H|^2 scaling).
        self.assertTrue(np.array_equal(np.sign(S.real), signs[1:, :, 0]))
        self.assertTrue(np.array_equal(np.sign(S.imag), signs[1:, :, 1]))

        # csi tracks |H_k|^2 (up to the common a^2/2^14 estimation scale + quantization).
        self.assertTrue(np.all(csi > 0))
        ratio = (csi/np.abs(Hk)**2).ravel()
        self.assertLess(np.std(ratio)/np.mean(ratio), 0.1)

        # Constellation-MSE improvement vs the unequalized bins (CSI-normalized, the
        # standard divider-free consumption). Unequalized = FFT of the received symbols
        # (float, same 1/N scaling) — what a slicer would see without the equalizer.
        rxc = (np.asarray(ri) + 1j*np.asarray(rq))[:(n_data + 1)*(N + CP)]
        rxc = rxc.reshape(n_data + 1, N + CP)[1:, CP:]
        Yun = np.fft.fft(rxc, axis=-1)/N                         # Unequalized data bins.
        mse_uneq = norm_mse(Yun.ravel(), Xd.ravel())
        mse_eq   = norm_mse((S/np.maximum(csi, 1)).ravel(), Xd.ravel())
        gain_db  = 10*np.log10(mse_uneq/mse_eq)
        self.assertGreaterEqual(gain_db, 18.4, f"equalization gain {gain_db:.1f} dB")

if __name__ == "__main__":
    unittest.main()
