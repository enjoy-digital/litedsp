#!/usr/bin/env python3
#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""AN011 - Pulse-Doppler radar: range gate, pulse compression, MTI, corner turn, Doppler
processing, 2-D CFAR, peak extraction, target list and alpha-beta tracking.

Three RTL passes over one synthetic scene (P = 16 Hamming-tapered chirp, N = 64 range bins,
M = 16 pulses per CPI, PRI = 80 samples, two CPIs; three moving targets, stationary clutter,
AWGN), each gated on a measured property:

1. front end: ADC samples -> LiteDSPRangeGate -> LiteDSPPulseCompressor -> LiteDSPMTICanceller
   -> LiteDSPCornerTurn (framing, compressed profile peaks, clutter suppression);
2. Doppler + detection: slow-time columns -> LiteDSPDopplerProcessor -> LiteDSPCFAR2D ->
   LiteDSPPeakExtractor -> LiteDSPTargetList (targets found, false alarms bounded, centroids);
3. tracking: the pass-2 detections + synthesised CPIs -> LiteDSPAlphaBetaTracker (confirmed
   tracks, RMS error, coasting through dropped detections).

Run: ``python3 examples/pulse_doppler_radar.py [--plot-dir DIR]``; prints PASS.
"""

import os
import sys
import math
import argparse

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from migen import *

from litex.gen import *

from litedsp.radar.timing      import LiteDSPRangeGate
from litedsp.radar.compress    import LiteDSPPulseCompressor
from litedsp.radar.mti         import LiteDSPMTICanceller
from litedsp.radar.corner_turn import LiteDSPCornerTurn
from litedsp.radar.doppler     import LiteDSPDopplerProcessor
from litedsp.radar.cfar_2d     import LiteDSPCFAR2D
from litedsp.radar.detect      import LiteDSPPeakExtractor, LiteDSPTargetList
from litedsp.radar.track       import LiteDSPAlphaBetaTracker
from litedsp.radar.waveform    import chirp_reference
from litedsp.radar.design      import cfar_alpha

# Scene --------------------------------------------------------------------------------------------

P, B      = 16, 0.5                                                # Chirp: samples, bandwidth (fs).
N, M, PRI = 64, 16, 80                                              # Range bins, pulses / CPI, PRI.
N_CPI     = 2                                                           # RTL CPIs.
FRAC      = 4                                                           # Sub-bin bits (Q.4).
# (range bin, Doppler bin, amplitude, range rate, Doppler rate) - rates in bins per CPI.
TARGETS = [(12.0, 3.0, 0.5, 0.5, 0.2), (30.0, 11.0, 0.3, -0.5, 0.1), (45.0, 6.4, 0.2, 0.1, 0.05)]
CLUTTER = (20, 0.8)                                                     # Stationary return.
SIGMA   = 200.0                                                         # AWGN (LSB).

def truth(cpi):
    return [(r + vr*cpi, d + vd*cpi) for r, d, _, vr, vd in TARGETS]

def scene(seed=11):
    """ADC samples for N_CPI CPIs: each pulse's echoes at integer ranges, rotating by the target's
    Doppler bin per pulse, plus clutter and noise."""
    rng   = np.random.default_rng(seed)
    pulse = chirp_reference(P, B)
    n     = (N_CPI*M + 1)*PRI                                     # + one PRI: flushes the FIR tail.
    rx    = rng.normal(0, SIGMA, n) + 1j*rng.normal(0, SIGMA, n)
    for c in range(N_CPI):
        for p in range(M):
            t0 = (c*M + p)*PRI
            for (r, fd), (_, _, a, _, _) in zip(truth(c), TARGETS):
                ri = int(round(r))
                rx[t0 + ri:t0 + ri + P] += a*pulse*np.exp(2j*math.pi*fd*p/M)
            rx[t0 + CLUTTER[0]:t0 + CLUTTER[0] + P] += CLUTTER[1]*pulse
    rx = np.clip(np.round(rx.real), -32767, 32767) + 1j*np.clip(np.round(rx.imag), -32767, 32767)
    return [{"i": int(v.real), "q": int(v.imag)} for v in rx]

# Simulation helper --------------------------------------------------------------------------------

def signed(v, width):
    v = int(v)
    return v - (1 << width) if v >= 1 << (width - 1) else v

def simulate(top, beats, in_fields, out_fields, done, taps=(), max_cycles=12000):
    """Push ``beats`` into ``top.sink`` at full rate, capture ``top.source`` until ``done(out)``,
    and record every transfer on the ``taps`` ``(endpoint, fields)``."""
    out  = []
    data = [[] for _ in taps]
    def read(ep, fields):                                             # (no yield in comprehensions)
        beat = {}
        for f in fields:
            beat[f] = (yield getattr(ep, f))
        return beat
    @passive
    def capture():
        yield top.source.ready.eq(1)
        while True:
            if (yield top.source.valid):
                out.append((yield from read(top.source, out_fields)))
            yield
    def tap(ep, fields, store):
        @passive
        def gen():
            while True:
                if (yield ep.valid) and (yield ep.ready):
                    store.append((yield from read(ep, fields)))
                yield
        return gen()
    def driver():
        for b in beats:
            for f in in_fields:
                yield getattr(top.sink, f).eq(int(b.get(f, 0)))
            yield top.sink.valid.eq(1)
            yield
            while not (yield top.sink.ready):
                yield
        yield top.sink.valid.eq(0)
        for _ in range(max_cycles):
            if done(out):
                return
            yield
        raise RuntimeError("simulation did not complete")
    run_simulation(top, [driver(), capture()] + [tap(ep, f, s) for (ep, f), s in zip(taps, data)])
    return out, data

# Pass 1: front end --------------------------------------------------------------------------------

class FrontEnd(LiteXModule):
    def __init__(self):
        self.rg = LiteDSPRangeGate(n_range_bins=N, n_pulses=M, pri=PRI, gate_start=0, pulse_width=P,
                                   with_csr=False)
        self.pc = LiteDSPPulseCompressor(pulse_len=P, bandwidth=B, window="hamming", with_csr=False)
        self.mti = LiteDSPMTICanceller(n_range_bins=N, order=3, with_csr=False)
        self.ct = LiteDSPCornerTurn(n_range_bins=N, n_pulses=M, with_csr=False)
        self.rg.enable.reset = 1
        self.mti.mode.reset  = 1                                        # 3-pulse canceller.
        self.sink, self.source = self.rg.sink, self.ct.source
        self.comb += [
            self.rg.source.connect(self.pc.sink),
            self.pc.source.connect(self.mti.sink),
            self.mti.source.connect(self.ct.sink),
        ]

def pass_front_end(adc):
    top = FrontEnd()
    n_out = N_CPI*N*M
    out, (pc, mti) = simulate(top, adc, ["i", "q"], ["i", "q", "first", "last"],
                              lambda o: len(o) >= n_out,
        taps=[(top.pc.source, ["i", "q", "first"]), (top.mti.source, ["i", "q", "first"])])
    out = out[:n_out]
    # The compressor emits P-1 pipeline beats before its first frame tag: align on 'first'.
    pc  = pc[next(k for k, b in enumerate(pc) if b["first"]):]
    mti = mti[next(k for k, b in enumerate(mti) if b["first"]):]
    r = {}
    # Framing: one slow-time column (M beats) per range bin.
    r["framing_ok"] = all(b["first"] == (k % M == 0) and b["last"] == (k % M == M - 1) for k,
                          b in enumerate(out))
    # Compressed range profiles (fast time, one frame per pulse).
    comp = np.array([signed(b["i"], 16) + 1j*signed(b["q"], 16) for b in pc[:N_CPI*M*N]]).reshape(
        -1, N)
    mtio = np.array([signed(b["i"], 16) + 1j*signed(b["q"], 16) for b in mti[:N_CPI*M*N]]).reshape(
        -1, N)
    profile = np.abs(comp[5])                                           # Pulse 5 of CPI 0.
    expected = sorted([int(round(t[0])) for t in truth(0)] + [CLUTTER[0]])
    peaks = []
    for e in expected:
        lo, hi = max(0, e - 4), min(N, e + 5)
        peaks.append(lo + int(np.argmax(profile[lo:hi])))
    r["peaks"], r["peaks_expected"] = peaks, expected
    # MTI clutter suppression at the clutter bin over pulses 2..15 of CPI 0 (3-pulse history).
    c_in  = np.mean(np.abs(comp[2:M, CLUTTER[0]]))
    c_out = np.mean(np.abs(mtio[2:M, CLUTTER[0]]))
    r["clutter_db"] = 20*math.log10(c_in/max(c_out, 1))
    r["profile"], r["profile_mti"] = profile, np.abs(mtio[5])
    r["columns"] = out
    ok = r["framing_ok"] and peaks == expected and r["clutter_db"] >= 30
    print(f"[pass 1] framing {'ok' if r['framing_ok'] else 'BAD'}, compressed peaks {peaks} "
          f"(expected {expected}), "
          f"MTI clutter suppression {r['clutter_db']:.1f} dB")
    return ok, r

# Pass 2: Doppler + detection ----------------------------------------------------------------------

class Detector(LiteXModule):
    def __init__(self):
        self.dp   = LiteDSPDopplerProcessor(n_pulses=M, window="hann", magnitude="approx",
                                            with_csr=False)
        self.cfar = LiteDSPCFAR2D(n_range_bins=N, n_doppler_bins=M, n_train=(3, 2), n_guard=(1, 1),
            data_width=17, with_csr=False)
        self.pe   = LiteDSPPeakExtractor(n_range_bins=N, n_doppler_bins=M, data_width=17,
                                         frac_bits=FRAC, with_csr=False)
        self.tl   = LiteDSPTargetList(max_targets=16, data_width=17, frac_bits=FRAC, with_csr=False)
        self.cfar.alpha.reset = cfar_alpha(1e-4, self.cfar.n_training, "magnitude")
        self.cfar.threshold_min.reset = 40                     # Noise floor: guards the zero-padded
                                                                        # edges and the MTI notch
                                                                        # column.
        self.sink, self.source = self.dp.sink, self.tl.source
        self.comb += [
            self.dp.source.connect(self.cfar.sink),
            self.cfar.source.connect(self.pe.sink),
            self.pe.source.connect(self.tl.sink),
        ]

def pass_detection(columns):
    top = Detector()
    # The SDF FFT releases a column's tail only as the next column arrives: one zero column
    # after the data flushes the last range bin of the second CPI.
    flush = [{"i": 0, "q": 0, "first": int(k == 0), "last": int(k == M - 1)} for k in range(M)]
    def done(o):
        return sum(1 for b in o if not b["hit"]) >= N_CPI
    out, (cells, dets) = simulate(top, columns + flush, ["i", "q", "first", "last"],
                                  ["range", "doppler", "data", "hit", "first", "last"],
        done, taps=[(top.dp.source, ["data"]), (top.cfar.source, ["detect"])])
    maps    = np.array([b["data"] for b in cells][:N_CPI*N*M]).reshape(N_CPI, N, M)
    detects = np.array([b["detect"] for b in dets][:N_CPI*N*M]).reshape(N_CPI, N, M)
    bursts, cur = [], []
    for b in out:
        if b["hit"]:
            cur.append((b["range"]/(1 << FRAC), b["doppler"]/(1 << FRAC), b["data"]))
        else:
            bursts.append((cur, b["data"])); cur = []
            if len(bursts) == N_CPI:
                break
    r = dict(maps=maps, detects=detects, bursts=[b for b, _ in bursts], found=[], false_alarms=[],
             sidelobes=[], errors=[])
    ok = True
    for c, (recs, count) in enumerate(bursts):
        ok &= count == len(recs)
        found, used = [], set()
        for k, (tr, td) in enumerate(truth(c)):
            best = None
            for i, (rr, dd, _) in enumerate(recs):
                e = max(abs(rr - round(tr)), abs(dd - td))
                if e <= 0.5 and (best is None or e < best[0]):
                    best = (e, i)
            if best is None:
                ok = False
                found.append(None)
            else:
                used.add(best[1]); found.append(recs[best[1]]); r["errors"].append(
                    (c, k, abs(recs[best[1]][0] - round(tr)), abs(recs[best[1]][1] - td)))
        # Unmatched records at a target's Doppler within the pulse length in range are its
        # compression sidelobes (P = 16 Hamming: ~-15 dB, above the threshold for a 40 dB target);
        # the rest are false alarms.
        side = fa = 0
        for i, (rr, dd, _) in enumerate(recs):
            if i in used:
                continue
            if any(abs(rr - round(tr)) <= P//2 and abs(dd - td) <= 1 for tr, td in truth(c)):
                side += 1
            else:
                fa += 1
        r["found"].append(found); r["false_alarms"].append(fa); r["sidelobes"].append(side)
        r.setdefault("unmatched", []).append(
            [(rr, dd, v) for i, (rr, dd, v) in enumerate(recs) if i not in used])
        ok &= fa <= 1 and side <= 3
        ok &= detects[c, CLUTTER[0], 0] == 0                      # MTI notch: no clutter detection.
    # The 6.4-bin target: interpolated Doppler within 0.35 bin.
    ok &= all(dd <= 0.35 for (_, k, _, dd) in r["errors"] if k == 2)
    print(f"[pass 2] targets found per CPI {[sum(f is not None for f in ff) for ff in r['found']]} "
          f"/ {len(TARGETS)}, "
          f"sidelobe detections {r['sidelobes']}, false alarms {r['false_alarms']}, max range / "
          f"Doppler error "
          f"{max(e[2] for e in r['errors']) if r['errors'] else float('nan'):.2f} / "
          f"{max(e[3] for e in r['errors']) if r['errors'] else float('nan'):.2f} bin, "
          f"clutter cell detected: {int(detects[:, CLUTTER[0], 0].sum())}")
    for c, u in enumerate(r["unmatched"]):
        if u:
            print(f"         CPI {c} unmatched records (range, Doppler, cell): "
                  f"{[(round(a, 2), round(b, 2), v) for a, b, v in u]}; "
                  f"targets {[(round(a, 1), round(b, 1)) for a, b in truth(c)]}")
    return ok, r

# Pass 3: tracking ---------------------------------------------------------------------------------

N_TRACK_CPI = 24

def tracker_input(bursts, seed=5):
    """The pass-2 bursts (CPIs 0, 1) followed by synthesised CPIs: truth + noise, one false alarm
    per CPI, target k dropped at CPI 6 + 3k."""
    rng   = np.random.default_rng(seed)
    beats = []
    def burst(recs):
        n = 0
        for rr, dd, v in recs:
            beats.append({"range": int(round(rr*(1 << FRAC))),
                          "doppler": int(round(dd*(1 << FRAC))), "data": int(v),
                          "hit": 1, "first": int(n == 0), "last": 0})
            n += 1
        beats.append(
            {"range": 0, "doppler": 0, "data": n, "hit": 0, "first": int(n == 0), "last": 1})
    for recs in bursts:
        burst(recs)
    for c in range(len(bursts), N_TRACK_CPI):
        recs = []
        for k, (tr, td) in enumerate(truth(c)):
            if c == 6 + 3*k:
                continue
            recs.append((tr + rng.uniform(-0.1, 0.1), td + rng.uniform(-0.1, 0.1), 10000))
        recs.append((rng.uniform(50, 62), rng.uniform(0, 15), 3000))
        burst(recs)
    return beats

def pass_tracking(bursts):
    top = LiteDSPAlphaBetaTracker(n_tracks=8, frac_bits=FRAC, with_csr=False)
    beats = tracker_input(bursts)
    def done(o):
        return sum(1 for b in o if not b["hit"]) >= N_TRACK_CPI
    out, _ = simulate(top, beats, ["range", "doppler", "data", "hit", "first", "last"],
        ["range", "doppler", "velocity", "id", "hits", "hit", "first", "last"], done)
    VW = len(top.source.velocity)
    tracks, cur = [], {}
    for b in out:
        if b["hit"]:
            cur[b["id"]] = (b["range"]/(1 << FRAC), b["doppler"]/(1 << FRAC),
                            signed(b["velocity"], VW)/256)
        else:
            tracks.append(cur); cur = {}
            if len(tracks) == N_TRACK_CPI:
                break
    r = dict(tracks=tracks)
    ok = len(tracks) == N_TRACK_CPI
    # Confirmed tracks by CPI 4 (confirm_hits 3): exactly the three targets, same ids afterwards.
    ids = sorted(tracks[3]) if ok else []
    ok &= len(ids) == len(TARGETS)
    ok &= all(sorted(t) == ids for t in tracks[4:])
    # Track -> target mapping by the CPI-3 positions.
    assoc = {}
    if ok:
        for i in ids:
            rr, dd, _ = tracks[3][i]
            assoc[i] = min(range(len(TARGETS)),
                           key=lambda k: abs(truth(3)[k][0] - rr) + abs(truth(3)[k][1] - dd))
        ok &= sorted(assoc.values()) == list(range(len(TARGETS)))
    err = []
    if ok:
        for c in range(8, N_TRACK_CPI):
            for i, k in assoc.items():
                err.append(tracks[c][i][0] - truth(c)[k][0])
        r["rms"] = float(np.sqrt(np.mean(np.square(err))))
        r["velocity_error"] = max(abs(tracks[N_TRACK_CPI - 1][i][2] - TARGETS[k][3]) for i,
                                  k in assoc.items())
        ok &= r["rms"] <= 0.35 and r["velocity_error"] <= 0.1
        r["assoc"] = assoc
    print(f"[pass 3] confirmed tracks {ids} (targets {len(TARGETS)}), range RMS over CPIs "
          f"8..{N_TRACK_CPI - 1} "
          f"{r.get('rms', float('nan')):.2f} bin, max range-rate error "
          f"{r.get('velocity_error', float('nan')):.3f} bin/CPI")
    return ok, r

# Plots --------------------------------------------------------------------------------------------

def plot(plot_dir, r1, r2, r3):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("[plot] matplotlib not installed, skipping the figures")
        return
    os.makedirs(plot_dir, exist_ok=True)
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    ax[0].plot(20*np.log10(np.maximum(r1["profile"], 1)), label="pulse compressor")
    ax[0].plot(20*np.log10(np.maximum(r1["profile_mti"], 1)), label="after MTI")
    for e in r1["peaks_expected"]:
        ax[0].axvline(e, color="k", alpha=0.2)
    ax[0].set(title="Range profile (pulse 5, CPI 0)", xlabel="range bin",
              ylabel="dB"); ax[0].legend(fontsize=8)
    m = 20*np.log10(np.maximum(r2["maps"][0], 1))
    ax[1].imshow(m, aspect="auto", origin="lower", cmap="viridis")
    dr, dc = np.nonzero(r2["detects"][0])
    ax[1].scatter(dc, dr, s=12, facecolors="none", edgecolors="w", label="CFAR detections")
    for rec in r2["bursts"][0]:
        ax[1].plot(rec[1], rec[0], "r+", ms=10)
    for tr, td in truth(0):
        ax[1].plot(td, tr, "cx", ms=7)
    ax[1].set(title="Range-Doppler map (CPI 0): detections, centroids (+), truth (x)",
              xlabel="Doppler bin", ylabel="range bin")
    for i, k in r3.get("assoc", {}).items():
        ax[2].plot([t[i][0] for t in r3["tracks"][3:]], range(3, N_TRACK_CPI), "-",
                   label=f"track {i}")
        ax[2].plot([truth(c)[k][0] for c in range(N_TRACK_CPI)], range(N_TRACK_CPI), "k:",
                   alpha=0.5)
    ax[2].set(title="Tracks (range vs CPI, truth dotted)", xlabel="range bin",
              ylabel="CPI"); ax[2].legend(fontsize=8)
    fig.tight_layout()
    path = os.path.join(plot_dir, "an011_pulse_doppler.png")
    fig.savefig(path, dpi=110)
    print(f"  plot -> {path}")

# Main ---------------------------------------------------------------------------------------------

def main():
    import time
    parser = argparse.ArgumentParser(description="AN011 pulse-Doppler radar.")
    parser.add_argument("--plot-dir", default=None, help="Save the figure here (matplotlib optional).")
    args = parser.parse_args()
    adc = scene()
    t = time.time()
    ok1, r1 = pass_front_end(adc)
    print(f"  ({time.time() - t:.0f} s)"); t = time.time()
    ok2, r2 = pass_detection(r1["columns"])
    print(f"  ({time.time() - t:.0f} s)"); t = time.time()
    ok3, r3 = pass_tracking(r2["bursts"])
    print(f"  ({time.time() - t:.0f} s)")
    if args.plot_dir:
        plot(args.plot_dir, r1, r2, r3)
    if ok1 and ok2 and ok3:
        print("  PASS: front end, detection and tracking gates met")
        return 0
    print("  FAIL")
    return 1

if __name__ == "__main__":
    sys.exit(main())
