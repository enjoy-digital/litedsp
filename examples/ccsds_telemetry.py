#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""CCSDS-style concatenated-FEC telemetry chain with the burst-spreading interleaver (AN005).

The classic CCSDS 131.0-B deep-space telemetry stack, assembled from LiteDSP blocks:

    TX: message bytes -> RSEncoder(255,223) x I codewords -> BlockInterleaver(I x 255)
        -> bytes-to-bits -> ConvEncoder (K=7, rate 1/2) -> SymbolMapper (QPSK)
    Channel (NumPy): AWGN at a set Es/N0 + a JAMMER BURST (a span of channel symbols
        replaced by random constellation points)
    RX: SoftDemapper (4-bit LLRs) -> soft ViterbiDecoder -> bits-to-bytes
        -> BlockDeinterleaver -> RSDecoder -> message bytes

The interleaver is the point of the demo: Viterbi decoder errors are bursty (a wrong path
survives for tens of symbols), and without interleaving one channel burst lands in a single
RS codeword and quickly exceeds its t = 16 correctable bytes. Interleaved with depth I, the
burst is spread across I codewords (<= ceil(B/I) bytes each), so the correctable burst grows
~I times. The burst-length sweep runs both chains — identical except for the (de)interleaver —
on the bit-exact NumPy golden models (test/models.py) and plots per-codeword damage; a full
RTL end-to-end run (every block in the Migen simulator, AWGN + burst channel, streams handed
intact between per-stage simulations) recovers the message exactly. The RTL point defaults to
ONE RS codeword (I = 1) to keep simulation time sane (the soft Viterbi decoder simulates at
~30 symbols/s in Migen); ``AN005_RTL_DEPTH=2`` runs the RTL chain at I = 2 with the demo
burst that is *uncorrectable without interleaving* — the money demo in RTL (a few minutes).

Documented deviations from CCSDS 131.0-B (see doc/app_notes/an005_ccsds_telemetry.md):
- The RS codec is the conventional-basis 0x11D/fcr=0 codec, not the CCSDS dual-basis 0x187
  code (byte-compatible chain structure, not bit-compatible with a CCSDS channel).
- Interleaving depth I = 2 for the model sweep (I = 1 for the default RTL point) keeps the
  runtime sane; the standard depths are I in {1, 2, 3, 4, 5, 8} with I = 5 typical (the
  blocks default to rows=5).
- Bytes are serialized LSB-first (the litex stream.Converter order); CCSDS transmits MSB
  first. The chain is byte-transparent either way (TX and RX agree).

Run: python3 examples/ccsds_telemetry.py  (writes the burst plot to doc/app_notes/img/)
"""

import os
import sys
import time
import argparse

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.comm.rs          import LiteDSPRSEncoder, LiteDSPRSDecoder
from litedsp.comm.interleaver import LiteDSPBlockInterleaver, LiteDSPBlockDeinterleaver
from litedsp.comm.coding      import LiteDSPConvEncoder
from litedsp.comm.mapper      import LiteDSPSymbolMapper
from litedsp.comm.soft_demap  import LiteDSPSoftDemapper
from litedsp.comm.viterbi     import LiteDSPViterbiDecoder

from test.common import run_stream, column
from test.models import (rs_encode_model, rs_decode_model, block_interleave_model,
    block_deinterleave_model, soft_demap_model, viterbi_model)

# Parameters ---------------------------------------------------------------------------------------

RS_N, RS_K, RS_T = 255, 223, 16     # RS(255,223): t = 16 correctable bytes per codeword.
SWEEP_I          = 2                # Model-sweep interleaving depth (CCSDS: 1..5, 8).
SPACING          = 8000             # QPSK constellation half-spacing (mapper/demapper LSBs).
LLR_SCALE        = 24               # Q1.15 demapper rescale: clean point -> |LLR| ~ 6 of +/-7.
FLUSH_BITS       = 64               # Conv-encoder flush: > Viterbi traceback - 1 = 55.
ESN0_DB          = 8.0              # Channel Es/N0 (QPSK symbol SNR) for sweep + RTL point.
DEMO_BURST       = 160              # Demo burst length (symbols): breaks I=1, corrected at I=2.

def burst_position(rows):
    """Burst start (channel symbols): centered in codeword rows-1's span (the last row)."""
    return (rows - 1)*RS_N*8 + 460

# TX / RX chains -------------------------------------------------------------------------------------

class CCSDSTx(LiteXModule):
    """RS encode (I codewords) -> byte interleave -> serialize -> conv K=7 -> QPSK map."""
    def __init__(self, rows=SWEEP_I, interleave=True):
        self.rs   = LiteDSPRSEncoder(n=RS_N, k=RS_K, with_csr=False)
        self.conv = LiteDSPConvEncoder(with_csr=False)              # K=7, G=(171,133) octal.
        self.b2b  = stream.Converter(8, 1)                          # Bytes -> bits, LSB-first.
        self.map  = LiteDSPSymbolMapper(bits_per_axis=1, spacing=SPACING, with_csr=False)
        self.sink, self.source = self.rs.sink, self.map.source
        path = [self.rs.source]
        if interleave:
            self.ilv = LiteDSPBlockInterleaver(rows=rows, cols=RS_N, width=8, with_csr=False)
            self.comb += path[-1].connect(self.ilv.sink)
            path.append(self.ilv.source)
        self.comb += [
            path[-1].connect(self.b2b.sink, omit={"first", "last"}),
            self.b2b.source.connect(self.conv.sink),
            # Conv symbol [g1|g0] -> QPSK symbol [q|i]: g0 on I, g1 on Q (two BPSK channels).
            self.map.sink.valid.eq(self.conv.source.valid),
            self.conv.source.ready.eq(self.map.sink.ready),
            self.map.sink.symbol.eq(self.conv.source.data),
        ]

class CCSDSRxBackend(LiteXModule):
    """Decoded bits -> pack bytes -> deinterleave -> RS decode (the post-Viterbi RX)."""
    def __init__(self, rows=SWEEP_I, interleave=True):
        self.b2B = stream.Converter(1, 8)                           # Bits -> bytes, LSB-first.
        self.rsd = LiteDSPRSDecoder(n=RS_N, k=RS_K, with_csr=False)
        self.sink, self.source = self.b2B.sink, self.rsd.source
        path = [self.b2B.source]
        if interleave:
            self.dilv = LiteDSPBlockDeinterleaver(rows=rows, cols=RS_N, width=8, with_csr=False)
            self.comb += path[-1].connect(self.dilv.sink)
            path.append(self.dilv.source)
        self.comb += path[-1].connect(self.rsd.sink, omit={"first", "last"})

# Golden-model chain ---------------------------------------------------------------------------------

def conv_encode(bits, constraint=7, polys=(0o171, 0o133)):
    """Reference K=7 convolutional encoder (mirrors LiteDSPConvEncoder)."""
    reg, out = 0, []
    for b in bits:
        full = int(b) | (reg << 1)
        sym  = 0
        for k, g in enumerate(polys):
            sym |= (bin(g & full).count("1") & 1) << k
        out.append(sym)
        reg = full & ((1 << (constraint - 1)) - 1)
    return out

def bytes_to_bits(data):
    """LSB-first per byte (the litex stream.Converter(8, 1) order)."""
    return [(int(b) >> j) & 1 for b in data for j in range(8)]

def bits_to_bytes(bits):
    return [sum(bits[8*i + j] << j for j in range(8)) for i in range(len(bits)//8)]

def tx_model(msg, rows, interleave=True):
    """Bit-exact model TX; returns (codeword bytes, channel I, channel Q) incl. flush symbols."""
    cw = []
    for c in range(rows):
        cw += rs_encode_model(msg[c*RS_K:(c + 1)*RS_K], n=RS_N, k=RS_K)
    chan = block_interleave_model(cw, rows=rows, cols=RS_N) if interleave else cw
    syms = conv_encode(bytes_to_bits(chan) + [0]*FLUSH_BITS)
    i = np.array([(2*((s >> 0) & 1) - 1)*SPACING for s in syms], np.int64)
    q = np.array([(2*((s >> 1) & 1) - 1)*SPACING for s in syms], np.int64)
    return cw, i, q

def channel(i, q, burst_len, burst_at, rng, esn0_db=ESN0_DB):
    """AWGN at Es/N0 + a jammer burst: burst_len symbols replaced by random QPSK points."""
    x = i.astype(float)
    y = q.astype(float)
    n0 = np.mean(x**2 + y**2)/10**(esn0_db/10)
    x += rng.normal(0, np.sqrt(n0/2), len(x))
    y += rng.normal(0, np.sqrt(n0/2), len(y))
    if burst_len:
        x[burst_at:burst_at + burst_len] = (rng.integers(0, 2, burst_len)*2 - 1)*SPACING
        y[burst_at:burst_at + burst_len] = (rng.integers(0, 2, burst_len)*2 - 1)*SPACING
    return (np.clip(np.round(x), -32768, 32767).astype(np.int64),
            np.clip(np.round(y), -32768, 32767).astype(np.int64))

def rx_model(i, q, rows, interleave=True):
    """Bit-exact model RX; returns (message bytes, per-codeword RS status, RS input bytes)."""
    llrs  = soft_demap_model(i, q, bits_per_axis=1, spacing=SPACING, llr_bits=4,
        llr_scale=LLR_SCALE, scale_frac=15)
    bits  = viterbi_model([int(x) for x in llrs], llr_bits=4)
    rxb   = bits_to_bytes(bits[:8*rows*RS_N])
    if interleave:
        rxb = block_deinterleave_model(rxb, rows=rows, cols=RS_N)
    out, stats = [], []
    for c in range(rows):
        m, corrected, unc = rs_decode_model(rxb[c*RS_N:(c + 1)*RS_N], n=RS_N, k=RS_K)
        out += m
        stats.append((corrected, unc))
    return out, stats, rxb

def run_point(msg, burst_len, interleave, rows=SWEEP_I, seed=7):
    """One model-chain run; returns (recovered ok, worst per-codeword byte errors, any unc)."""
    cw, ti, tq = tx_model(msg, rows, interleave)
    ri, rq     = channel(ti, tq, burst_len, burst_position(rows), np.random.default_rng(seed))
    out, stats, rxb = rx_model(ri, rq, rows, interleave)
    errs = [sum(1 for a, b in zip(rxb[c*RS_N:(c + 1)*RS_N], cw[c*RS_N:(c + 1)*RS_N]) if a != b)
            for c in range(rows)]
    return out == list(msg), max(errs), any(u for _, u in stats)

# RTL end-to-end run ---------------------------------------------------------------------------------

def _rtl(dut, samples, n_out, in_fields, out_fields):
    """One full-rate stage simulation (no artificial throttle: RTL runtime matters here)."""
    return run_stream(dut, samples, n_out, in_fields, out_fields,
        sink_throttle=0.0, source_ready_rate=1.0)

def demapper_scaled():
    """Demapper with the example's llr_scale wired (a plain Signal when with_csr=False)."""
    d = LiteDSPSoftDemapper(bits_per_axis=1, spacing=SPACING, llr_bits=4, with_csr=False)
    d.comb += d.llr_scale.eq(LLR_SCALE)
    return d

def run_rtl(msg, rows, burst_len):
    """Full RTL chain around the NumPy AWGN+burst channel; returns the recovered bytes.

    Every block runs in the Migen simulator; the chain is simulated stage by stage (streams
    captured whole and handed to the next stage intact — the blocks count block boundaries
    from reset, so this is exactly the composed behavior) because a single all-blocks
    simulation multiplies every block's per-cycle cost into the ~30 symbols/s Viterbi rate.
    Intermediate streams are also checked bit-exact against the golden models.
    """
    n_syms = rows*RS_N*8                                         # Payload channel symbols.
    # TX composite: message bytes -> QPSK I/Q.
    t0  = time.time()
    cap = _rtl(CCSDSTx(rows=rows), [{"data": int(b)} for b in msg], n_syms,
        ["data"], ["i", "q"])
    ti, tq = column(cap, "i", 16), column(cap, "q", 16)
    # Model==RTL: the TX waveform must be bit-identical to the golden-model TX (the model
    # also supplies the FLUSH_BITS tail symbols that drain the Viterbi survivor depth).
    _, mi, mq = tx_model(msg, rows, interleave=True)
    assert np.array_equal(ti, mi[:n_syms]) and np.array_equal(tq, mq[:n_syms]), \
        "RTL TX waveform != NumPy golden model"
    print(f"    TX  RS encode x{rows} -> interleave -> conv -> map: {len(ti)} symbols "
          f"== model ({time.time() - t0:.0f}s)")
    # Channel (same as the model sweep).
    ri, rq = channel(mi, mq, burst_len, burst_position(rows), np.random.default_rng(7))
    # RX stage 1: soft demapper (I/Q -> packed 4-bit LLR pairs).
    t0   = time.time()
    cap  = _rtl(demapper_scaled(), [{"i": int(a) & 0xFFFF, "q": int(b) & 0xFFFF}
                                    for a, b in zip(ri, rq)], len(ri),
        ["i", "q"], ["llrs"])
    llrs = [c["llrs"] for c in cap]
    assert llrs == [int(x) for x in soft_demap_model(ri, rq, bits_per_axis=1, spacing=SPACING,
        llr_bits=4, llr_scale=LLR_SCALE, scale_frac=15)], "RTL demapper != model"
    print(f"    RX  soft demapper: {len(llrs)} LLR pairs == model ({time.time() - t0:.0f}s)")
    # RX stage 2: soft Viterbi (the simulation-time hot spot).
    t0   = time.time()
    vit  = LiteDSPViterbiDecoder(llr_bits=4, with_csr=False)
    cap  = _rtl(vit, [{"llrs": l} for l in llrs], len(llrs) - vit.traceback + 1,
        ["llrs"], ["data"])
    bits = [c["data"] for c in cap]
    assert bits == viterbi_model(llrs, llr_bits=4), "RTL Viterbi != model"
    print(f"    RX  soft Viterbi: {len(bits)} bits == model ({time.time() - t0:.0f}s)")
    # RX stage 3: pack -> deinterleave -> RS decode.
    t0  = time.time()
    cap = _rtl(CCSDSRxBackend(rows=rows), [{"data": b} for b in bits[:8*rows*RS_N]],
        rows*RS_K, ["data"], ["data"])
    print(f"    RX  deinterleave -> RS decode x{rows}: {rows*RS_K} bytes "
          f"({time.time() - t0:.0f}s)")
    return [c["data"] for c in cap]

# Plot -------------------------------------------------------------------------------------------------

def save_plot(plot_dir, lengths, res_plain, res_ilv):
    try:
        import matplotlib
    except ImportError:
        print("  (matplotlib not available: skipping plots)")
        return
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    os.makedirs(plot_dir, exist_ok=True)
    ink, muted, blue, orange = "#333230", "#6f6d66", "#2a78d6", "#d97706"
    fig, ax = plt.subplots(figsize=(7.2, 4.2), dpi=140)
    for res, color, label in [(res_plain, orange, "no interleaving"),
                              (res_ilv,   blue,   f"block interleaver, I = {SWEEP_I}")]:
        worst = [r[1] for r in res]
        ok    = [r[0] for r in res]
        ax.plot(lengths, worst, "o-", color=color, lw=1.6, ms=5, mec="white", mew=0.8,
            label=f"{label} (worst codeword)")
        bad = [(l, w) for l, w, k in zip(lengths, worst, ok) if not k]
        if bad:
            ax.plot(*zip(*bad), "x", color=color, ms=11, mew=2.2,
                label=f"{label}: RS uncorrectable")
    ax.axhline(RS_T, color="#c9c7c0", lw=1.0)
    ax.text(lengths[0], RS_T + 0.6, f"RS(255,223) limit t = {RS_T} bytes/codeword",
        fontsize=8, color=muted)
    ax.set_xlabel("channel burst length (QPSK symbols jammed)", color=ink)
    ax.set_ylabel("RS-input byte errors, worst codeword", color=ink)
    ax.set_title(f"AN005 concatenated FEC: interleaving spreads the Viterbi error burst "
                 f"(Es/N0 = {ESN0_DB:.0f} dB)", color=ink, fontsize=10)
    ax.grid(color="#dddbd4", lw=0.6, alpha=0.6)
    ax.tick_params(colors=muted, labelsize=8)
    for s in ax.spines.values():
        s.set_color("#c9c7c0")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)
    fig.tight_layout()
    fig.savefig(os.path.join(plot_dir, "an005_burst.png"))
    plt.close(fig)
    print(f"  plot -> {os.path.join(plot_dir, 'an005_burst.png')}")

# Demo -------------------------------------------------------------------------------------------------

def main():
    default_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "doc", "app_notes", "img")
    parser = argparse.ArgumentParser(description="AN005 CCSDS concatenated-FEC telemetry chain.")
    parser.add_argument("--plot-dir", default=default_dir, help="Output directory for PNG plots.")
    parser.add_argument("--rtl-depth", default=int(os.environ.get("AN005_RTL_DEPTH", 1)),
        type=int, choices=[1, 2], help="Interleaving depth for the RTL run (1 = fast/CI; "
        "2 = the full burst money demo in RTL, a few minutes).")
    args = parser.parse_args()

    rng = np.random.default_rng(42)
    msg = [int(x) for x in rng.integers(0, 256, SWEEP_I*RS_K)]

    print(f"CCSDS telemetry (AN005): RS(255,223) x {SWEEP_I} -> interleave (I={SWEEP_I}) "
          f"-> conv K=7 r=1/2 -> QPSK/AWGN+burst -> LLRs -> soft Viterbi -> deinterleave -> RS")
    print(f"  burst sweep (NumPy golden models, Es/N0 {ESN0_DB:.0f} dB, "
          f"burst inside one codeword's span):")

    # Burst-length sweep: identical chains, with and without the (de)interleaver.
    lengths   = [0, 40, 80, 120, 160, 200, 240, 280]
    res_plain = [run_point(msg, l, interleave=False) for l in lengths]
    res_ilv   = [run_point(msg, l, interleave=True)  for l in lengths]
    for l, p, v in zip(lengths, res_plain, res_ilv):
        print(f"    burst {l:3d} syms: no-ILV worst codeword {p[1]:2d} bytes "
              f"{'OK          ' if p[0] else 'UNCORRECTABLE'}   "
              f"ILV worst {v[1]:2d} bytes {'OK' if v[0] else 'UNCORRECTABLE'}")

    # The money demo: at DEMO_BURST the plain chain is beyond t = 16 in one codeword and
    # fails; the interleaved chain spreads the same burst and recovers exactly.
    demo   = lengths.index(DEMO_BURST)
    max_ok = lambda res: max((l for l, r in zip(lengths, res) if r[0]), default=0)
    print(f"  correctable burst: {max_ok(res_plain)} symbols plain -> {max_ok(res_ilv)} "
          f"symbols interleaved (I = {SWEEP_I}, limit ~ I*t = {SWEEP_I*RS_T} bytes)")
    assert not res_plain[demo][0] and res_plain[demo][2], \
        f"expected the {DEMO_BURST}-symbol burst to break the non-interleaved chain"
    assert res_ilv[demo][0], \
        f"expected the interleaver to correct the {DEMO_BURST}-symbol burst"
    assert res_ilv[demo][1] <= RS_T < res_plain[demo][1], \
        "expected the burst spread below t only with interleaving"
    assert max_ok(res_ilv) >= 1.5*max_ok(res_plain), "interleaving gain below 1.5x"

    # Full RTL end-to-end run (every block in the Migen simulator). Depth 1 (default) uses a
    # burst sized within one codeword's t = 16 (interleaver in the chain, identity at I = 1);
    # depth 2 replays the sweep's DEMO_BURST — uncorrectable without interleaving — in RTL.
    rows      = args.rtl_depth
    rtl_burst = DEMO_BURST if rows >= 2 else 60
    rtl_msg   = msg[:rows*RS_K]
    print(f"  RTL end-to-end: I = {rows} ({rows*RS_K} message bytes), burst {rtl_burst} "
          f"symbols at Es/N0 {ESN0_DB:.0f} dB (Migen, staged per block)...")
    t0  = time.time()
    got = run_rtl(rtl_msg, rows, rtl_burst)
    assert got == rtl_msg, "RTL chain did not recover the message exactly"
    print(f"    message recovered error-free ({rows*RS_K} bytes) in {time.time() - t0:.0f}s "
          f"of simulation")
    print(f"  PASS: burst of {DEMO_BURST} symbols breaks the non-interleaved chain "
          f"(uncorrectable) and is fully corrected with I = {SWEEP_I} interleaving; "
          f"RTL chain (I = {rows}, burst {rtl_burst}) error-free")

    save_plot(args.plot_dir, lengths, res_plain, res_ilv)

if __name__ == "__main__":
    main()
