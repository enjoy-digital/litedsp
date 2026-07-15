#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""FM stereo broadcast receiver (AN001): pilot-squaring stereo decoder.

Extends examples/fm_receiver.py to the full FM *stereo* multiplex (MPX). The composite is
generated in NumPy — mono (L+R), 19 kHz pilot, DSB-SC (L-R) on the 38 kHz subcarrier — then FM
modulated and fed to the LiteDSP chain:

    FMDemod -> [MPX] -+-> StreamFIFO -+-> LP decimator ----------------------> (L+R) -+-> IQAdd
                      |               `-> Mixer(x38 kHz) -> LP decimator ----> (L-R) -'   L | R
                      `-> BP 19 kHz -> Mixer(square) -> BP 38 kHz --^ (38 kHz carrier)

The 38 kHz subcarrier is regenerated from the pilot by *squaring* (classic analog-decoder trick:
cos^2 = (1 + cos 2x)/2), so the L-R path is phase-coherent with the transmitted subcarrier
without a PLL. Phase alignment is by construction: both band-pass FIRs are linear-phase and their
group delays sum to an integer number of 38 kHz periods (see AN001, doc/app_notes/).

Documented simplifications vs a broadcast-grade decoder (doc/app_notes/an001_fm_stereo.md):
- Elevated pilot (20% instead of 9%) for headroom in the Q1.15 squaring path.
- Narrow demo filters sized for tone program material and simulation speed.
- No de-emphasis, no pilot-presence detection (mono/stereo blend).

Run: python3 examples/fm_stereo_receiver.py  (writes plots to doc/app_notes/img/)
"""

import os
import sys
import argparse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout
from litedsp.comm.fm_demod   import LiteDSPFMDemod
from litedsp.filter.fir      import LiteDSPFIRFilter
from litedsp.filter.fir_poly import LiteDSPFIRDecimator
from litedsp.filter.design   import firwin_lowpass, firwin_bandpass
from litedsp.mixing.mixer    import LiteDSPMixer, MIXER_MODE_UP
from litedsp.stream.split    import LiteDSPSplit
from litedsp.stream.fifo     import LiteDSPStreamFIFO
from litedsp.stream.ops      import LiteDSPIQAdd

from test.common import run_stream, column, np_scaled
from test.models import fir_model

# Parameters ---------------------------------------------------------------------------------------
#
# The sample rate is a multiple of the 19 kHz pilot: fs = 8 x 19 kHz = 152 kHz, so the pilot is
# fs/8 and the 38 kHz subcarrier fs/4 (4 samples/period). The band-pass group delays
# (tau = (n_taps-1)/2) must satisfy tau_bp19 + tau_bp38 = 0 mod 4 samples so the squared,
# re-filtered pilot lands exactly in phase with the received subcarrier (AN001 derivation).

FS       = 152_000            # Sample rate at the demodulator (8 x 19 kHz).
F_PILOT  = 19_000/FS          # Pilot, fs/8.
F_SUB    = 38_000/FS          # Stereo subcarrier, fs/4.
F_TONE   = FS/128/FS          # Test tone: 1187.5 Hz (audio-band).
F_DEV    = 0.12               # Peak FM deviation (normalized, per unit MPX).
DECIM    = 4                  # Audio decimation (audio rate = 38 kHz).

N_BP19   = 33                 # 19 kHz pilot band-pass taps  (tau = 16).
N_BP38   = 25                 # 38 kHz carrier band-pass taps (tau = 12); 16 + 12 = 28 = 0 mod 4.
N_LP     = 25                 # Audio low-pass (decimator) taps, cutoff 7.6 kHz.
G_BP19   = 10.0               # Pilot band-pass gain (pilot -> near full scale before squaring).
G_BP38   = 5.0                # Carrier band-pass gain.

MPX_MONO  = 0.4               # (L+R)/2 fraction of the composite.
MPX_PILOT = 0.2               # Pilot fraction (elevated vs the 9% broadcast standard: headroom
                              # for the Q1.15 squaring path — documented in the app note).
MPX_DIFF  = 0.4               # (L-R)/2 DSB-SC fraction.

# Design-time calibration --------------------------------------------------------------------------

def carrier_amplitude(bp19, bp38, n=1024):
    """Predict the regenerated 38 kHz carrier amplitude with the bit-exact NumPy models.

    Runs a synthetic pilot (at the amplitude the FM demodulator produces) through the pilot
    band-pass -> squaring mixer -> 38 kHz band-pass path. Used to derive the L-R low-pass gain
    that matches the (L-R) audio level to the (L+R) path, so the L/R matrix cancels exactly.
    """
    a_pilot = MPX_PILOT*F_DEV*65536                        # Pilot amplitude in demod counts.
    pilot   = np.round(a_pilot*np.cos(2*np.pi*F_PILOT*np.arange(n))).astype(np.int64)
    p  = fir_model(pilot, bp19)                            # Pilot band-pass.
    sq = np_scaled(p.astype(np.int64)*p.astype(np.int64), 15, 16)  # Mixer(up): p*p >> 15.
    c  = fir_model(sq, bp38)                               # 38 kHz band-pass.
    return float(np.abs(c[len(c)//2:]).max())

# FM Stereo Receiver -------------------------------------------------------------------------------

class FMStereoReceiver(LiteXModule):
    """FMDemod -> pilot-squaring 38 kHz regeneration -> L-R demod -> matrix. L on I, R on Q."""
    def __init__(self, data_width=16):
        self.sink = stream.Endpoint(iq_layout(data_width))

        # # #

        # Coefficients (fixed at build time; runtime-reloadable variants exist, see datasheets).
        bp19 = firwin_bandpass(N_BP19, 16_000/FS, 22_000/FS, data_width=data_width, gain=G_BP19)
        bp38 = firwin_bandpass(N_BP38, 32_000/FS, 44_000/FS, data_width=data_width, gain=G_BP38)
        a_c  = carrier_amplitude(bp19, bp38)               # Regenerated-carrier amplitude.
        g_lr = 2.0*(1 << (data_width - 1))/a_c             # L-R gain: undo carrier scaling + DSB /2.
        lp_m = firwin_lowpass(N_LP, 7_600/FS, data_width=data_width, gain=1.0)
        lp_d = firwin_lowpass(N_LP, 7_600/FS, data_width=data_width, gain=g_lr)

        # Blocks.
        # -------
        self.demod     = LiteDSPFMDemod(data_width=data_width, angle_width=data_width, with_csr=False)
        self.split_mpx = LiteDSPSplit(n=2, data_width=data_width)              # MPX -> direct | pilot.
        self.fifo      = LiteDSPStreamFIFO(depth=32, data_width=data_width, with_csr=False)
        self.split_dir = LiteDSPSplit(n=2, data_width=data_width)              # direct -> mono | L-R.
        self.bp19      = LiteDSPFIRFilter(n_taps=N_BP19, data_width=data_width, symmetric=True)
        self.sqmix     = LiteDSPMixer(data_width=data_width, with_csr=False)   # pilot^2 (38 kHz + DC).
        self.bp38      = LiteDSPFIRFilter(n_taps=N_BP38, data_width=data_width, symmetric=True)
        self.lrmix     = LiteDSPMixer(data_width=data_width, with_csr=False)   # MPX x 38 kHz carrier.
        self.lp_mono   = LiteDSPFIRDecimator(n_taps=N_LP, decimation=DECIM, data_width=data_width,
            coefficients=lp_m, with_csr=False)
        self.lp_diff   = LiteDSPFIRDecimator(n_taps=N_LP, decimation=DECIM, data_width=data_width,
            coefficients=lp_d, with_csr=False)
        self.matrix    = LiteDSPIQAdd(data_width=data_width)                   # L = M+S, R = M-S.
        self.source    = self.matrix.source                                    # L on I, R on Q.

        # Fixed band-pass coefficients (LiteDSPFIRFilter exposes a coeffs array).
        self.comb += [self.bp19.coeffs[i].eq(c) for i, c in enumerate(bp19)]
        self.comb += [self.bp38.coeffs[i].eq(c) for i, c in enumerate(bp38)]
        self.comb += [self.sqmix.mode.eq(MIXER_MODE_UP), self.lrmix.mode.eq(MIXER_MODE_UP)]

        # MPX fan-out (demod output is real: carried on I, Q = 0).
        # --------------------------------------------------------
        self.comb += [
            self.sink.connect(self.demod.sink),
            self.split_mpx.sink.valid.eq(self.demod.source.valid),
            self.split_mpx.sink.i.eq(self.demod.source.data),
            self.demod.source.ready.eq(self.split_mpx.sink.ready),
            # Direct path: elastic FIFO (absorbs the pilot-path pipeline fill) -> mono | L-R demod.
            self.split_mpx.sources[0].connect(self.fifo.sink),
            self.fifo.source.connect(self.split_dir.sink),
            # Pilot path: 19 kHz band-pass (real FIR on I).
            self.bp19.sink.valid.eq(self.split_mpx.sources[1].valid),
            self.bp19.sink.data.eq(self.split_mpx.sources[1].i),
            self.split_mpx.sources[1].ready.eq(self.bp19.sink.ready),
        ]

        # 38 kHz regeneration: square the pilot, band-pass the 2nd harmonic.
        # ------------------------------------------------------------------
        # The pilot feeds both mixer inputs directly (a Split here would form a combinational
        # valid/ready cycle with the mixer's joint handshake: split valid gated by all-ready,
        # mixer per-sink ready gated by the other sink's valid).
        self.comb += [
            self.sqmix.sink_a.valid.eq(self.bp19.source.valid),
            self.sqmix.sink_a.i.eq(self.bp19.source.data),
            self.sqmix.sink_b.valid.eq(self.bp19.source.valid),
            self.sqmix.sink_b.i.eq(self.bp19.source.data),
            self.bp19.source.ready.eq(self.sqmix.sink_a.ready & self.sqmix.sink_b.ready),
            self.bp38.sink.valid.eq(self.sqmix.source.valid),
            self.bp38.sink.data.eq(self.sqmix.source.i),
            self.sqmix.source.ready.eq(self.bp38.sink.ready),
        ]

        # L-R demodulation: MPX x carrier -> low-pass decimate. Mono: low-pass decimate.
        # ------------------------------------------------------------------------------
        self.comb += [
            self.split_dir.sources[0].connect(self.lp_mono.sink),
            self.split_dir.sources[1].connect(self.lrmix.sink_a),
            self.lrmix.sink_b.valid.eq(self.bp38.source.valid),
            self.lrmix.sink_b.i.eq(self.bp38.source.data),
            self.bp38.source.ready.eq(self.lrmix.sink_b.ready),
            self.lrmix.source.connect(self.lp_diff.sink),
        ]

        # Matrix (IQAdd): L = (L+R) + (L-R) on I, R = (L+R) - (L-R) on Q.
        # ---------------------------------------------------------------
        self.comb += [
            self.matrix.sink_a.valid.eq(self.lp_mono.source.valid),
            self.matrix.sink_a.i.eq(self.lp_mono.source.i),
            self.matrix.sink_a.q.eq(self.lp_mono.source.i),
            self.lp_mono.source.ready.eq(self.matrix.sink_a.ready),
            self.matrix.sink_b.valid.eq(self.lp_diff.source.valid),
            self.matrix.sink_b.i.eq(self.lp_diff.source.i),
            self.matrix.sink_b.q.eq(-self.lp_diff.source.i),
            self.lp_diff.source.ready.eq(self.matrix.sink_b.ready),
        ]

# Stimulus -----------------------------------------------------------------------------------------

def make_mpx(n, l_audio, r_audio):
    """Compose the stereo multiplex: mono + 19 kHz pilot + (L-R) DSB-SC at 38 kHz."""
    t = np.arange(n)
    return (MPX_MONO *(l_audio + r_audio)
          + MPX_PILOT*np.cos(2*np.pi*F_PILOT*t)
          + MPX_DIFF *(l_audio - r_audio)*np.cos(2*np.pi*F_SUB*t))

def fm_modulate(mpx, amplitude=14000):
    """FM modulate the composite at baseband (complex I/Q, integer counts)."""
    x = amplitude*np.exp(1j*2*np.pi*np.cumsum(F_DEV*mpx))
    return [{"i": int(round(v.real)), "q": int(round(v.imag))} for v in x]

# Metrics ------------------------------------------------------------------------------------------

def tone_fit(x, f):
    """LS-fit a tone at normalized frequency ``f``; returns (fitted waveform, SNR dB)."""
    k   = np.arange(len(x))
    c   = np.exp(-1j*2*np.pi*f*k)
    z   = 2*np.mean(x*c)
    fit = np.abs(z)*np.cos(2*np.pi*f*k + np.angle(z))
    return fit, 10*np.log10(np.sum(fit**2)/max(np.sum((x - fit)**2), 1e-12))

# Plots --------------------------------------------------------------------------------------------

def save_plots(plot_dir, mpx_counts, l_audio, r_audio, skip, sep_db, snr_db_v):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plots)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(plot_dir, exist_ok=True)
    ink, muted, blue, green = "#333230", "#6f6d66", "#2a78d6", "#1baf7a"

    # MPX spectrum (demodulated composite, model view of the chain input).
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=140)
    w   = np.hanning(len(mpx_counts))
    spc = np.abs(np.fft.rfft(mpx_counts*w))
    spc = 20*np.log10(spc/spc.max() + 1e-9)
    fkhz = np.fft.rfftfreq(len(mpx_counts))*FS/1e3
    ax.plot(fkhz, spc, color=blue, lw=1.0)
    for f, name in [(F_TONE*FS/1e3, "L+R"), (19, "pilot"), (38, "38 kHz DSB-SC (L-R)")]:
        ax.annotate(name, (f, 2), ha="center", fontsize=8, color=ink, annotation_clip=False)
    ax.set_xlim(0, 60)
    ax.set_ylim(-90, 8)
    ax.set_xlabel("frequency (kHz)", color=ink)
    ax.set_ylabel("dB (rel. max)", color=ink)
    ax.set_title("AN001 composite MPX spectrum (FM-demodulated)", color=ink, fontsize=11)
    ax.grid(color="#dddbd4", lw=0.6, alpha=0.6)
    ax.tick_params(colors=muted, labelsize=8)
    for s in ax.spines.values():
        s.set_color("#c9c7c0")
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an001_mpx_spectrum.png"))
    plt.close(fig)

    # Decoded L/R audio.
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=140)
    k = np.arange(skip, len(l_audio))
    ax.plot(k, l_audio[skip:], color=blue,  lw=1.4, label="L (decoded)")
    ax.plot(k, r_audio[skip:], color=green, lw=1.4, label="R (decoded)")
    ax.set_xlabel("audio sample (38 kHz rate)", color=ink)
    ax.set_ylabel("amplitude (counts)", color=ink)
    ax.set_title(f"AN001 decoded audio, L-only program: separation {sep_db:.1f} dB, "
                 f"L SNR {snr_db_v:.1f} dB", color=ink, fontsize=11)
    ax.grid(color="#dddbd4", lw=0.6, alpha=0.6)
    ax.tick_params(colors=muted, labelsize=8)
    for s in ax.spines.values():
        s.set_color("#c9c7c0")
    ax.legend(loc="upper right", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an001_audio.png"))
    plt.close(fig)
    print(f"  plots -> {plot_dir}/an001_mpx_spectrum.png, {plot_dir}/an001_audio.png")

# Demo ---------------------------------------------------------------------------------------------

def main():
    default_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "doc", "app_notes", "img")
    parser = argparse.ArgumentParser(description="AN001 FM stereo broadcast receiver.")
    parser.add_argument("--plot-dir", default=default_dir, help="Output directory for PNG plots.")
    parser.add_argument("--samples",  default=int(os.environ.get("AN001_SAMPLES", 1536)), type=int,
        help="MPX samples to simulate (audio samples = samples/4).")
    args = parser.parse_args()

    # L-only program: everything on L, silence on R -> the R output measures stereo crosstalk.
    n = args.samples
    t = np.arange(n)
    l_audio = np.cos(2*np.pi*F_TONE*t)
    r_audio = np.zeros(n)
    mpx     = make_mpx(n, l_audio, r_audio)

    print(f"FM stereo receiver (AN001): fs={FS/1e3:.0f} kHz, {n} MPX samples, "
          f"pilot-squaring 38 kHz regeneration")
    dut = FMStereoReceiver(data_width=16)
    n_audio = n//DECIM - 16                          # Drop the decimator tail.
    cap = run_stream(dut, fm_modulate(mpx), n_audio, ["i", "q"], ["i", "q"],
        sink_throttle=0.0, source_ready_rate=1.0)
    l_out = column(cap, "i", 16).astype(float)       # L on I.
    r_out = column(cap, "q", 16).astype(float)       # R on Q.

    # Measurements. Skip the filter/carrier settling transient and truncate to a whole number
    # of tone periods (the single-bin tone fit is leakage-free on whole periods).
    skip   = 100
    period = int(round(1/(F_TONE*DECIM)))
    m      = ((len(l_out) - skip)//period)*period
    l_ac = l_out[skip:skip + m] - l_out[skip:skip + m].mean()
    r_ac = r_out[skip:skip + m] - r_out[skip:skip + m].mean()
    sep  = 20*np.log10(np.sqrt(np.mean(l_ac**2))/max(np.sqrt(np.mean(r_ac**2)), 1e-9))
    fit, snr = tone_fit(l_ac, F_TONE*DECIM)
    print(f"  L audio: {np.sqrt(np.mean(l_ac**2)):.0f} counts rms, "
          f"tone SNR {snr:.1f} dB (vs LS-fitted {F_TONE*FS:.1f} Hz tone)")
    print(f"  R audio: {np.sqrt(np.mean(r_ac**2)):.1f} counts rms (crosstalk)")
    print(f"  stereo separation: {sep:.1f} dB")

    # Golden gates (prototype measures ~50 dB separation / ~35 dB SNR; gated with margin).
    assert sep >= 30.0, f"stereo separation {sep:.1f} dB < 30 dB"
    assert snr >= 25.0, f"L audio SNR {snr:.1f} dB < 25 dB"
    print("  PASS: L-only program decoded with >= 30 dB separation, >= 25 dB audio SNR")

    # Model view of the chain input for the MPX spectrum plot (ideal discriminator).
    x = 14000*np.exp(1j*2*np.pi*np.cumsum(F_DEV*mpx))
    mpx_counts = np.angle(x[1:]*np.conj(x[:-1]))/(2*np.pi)*65536
    save_plots(args.plot_dir, mpx_counts, l_out, r_out, skip, sep, snr)

if __name__ == "__main__":
    main()
