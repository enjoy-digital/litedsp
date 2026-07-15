#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""DQPSK modem loopback with BER curve (AN002).

Full transmit -> channel -> receive modem built from LiteDSP blocks:

    TX: PRBS bits -> Gray dibits -> DiffEncoder -> SymbolMapper -> PulseShaper (RRC, 2 sps)
    Channel (NumPy): fractional-delay all-pass + 90 deg phase rotation + AWGN at a set Eb/N0
    RX: RRC matched filter -> TimingRecovery (M&M) -> Slicer -> DiffDecoder -> bits

Differential (DQPSK) encoding makes the link immune to the 90 deg channel rotation (quadrant
ambiguity) without a carrier-phase loop: the slicer decides in the rotated constellation and the
differential decode cancels the constant offset. Carrier-*frequency* recovery is out of scope
here (the shipped LiteDSPCarrierLoop detectors target residual-carrier/BPSK; see the app note).

The BER vs Eb/N0 sweep runs on the bit-exact NumPy golden models (test/models.py) for speed,
with ideal symbol-instant sampling in place of the timing loop; ONE full RTL simulation point
(both TX and RX chains in the Migen simulator) confirms model==RTL: the TX waveforms are
asserted bit-identical, and the RTL BER (with the real M&M timing recovery) must sit close to
the model BER at that point. The curve is compared against coherently-detected DQPSK theory
and the implementation loss at BER 1e-3 is gated.

Run: python3 examples/qpsk_modem.py  (writes the BER plot to doc/app_notes/img/)
"""

import os
import sys
import math
import argparse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common               import iq_layout
from litedsp.comm.diff            import LiteDSPDifferentialEncoder, LiteDSPDifferentialDecoder
from litedsp.comm.mapper          import LiteDSPSymbolMapper
from litedsp.comm.slicer          import LiteDSPSlicer
from litedsp.comm.timing_recovery import LiteDSPTimingRecovery
from litedsp.filter.fir           import LiteDSPFIRFilterComplex
from litedsp.filter.pulse_shape   import LiteDSPPulseShaper
from litedsp.filter.design        import rrc_coefficients

from test.common import run_stream, column, np_saturated
from test.models import diff_encode_model, diff_decode_model, fir_interpolator_model, \
    fir_complex_model

# Parameters ---------------------------------------------------------------------------------------

SPS, SPAN, BETA = 2, 8, 0.35        # RRC pulse shaping: 2 samples/symbol, 8-symbol span.
SPACING         = 8000              # Constellation half-spacing (mapper/slicer LSBs).
CHAN_DELAY      = 0.35              # Channel fractional delay (samples) - exercises the M&M loop.
CHAN_PHASE      = np.pi/2           # Channel phase rotation: one quadrant (diff-resolved).
RTL_SKIP        = 500               # Symbols discarded for M&M timing acquisition (RTL point).

# Symbol index maps: phase index p (angle = 45 + 90p deg) <-> mapper/slicer symbol [q|i].
P2S = [3, 2, 0, 1]                  # Phase index -> mapper symbol.
S2P = [2, 3, 1, 0]                  # Slicer symbol -> phase index (inverse).
GRAY_ENC = {(0, 0): 0, (0, 1): 1, (1, 1): 2, (1, 0): 3}   # Bit pair -> phase increment.
GRAY_DEC = {0: (0, 0), 1: (0, 1), 2: (1, 1), 3: (1, 0)}   # Phase increment -> bit pair.

# TX / RX chains -----------------------------------------------------------------------------------

class QPSKTx(LiteXModule):
    """Gray dibits -> DiffEncoder -> SymbolMapper -> RRC PulseShaper (2 sps I/Q out)."""
    def __init__(self, data_width=16):
        self.sink = stream.Endpoint([("data", 2)])   # Phase-increment index (Gray-coded dibit).

        # # #

        self.enc    = LiteDSPDifferentialEncoder(modulus=4, with_csr=False)
        self.mapper = LiteDSPSymbolMapper(data_width=data_width, bits_per_axis=1,
            spacing=SPACING, with_csr=False)
        self.shaper = LiteDSPPulseShaper(sps=SPS, span=SPAN, beta=BETA, data_width=data_width,
            with_csr=False)
        self.source = self.shaper.source
        self.comb += [
            self.sink.connect(self.enc.sink),
            # Phase index -> constellation symbol index (build-time LUT).
            self.mapper.sink.valid.eq(self.enc.source.valid),
            self.enc.source.ready.eq(self.mapper.sink.ready),
            Case(self.enc.source.data, {p: self.mapper.sink.symbol.eq(s)
                                        for p, s in enumerate(P2S)}),
            self.mapper.source.connect(self.shaper.sink),
        ]

class QPSKRx(LiteXModule):
    """RRC matched filter -> TimingRecovery (M&M) -> Slicer -> DiffDecoder (dibits out)."""
    def __init__(self, data_width=16):
        self.sink = stream.Endpoint(iq_layout(data_width))

        # # #

        self.mf     = LiteDSPFIRFilterComplex(n_taps=SPS*SPAN + 1, data_width=data_width,
            symmetric=True, coefficients=rrc_coefficients(SPS, SPAN, BETA, data_width=data_width),
            with_csr=False)
        self.timing = LiteDSPTimingRecovery(data_width=data_width, sps=SPS, gain_mu=0.1,
            with_csr=False)
        self.slicer = LiteDSPSlicer(data_width=data_width, bits_per_axis=1, spacing=SPACING,
            with_csr=False)
        self.dec    = LiteDSPDifferentialDecoder(modulus=4, with_csr=False)
        self.source = self.dec.source
        self.comb += [
            self.sink.connect(self.mf.sink),
            self.mf.source.connect(self.timing.sink),
            self.timing.source.connect(self.slicer.sink),
            # Slicer symbol index -> phase index (build-time LUT).
            self.dec.sink.valid.eq(self.slicer.source.valid),
            self.slicer.source.ready.eq(self.dec.sink.ready),
            Case(self.slicer.source.symbol, {s: self.dec.sink.data.eq(p)
                                             for s, p in enumerate(S2P)}),
        ]

# Host-side helpers ----------------------------------------------------------------------------------

def gray_encode_bits(bits):
    """Bit pairs -> phase-increment indices (Gray, so one phase step = one bit error)."""
    return np.array([GRAY_ENC[(int(b0), int(b1))] for b0, b1 in zip(bits[0::2], bits[1::2])])

def gray_decode_increments(incs):
    """Phase-increment indices -> bit pairs."""
    out = np.empty(2*len(incs), np.int64)
    for k, d in enumerate(incs):
        out[2*k], out[2*k + 1] = GRAY_DEC[int(d)]
    return out

def tx_model(dibits, data_width=16):
    """Bit-exact NumPy model of QPSKTx (diff encode -> map -> RRC interpolate)."""
    phases = diff_encode_model(dibits, modulus=4)
    syms   = np.array([P2S[p] for p in phases])
    i = (2*(syms & 1)        - 1)*SPACING                  # Mapper: [q|i], L=2 PAM levels.
    q = (2*((syms >> 1) & 1) - 1)*SPACING
    s      = max(0, math.ceil(math.log2(SPS)))             # PulseShaper gain split (see block doc).
    coeffs = rrc_coefficients(SPS, SPAN, BETA, data_width=data_width, gain=SPS/2**s)
    ti = fir_interpolator_model(i, coeffs, SPS, data_width=data_width, shift=data_width - 1 - s)
    tq = fir_interpolator_model(q, coeffs, SPS, data_width=data_width, shift=data_width - 1 - s)
    return ti, tq

def channel(ti, tq, ebn0_db, rng, frac_delay=CHAN_DELAY, phase=CHAN_PHASE):
    """AWGN channel: fractional-delay all-pass + static phase rotation + complex noise.

    Eb/N0 accounting: Es = P*sps (energy/symbol at 2 samples/symbol), Eb = Es/2 (2 bits/symbol),
    so the per-sample complex noise variance is N0 = Eb/10^(Eb/N0 / 10).
    """
    x = ti.astype(float) + 1j*tq.astype(float)
    f = np.fft.fftfreq(len(x))
    x = np.fft.ifft(np.fft.fft(x)*np.exp(-2j*np.pi*f*frac_delay))   # All-pass fractional delay.
    x = x*np.exp(1j*phase)
    p_sig = np.mean(np.abs(x)**2)
    eb    = p_sig*SPS/2
    n0    = eb/(10**(ebn0_db/10))
    x    += rng.normal(0, np.sqrt(n0/2), len(x)) + 1j*rng.normal(0, np.sqrt(n0/2), len(x))
    return (np_saturated(np.round(x.real), 16).astype(np.int64),
            np_saturated(np.round(x.imag), 16).astype(np.int64))

def rx_model(ri, rq, n_symbols, data_width=16):
    """Model RX: matched RRC + *ideal* symbol-instant sampling (genie timing) -> dibits.

    The timing-recovery loop has no NumPy golden model; the sweep replaces it with sampling at
    the known optimum instant (TX + MF group delay = SPS*SPAN samples, fractional channel delay
    undone by the same all-pass). The RTL point runs the real M&M loop and is gated against
    this model's BER.
    """
    coeffs = rrc_coefficients(SPS, SPAN, BETA, data_width=data_width)
    mi, mq = fir_complex_model(ri, rq, coeffs, data_width=data_width)
    y = mi.astype(float) + 1j*mq.astype(float)
    f = np.fft.fftfreq(len(y))
    y = np.fft.ifft(np.fft.fft(y)*np.exp(+2j*np.pi*f*CHAN_DELAY))   # Genie: undo the frac delay.
    idx = SPS*SPAN + SPS*np.arange(n_symbols)                       # TX(8) + MF(8) group delays.
    idx = idx[idx < len(y)]
    sym = y[idx]
    ki  = (sym.real >= 0).astype(int)                               # Slicer (sign decision).
    kq  = (sym.imag >= 0).astype(int)
    phases = np.array([S2P[s] for s in (kq << 1) | ki])
    return diff_decode_model(phases, modulus=4)

def ber_count(tx_dibits, rx_dibits, skip=32, search=64):
    """Align RX phase increments to TX (offset search, both signs) and count bit errors.

    ``skip`` discards the acquisition transient. The offset may be negative: during timing
    acquisition the M&M loop can consume fewer than ``sps`` samples per symbol, so the RX
    symbol index can *lead* the TX index.
    """
    rx = np.asarray(rx_dibits)[skip:]
    best = (1.0, 0)
    for off in range(-search, search + 1):
        lo = skip + off
        if lo < 0:
            continue
        ref = np.asarray(tx_dibits)[lo:lo + len(rx)]
        m   = min(len(ref), len(rx))
        if m < 100:
            continue
        errs = np.sum(gray_decode_increments(rx[:m]) != gray_decode_increments(ref[:m]))
        ber  = errs/(2*m)
        if ber < best[0]:
            best = (ber, 2*m)
    return best   # (BER, bits compared).

def theory_ber(ebn0_db):
    """Coherently-detected, differentially-encoded Gray QPSK: Pb = 2Q(1-Q), Q = Q(sqrt(2 Eb/N0))."""
    q = 0.5*math.erfc(math.sqrt(10**(ebn0_db/10)))
    return 2*q*(1 - q)

def crossing_db(ebn0s, bers, target=1e-3):
    """Eb/N0 (dB) where the log-interpolated BER curve crosses ``target``."""
    lb = np.log10(np.maximum(bers, 1e-12))
    lt = math.log10(target)
    for k in range(len(ebn0s) - 1):
        if lb[k] >= lt >= lb[k + 1]:
            f = (lt - lb[k])/(lb[k + 1] - lb[k])
            return ebn0s[k] + f*(ebn0s[k + 1] - ebn0s[k])
    return float("nan")

# RTL point ----------------------------------------------------------------------------------------

def run_rtl_point(dibits, ebn0_db, rng):
    """Run the full TX and RX chains in the Migen simulator at one Eb/N0 point."""
    n_sym = len(dibits)
    # TX.
    tx  = QPSKTx()
    cap = run_stream(tx, [{"data": int(d)} for d in dibits], SPS*n_sym - 4*SPAN, ["data"],
        ["i", "q"], sink_throttle=0.0, source_ready_rate=1.0)
    ti, tq = column(cap, "i", 16), column(cap, "q", 16)
    # Model==RTL: the TX waveform must be bit-identical to the golden-model TX.
    mi, mq = tx_model(dibits)
    assert np.array_equal(ti, mi[:len(ti)]) and np.array_equal(tq, mq[:len(tq)]), \
        "RTL TX waveform != NumPy golden model"
    # Channel (same as the model sweep).
    ri, rq = channel(ti, tq, ebn0_db, rng)
    # RX.
    rx  = QPSKRx()
    cap = run_stream(rx, [{"i": int(i), "q": int(q)} for i, q in zip(ri, rq)],
        len(ri)//SPS - 4*SPAN, ["i", "q"], ["data"],
        sink_throttle=0.0, source_ready_rate=1.0)
    rx_dibits = column(cap, "data")
    # Skip the M&M acquisition transient (~100 symbols in the clean case, longer with noise).
    ber, bits = ber_count(dibits, rx_dibits, skip=RTL_SKIP)
    # Model RX on the same noisy waveform (genie timing), scored over a comparable window.
    mdl_ber, mdl_bits = ber_count(dibits, rx_model(ri, rq, n_sym), skip=RTL_SKIP)
    return (ber, bits), (mdl_ber, mdl_bits), (ti, tq)

# Plot ---------------------------------------------------------------------------------------------

def save_plot(plot_dir, ebn0s, bers, rtl_point, loss_db):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plots)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(plot_dir, exist_ok=True)
    ink, muted, blue, green = "#333230", "#6f6d66", "#2a78d6", "#1baf7a"
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=140)
    xs = np.linspace(min(ebn0s) - 0.5, max(ebn0s) + 0.5, 200)
    ax.semilogy(xs, [theory_ber(x) for x in xs], color=muted, lw=1.4, ls="--",
        label="DQPSK theory (coherent det., diff. decoding)")
    ax.semilogy(ebn0s, bers, "o-", color=blue, lw=1.6, ms=5, mec="white", mew=0.8,
        label="NumPy golden models (ideal timing)")
    ax.semilogy([rtl_point[0]], [rtl_point[1]], "*", color=green, ms=14, mec="white", mew=1.0,
        label=f"RTL simulation point ({rtl_point[0]:.0f} dB)")
    ax.axhline(1e-3, color="#c9c7c0", lw=0.8)
    ax.text(min(ebn0s) - 0.4, 1.25e-3, "BER 1e-3", fontsize=8, color=muted)
    ax.set_xlabel("Eb/N0 (dB)", color=ink)
    ax.set_ylabel("bit error rate", color=ink)
    ax.set_title(f"AN002 DQPSK modem BER: implementation loss {loss_db:.2f} dB @ 1e-3",
        color=ink, fontsize=11)
    ax.grid(which="both", color="#dddbd4", lw=0.6, alpha=0.6)
    ax.tick_params(colors=muted, labelsize=8)
    for s in ax.spines.values():
        s.set_color("#c9c7c0")
    ax.legend(loc="lower left", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an002_ber.png"))
    plt.close(fig)
    print(f"  plot -> {os.path.join(plot_dir, 'an002_ber.png')}")

# Demo ---------------------------------------------------------------------------------------------

def main():
    default_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "doc", "app_notes", "img")
    parser = argparse.ArgumentParser(description="AN002 DQPSK modem loopback + BER curve.")
    parser.add_argument("--plot-dir", default=default_dir, help="Output directory for PNG plots.")
    parser.add_argument("--rtl-symbols", default=int(os.environ.get("AN002_RTL_SYMBOLS", 1500)),
        type=int, help="Symbols for the RTL confirmation point (sim time ~ linear).")
    args = parser.parse_args()

    rng = np.random.RandomState(1)

    # Host sweep on the bit-exact NumPy golden models (fast; ideal symbol timing).
    ebn0s  = [4, 5, 6, 7, 8]
    n_syms = [20000, 20000, 40000, 60000, 120000]
    print("DQPSK modem (AN002): RRC 2 sps -> AWGN -> matched filter -> M&M timing -> slicer -> "
          "diff decode")
    print("  model sweep (NumPy golden models):")
    bers = []
    for ebn0, n_sym in zip(ebn0s, n_syms):
        bits   = rng.randint(0, 2, 2*n_sym)          # PRBS-equivalent random bits.
        dibits = gray_encode_bits(bits)
        ti, tq = tx_model(dibits)
        ri, rq = channel(ti, tq, ebn0, rng)
        ber, nbits = ber_count(dibits, rx_model(ri, rq, n_sym))
        bers.append(max(ber, 0.5/nbits))
        print(f"    Eb/N0 {ebn0} dB: BER {ber:.2e} ({nbits} bits, theory {theory_ber(ebn0):.2e})")

    # Implementation loss at BER 1e-3 (log-interpolated crossing vs theory crossing).
    meas_x = crossing_db(np.array(ebn0s, float), np.array(bers))
    thry_x = crossing_db(np.linspace(2, 12, 400), np.array([theory_ber(x)
        for x in np.linspace(2, 12, 400)]))
    loss   = meas_x - thry_x
    print(f"  Eb/N0 @ BER 1e-3: measured {meas_x:.2f} dB, theory {thry_x:.2f} dB, "
          f"implementation loss {loss:.2f} dB")

    # One full RTL simulation point: model==RTL confirmation (TX bit-identical, BER close).
    ebn0_rtl = 4
    n_rtl    = args.rtl_symbols
    bits     = rng.randint(0, 2, 2*n_rtl)
    dibits   = gray_encode_bits(bits)
    print(f"  RTL point: Eb/N0 {ebn0_rtl} dB, {n_rtl} symbols (Migen simulation of both chains)...")
    (rtl_ber, rtl_bits), (mdl_ber, mdl_bits), _ = run_rtl_point(dibits, ebn0_rtl, rng)
    print(f"    RTL   BER {rtl_ber:.2e} ({rtl_bits} bits)  [TX waveform == model: OK]")
    print(f"    model BER {mdl_ber:.2e} ({mdl_bits} bits) on the same noisy waveform")

    # Golden gates (tuned with margin over measured values; see doc/app_notes/an002_qpsk_modem.md).
    assert all(b1 > b2 for b1, b2 in zip(bers, bers[1:])), f"BER curve not monotonic: {bers}"
    assert loss < 1.0, f"implementation loss {loss:.2f} dB >= 1.0 dB @ BER 1e-3"
    assert rtl_ber < 3.0*max(mdl_ber, 1e-3), \
        f"RTL BER {rtl_ber:.2e} inconsistent with model BER {mdl_ber:.2e}"
    print(f"  PASS: loss {loss:.2f} dB < 1.0 dB @ BER 1e-3, RTL point consistent with model")

    save_plot(args.plot_dir, ebn0s, bers, (ebn0_rtl, rtl_ber), loss)

if __name__ == "__main__":
    main()
