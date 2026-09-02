#!/usr/bin/env python3
#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Stereo audio processor (AN010): I2S in -> EQ -> compressor -> limiter -> volume -> dither -> I2S out.

The RTL chain of a small digital audio product, exercised in three simulation passes that share
one set of blocks (Migen simulates these serial engines at a few hundred cycles per second, so
each pass only carries the frames its gate needs):

  1. tone chain      AudioEQ -> Volume -> PeakMeter -> Dither(16-bit, 2nd-order noise shaping)
       A  five tones at -20 dBFS: EQ magnitude vs the RBJ design
       D  250 Hz at -6 dBFS (EQ bypassed): THD+N of the 16-bit noise-shaped output (20 Hz .. 10 kHz)
  2. dynamics chain  Compressor -> Limiter -> PeakMeter
       B  1 kHz at -30 / -20 / -10 / -3 dBFS through the compressor (peak detector, instant
          attack): static curve vs the design and vs the bit-exact model
       C  1 kHz at 0 dBFS through the limiter (-1 dBFS ceiling, 32-frame lookahead): output peak
  3. I2S transport   stimulus -> I2S TX (master, 24-bit) ==pins==> I2S RX (slave) -> Dither(16-bit,
                     rounding only) -> I2S TX (master, 16-bit) ==pins==> I2S RX (slave) -> NumPy:
                     the received words equal the rounded stimulus

All streams are channel-tagged TDM frames (`tdm_layout(24, 2)`, L = R here). The dynamics
segments are separated by silence gaps that let control changes propagate and locate the
segments at the output. The nominal sample rate for the filter and time-constant design is
48 kHz.

Run: python3 examples/audio_processor.py [--plot-dir DIR]
"""

import os
import sys
import math
import argparse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litedsp.audio.i2s      import LiteDSPI2SReceiver, LiteDSPI2STransmitter
from litedsp.audio.eq       import LiteDSPAudioEQ
from litedsp.audio.dynamics import LiteDSPCompressor
from litedsp.audio.level    import LiteDSPVolume
from litedsp.audio.meter    import LiteDSPPeakMeter
from litedsp.audio.dither   import LiteDSPDither
from litedsp.audio.design   import rbj_biquad, time_constant_coeff, db_to_linear
from litedsp.filter.design  import biquad_sos_quantize
from litedsp.audio.dynamics import PRESET_VALUES

from char.metrics import thd_n_db
from test.models  import compressor_model

# Parameters ---------------------------------------------------------------------------------------

FS       = 48000                       # Nominal sample rate (design of filters / time constants).
DW       = 24
FS24     = (1 << 23) - 1
BCLK_DIV = 4                           # I2S pass: BCLK = sys/4.
SLOT     = 24

EQ_BANDS  = [("lowshelf", 80.0, 6.0, 0.7071), ("peaking", 1000.0, -4.0, 1.5), ("highshelf", 8000.0, 3.0, 0.7071)]
EQ_TONES  = [250.0, 500.0, 1000.0, 3000.0, 8000.0]                # Multiples of the analysis bin.
EQ_TOL_DB = 0.3

COMP_THRESHOLD_DB, COMP_RATIO   = -20.0, 4.0                       # Preset values.
COMP_RELEASE_MS                 = 10.0                             # Instant attack: peak hold-ish.
COMP_LEVELS_DB                  = [-30.0, -20.0, -10.0, -3.0]
COMP_TOL_DB, MODEL_TOL_DB       = 1.0, 0.1

LIMITER_CEILING_DB, LIMITER_TOL_DB = -1.0, 0.5
THDN_TONE_HZ, THDN_MAX_DB          = 250.0, -80.0                # In the 20 Hz .. 10 kHz band.
THDN_BAND_HZ                       = (20.0, 10000.0)

ANALYSIS = 192                                                     # 4 ms: 250 Hz bins.
EQ_SETTLE, THDN_SETTLE = 160, 32                                   # 80 Hz shelf tau ~ 96 frames.
SEG_STEP = 128                                                     # Compressor level step.
GAP      = 48
I2S_FRAMES = 48

# Design -------------------------------------------------------------------------------------------

def eq_rows():
    return [rbj_biquad(kind, f0, gain_db, q, sample_rate=FS) for kind, f0, gain_db, q in EQ_BANDS]

def sos_db(rows, freqs):
    """Magnitude (dB) of float ``[b0, b1, b2, a0, a1, a2]`` rows at ``freqs`` (Hz)."""
    z = np.exp(-2j*np.pi*np.asarray(freqs, float)/FS)
    h = np.ones_like(z)
    for b0, b1, b2, a0, a1, a2 in rows:
        h = h*(b0 + b1*z + b2*z*z)/(a0 + a1*z + a2*z*z)
    return 20*np.log10(np.abs(h))

def compressor_curve(level_db):
    """Static curve of the peak-detector compressor: output level of a sine at ``level_db``."""
    return level_db - max(0.0, level_db - COMP_THRESHOLD_DB)*(1 - 1/COMP_RATIO)

# Hardware -----------------------------------------------------------------------------------------

class ToneChain(LiteXModule):
    """AudioEQ -> Volume -> PeakMeter -> Dither (24-bit in, 16-bit MSB-aligned out)."""
    def __init__(self):
        sections, _ = biquad_sos_quantize(eq_rows(), 32, 28)
        self.eq     = LiteDSPAudioEQ(data_width=DW, n_bands=3, n_channels=2, sections=sections, with_csr=False)
        self.volume = LiteDSPVolume(data_width=DW, n_channels=2, with_csr=False)
        self.meter  = LiteDSPPeakMeter(data_width=DW, n_channels=2, with_csr=False)
        self.dither = LiteDSPDither(data_width=DW, out_width=16, n_channels=2, shaping="ef2", with_csr=False)
        self.comb += [
            self.eq.source.connect(self.volume.sink),
            self.volume.source.connect(self.meter.sink),
            self.meter.source.connect(self.dither.sink),
        ]
        self.sink, self.source = self.eq.sink, self.dither.source

class DynamicsChain(LiteXModule):
    """Compressor -> Limiter -> PeakMeter."""
    def __init__(self):
        self.comp    = LiteDSPCompressor(data_width=DW, n_channels=2, preset="compressor", with_csr=False)
        self.limiter = LiteDSPCompressor(data_width=DW, n_channels=2, lookahead=32, preset="limiter", with_csr=False)
        self.meter   = LiteDSPPeakMeter(data_width=DW, n_channels=2, with_csr=False)
        self.comb += [
            self.comp.source.connect(self.limiter.sink),
            self.limiter.source.connect(self.meter.sink),
        ]
        self.sink, self.source = self.comp.sink, self.meter.source

class I2SLoop(LiteXModule):
    """I2S TX (24-bit master) => RX (slave) -> Dither (rounding) -> I2S TX (16-bit master) => RX."""
    def __init__(self):
        self.adc_tx = LiteDSPI2STransmitter(data_width=DW, sample_width=24, slot_width=SLOT, n_channels=2,
            fmt="i2s", mode="master", bclk_div=BCLK_DIV, with_csr=False)
        self.rx     = LiteDSPI2SReceiver(data_width=DW, sample_width=24, slot_width=SLOT, n_channels=2,
            fmt="i2s", mode="slave", with_csr=False)
        self.dither = LiteDSPDither(data_width=DW, out_width=16, n_channels=2, shaping="none", with_csr=False)
        self.tx     = LiteDSPI2STransmitter(data_width=DW, sample_width=16, slot_width=SLOT, n_channels=2,
            fmt="i2s", mode="master", bclk_div=BCLK_DIV, with_csr=False)
        self.dac_rx = LiteDSPI2SReceiver(data_width=DW, sample_width=16, slot_width=SLOT, n_channels=2,
            fmt="i2s", mode="slave", with_csr=False)
        self.comb += [
            self.rx.bclk.eq(self.adc_tx.bclk), self.rx.lrck.eq(self.adc_tx.lrck), self.rx.sdata.eq(self.adc_tx.sdata),
            self.rx.source.connect(self.dither.sink),
            self.dither.source.connect(self.tx.sink),
            self.dac_rx.bclk.eq(self.tx.bclk), self.dac_rx.lrck.eq(self.tx.lrck), self.dac_rx.sdata.eq(self.tx.sdata),
        ]
        self.sink, self.source = self.adc_tx.sink, self.dac_rx.source

# Stimulus -----------------------------------------------------------------------------------------

def tone(freqs_db, n, start=0):
    t = np.arange(start, start + n)/FS
    x = sum(db_to_linear(db)*np.sin(2*np.pi*f*t) for f, db in freqs_db)
    return np.clip(np.round(x*FS24), -FS24, FS24).astype(np.int64)

def build(segments, tail=GAP):
    """``segments`` = list of (samples, controls): frames with a silence gap before each segment
    and the control schedule {frame: controls} applied mid-gap (the pipeline carries silence)."""
    x, sched = [], {}
    for seg, controls in segments:
        if controls:
            sched[len(x) + GAP//2] = controls
        x.extend([0]*GAP)
        x.extend(np.asarray(seg).tolist())
    x.extend([0]*tail)
    return x, sched

# Simulation ---------------------------------------------------------------------------------------

def simulate(top, frames, sched, setup=(), tail_cycles=None, status=None):
    """Push ``frames`` (L = R) into ``top.sink`` at full rate, capture ``top.source`` (channel 0)
    and read the ``status`` signals (``{name: Signal}``) at the end."""
    out, seen = [], {}
    @passive
    def capture():
        yield top.source.ready.eq(1)
        while True:
            if (yield top.source.valid):
                out.append(((yield top.source.data), (yield top.source.channel)))
            yield
    def resolve(name):
        obj = top
        for part in name.split("."):
            obj = getattr(obj, part)
        return obj
    def driver():
        for name, value in setup:
            yield resolve(name).eq(value)
        for k, v in enumerate(frames):
            for name, value in sched.get(k, []):
                yield resolve(name).eq(value)
            for c in range(2):
                yield top.sink.data.eq(int(v))
                yield top.sink.channel.eq(c)
                yield top.sink.valid.eq(1)
                yield
                while (yield top.sink.ready) == 0:
                    yield
            yield top.sink.valid.eq(0)
        for _ in range(tail_cycles or 4*GAP):
            yield
        for name, sig in (status or {}).items():
            seen[name] = (yield sig)
    run_simulation(top, [driver(), capture()])
    y = np.array([d for d, c in out if c == 0], np.int64)
    y = np.where(y >= 1 << 23, y - (1 << 24), y)
    return y, seen

def segments(y, min_len=48, silent=4*256, min_gap=16):
    """Runs of frames (>= min_len) between the silence gaps (>= min_gap consecutive frames below
    ``silent``; a tone's zero crossings are shorter than that)."""
    y = np.asarray(y)
    quiet = np.abs(y) < silent
    gap, start = np.zeros(len(y), bool), None
    for k, q in enumerate(np.concatenate([quiet, [False]])):
        if q and start is None:
            start = k
        elif not q and start is not None:
            if k - start >= min_gap:
                gap[start:k] = True
            start = None
    segs, start = [], None
    for k, a in enumerate(np.concatenate([~gap, [False]])):
        if a and start is None:
            start = k
        elif not a and start is not None:
            if k - start >= min_len:
                segs.append((start, k))
            start = None
    return segs

def fit_amplitude(y, f):
    t = np.arange(len(y))
    basis = np.stack([np.cos(2*np.pi*f*t/FS), np.sin(2*np.pi*f*t/FS)], axis=1)
    coef, *_ = np.linalg.lstsq(basis, np.asarray(y, float), rcond=None)
    return float(np.hypot(*coef))

# Passes -------------------------------------------------------------------------------------------

def pass_tone_chain(results):
    scale = float(1 << 23)
    # A: EQ magnitude (two simulations from reset: no gaps, no ring-down between segments).
    frames = tone([(f, -20.0) for f in EQ_TONES], EQ_SETTLE + ANALYSIS).tolist()
    print(f"pass 1a (tone chain, EQ): {len(frames)} frames")
    y, _ = simulate(ToneChain(), frames, {}, tail_cycles=64)
    ya  = y[len(frames) - ANALYSIS:len(frames)]/scale
    exp = sos_db(eq_rows(), EQ_TONES)
    got = np.array([20*math.log10(fit_amplitude(ya, f)/db_to_linear(-20.0)) for f in EQ_TONES])
    err = float(np.max(np.abs(got - exp)))
    print("EQ    " + "  ".join(f"{f:.0f} Hz {g:+.2f} dB (design {e:+.2f})" for f, g, e in zip(EQ_TONES, got, exp))
          + f"  -> max error {err:.2f} dB (limit {EQ_TOL_DB})")
    # D: THD+N of the dithered 16-bit output (EQ bypassed: its transient would take ~8 tau).
    frames = tone([(THDN_TONE_HZ, -6.0)], THDN_SETTLE + ANALYSIS).tolist()
    print(f"pass 1b (tone chain, THD+N): {len(frames)} frames")
    y, _ = simulate(ToneChain(), frames, {}, setup=[("eq.bypass", 1)], tail_cycles=64)
    yd   = (y[len(frames) - ANALYSIS:len(frames)] >> 8).astype(float)
    thdn = float(thd_n_db(yd, THDN_TONE_HZ/FS, band=(THDN_BAND_HZ[0]/FS, THDN_BAND_HZ[1]/FS)))
    full = float(thd_n_db(yd, THDN_TONE_HZ/FS))
    print(f"THD+N {thdn:.1f} dB in {THDN_BAND_HZ[0]:.0f} Hz..{THDN_BAND_HZ[1]/1000:.0f} kHz ({full:.1f} dB full band: the "
          f"2nd-order shaper moves the dither noise above the audio band), -6 dBFS {THDN_TONE_HZ:.0f} Hz at the "
          f"16-bit output (limit {THDN_MAX_DB})")
    results.update(eq_got=got, eq_exp=exp, thdn=thdn, spectrum=yd)
    return err <= EQ_TOL_DB and thdn <= THDN_MAX_DB

def step_levels(y, b0):
    """Amplitude (dBFS) of the last half of each compressor level step starting at ``b0``."""
    scale = float(1 << 23)
    out = []
    for k in range(len(COMP_LEVELS_DB)):                     # Inner window: the segment start is
        lo = b0 + k*SEG_STEP + SEG_STEP//2 + 4                 # found within a frame (sin(0) = 0).
        yb = y[lo:b0 + (k + 1)*SEG_STEP - 4]/scale
        out.append(20*math.log10(max(fit_amplitude(yb, 1000.0), 1e-9)))
    return out

def limiter_peak(y, c0, c1):
    """Output peak (dBFS) over the second half of the limiter segment."""
    return 20*math.log10(max(np.max(np.abs(y[c0 + SEG_STEP//2:c1])), 1)/float(1 << 23))

def pass_dynamics_chain(results):
    seg_b = np.concatenate([tone([(1000.0, db)], SEG_STEP, k*SEG_STEP) for k, db in enumerate(COMP_LEVELS_DB)])
    seg_c = tone([(1000.0, 0.0)], SEG_STEP)
    frames, sched = build([
        (seg_b, [("comp.bypass", 0), ("limiter.bypass", 1)]),
        (seg_c, [("comp.bypass", 1), ("limiter.bypass", 0)]),
    ])
    release = time_constant_coeff(COMP_RELEASE_MS, FS, 16)
    setup   = [("comp.detector", 0), ("comp.attack", 65535), ("comp.release", release)]
    print(f"pass 2 (dynamics chain): {len(frames)} frames")
    top = DynamicsChain()
    y, seen = simulate(top, frames, sched, setup=setup, status={"clips": top.meter.clip_count[0]})
    segs = segments(y)
    if len(segs) != 2:
        print(f"FAIL: dynamics chain expected 2 segments, got {[(a, b - a) for a, b in segs]}")
        return False
    (b0, b1), (c0, c1) = segs
    comp_out = step_levels(y, b0)
    peak_db  = limiter_peak(y, c0, c1)
    comp_exp = [compressor_curve(level) for level in COMP_LEVELS_DB]
    # Bit-exact model of each stage on the same stimulus (the other stage is bypassed).
    thr, s_above, s_below, _, _, gr_max = PRESET_VALUES["compressor"]
    beats = [int(v) for v in np.concatenate([[0]*GAP, seg_b]) for _ in range(2)]
    ym = compressor_model(beats, [k % 2 for k in range(len(beats))], thr, s_above, s_below, 65535, release,
        gr_max, detector=0)[0][0::2]
    thr, s_above, s_below, att, rel, gr_max = PRESET_VALUES["limiter"]
    beats = [int(v) for v in np.concatenate([[0]*GAP, seg_c]) for _ in range(2)]
    yl = compressor_model(beats, [k % 2 for k in range(len(beats))], thr, s_above, s_below, att, rel,
        gr_max, lookahead=32)[0][0::2]
    (mb0, _), = segments(np.asarray(ym))
    (mc0, mc1), = segments(np.asarray(yl))
    model_out  = step_levels(np.asarray(ym), mb0)
    model_peak = limiter_peak(np.asarray(yl), mc0, mc1)
    cerr = float(np.max(np.abs(np.array(comp_out) - np.array(comp_exp))))
    merr = float(np.max(np.abs(np.array(comp_out) - np.array(model_out))))
    print("COMP  " + "  ".join(f"{l:+.0f} -> {o:+.2f} dBFS (design {e:+.2f}, model {m:+.2f})"
          for l, o, e, m in zip(COMP_LEVELS_DB, comp_out, comp_exp, model_out))
          + f"  -> max error {cerr:.2f} dB vs design (limit {COMP_TOL_DB}), {merr:.3f} dB vs model (limit {MODEL_TOL_DB})")
    clips = seen["clips"]
    print(f"LIM   0 dBFS in -> peak {peak_db:+.2f} dBFS (model {model_peak:+.2f}, ceiling {LIMITER_CEILING_DB:+.1f} +{LIMITER_TOL_DB}), clip count {clips}")
    results.update(comp_out=comp_out, comp_exp=comp_exp, peak_db=peak_db, clips=clips)
    return (cerr <= COMP_TOL_DB and merr <= MODEL_TOL_DB and abs(peak_db - model_peak) <= MODEL_TOL_DB
            and peak_db <= LIMITER_CEILING_DB + LIMITER_TOL_DB and clips == 0)

def pass_i2s_loop(results):
    prng = np.random.default_rng(1)
    x = prng.integers(-FS24, FS24, I2S_FRAMES).astype(np.int64)
    print(f"pass 3 (I2S transport): {I2S_FRAMES} frames")
    y, _ = simulate(I2SLoop(), x.tolist(), {}, setup=[("dither.dither_enable", 0), ("dither.shaping_enable", 0)],
        tail_cycles=4*2*SLOT*BCLK_DIV)
    exp = np.clip((x + 128) >> 8, -32768, 32767).tolist()           # Round half up, 16-bit.
    got = (y >> 8).tolist()
    # The slave receivers lock on the first LRCK transition (the first frame's left slot sits at
    # the reset level), so the run starts a frame or two into the stimulus.
    hit = next(((k, j) for j in range(3) for k in range(len(got)) if got[k:k + 32] == exp[j:j + 32]), None)
    ok  = hit is not None and got[hit[0]:] == exp[hit[1]:hit[1] + len(got) - hit[0]]
    print(f"I2S   {len(got)} words received, transport {'bit-exact' if ok else 'MISMATCH'}"
          + (f" (stimulus frame {hit[1]} onwards)" if hit else ""))
    return bool(ok)

# Plot ---------------------------------------------------------------------------------------------

def plot(plot_dir, r):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[plot] matplotlib not installed, skipping the figure")
        return
    os.makedirs(plot_dir, exist_ok=True)
    fig, ax = plt.subplots(1, 3, figsize=(14, 4))
    f = np.logspace(math.log10(20), math.log10(20000), 400)
    ax[0].semilogx(f, sos_db(eq_rows(), f), label="design")
    ax[0].plot(EQ_TONES, r["eq_got"], "o", label="measured")
    ax[0].set(title="3-band EQ", xlabel="Hz", ylabel="dB"); ax[0].grid(True, which="both"); ax[0].legend()
    lv = np.linspace(-40, 0, 100)
    ax[1].plot(lv, [compressor_curve(l) for l in lv], label="design")
    ax[1].plot(COMP_LEVELS_DB, r["comp_out"], "o", label="measured")
    ax[1].set(title="Compressor static curve (peak, 4:1 above -20 dB)", xlabel="in dBFS", ylabel="out dBFS")
    ax[1].grid(True); ax[1].legend()
    yd   = r["spectrum"]
    spec = np.abs(np.fft.rfft(yd*np.hanning(len(yd))))/(len(yd)/4)/32768
    ax[2].plot(np.fft.rfftfreq(len(yd), 1/FS), 20*np.log10(np.maximum(spec, 1e-9)))
    ax[2].set(title=f"16-bit dithered output (-6 dBFS {THDN_TONE_HZ:.0f} Hz)", xlabel="Hz", ylabel="dBFS", ylim=(-140, 0))
    ax[2].grid(True)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an010_audio.png"), dpi=110)

# Main ---------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plot-dir", default=None, help="Write an010_audio.png to this directory.")
    parser.add_argument("--passes", default="1,2,3", help="Comma-separated subset of the passes to run.")
    args = parser.parse_args()
    results = {}
    passes  = {"1": pass_tone_chain, "2": pass_dynamics_chain, "3": pass_i2s_loop}
    ok = True
    for k in args.passes.split(","):
        ok = passes[k](results) and ok
    if args.plot_dir and {"eq_got", "comp_out", "spectrum"} <= set(results):
        plot(args.plot_dir, results)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
