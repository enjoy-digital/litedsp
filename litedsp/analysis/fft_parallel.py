#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import check, iq_layout, iq_lanes, scaled
from litedsp.analysis.fft import LiteDSPFFT, _twiddle_rom
from litedsp.stream.adapt import LiteDSPIQSerialToParallel, LiteDSPIQParallelToSerial

# Parallel FFT (Radix-2 DIF split, 2 samples/cycle) -------------------------------------------------

class LiteDSPParallelFFT(LiteXModule):
    """Streaming ``N``-point FFT at 2 samples/cycle (super-sample-rate wideband path).

    The serial radix-2 SDF schedule of :class:`~litedsp.analysis.fft.LiteDSPFFT` regrouped for
    two lanes per beat, **bit-identical** to the serial FFT on the flattened lane stream. The
    first DIF butterfly rank splits each frame into an ``N/2`` "sum" sub-frame (even bins) and
    a twiddled "difference" sub-frame (odd bins):

        ``X[2k]   = FFT_{N/2}( (x[n] + x[n + N/2]) / 2 )``
        ``X[2k+1] = FFT_{N/2}( (x[n] - x[n + N/2]) * W_N^n / 2 )``

    which is exactly what serial stage 0 computes (same ``scaled`` 1/2 round+saturate on the
    sum, same quantized Q1.(W-1) twiddle product and rescale on the difference); serial stages
    1..log2(N)-1 then process the two sub-frames as independent ``N/2``-sample blocks, since
    stage ``s`` of an ``N``-point SDF cascade is identical hardware to stage ``s - 1`` of an
    ``N/2``-point one (same delay ``D = N >> (s+1)``, same twiddle ROM) and SDF butterflies
    never mix consecutive blocks. The parallel datapath therefore instantiates two unmodified
    serial :class:`~litedsp.analysis.fft.LiteDSPFFT` ``N/2`` cores — one per sub-frame — fed at
    one sample/cycle each, with the 2-lane butterfly rank in front. Every rounding happens at
    the same position as in the serial machine, so each output frame is bit-exact vs the
    serial FFT (``fft_fixed_model``); only the latency differs.

    Interface: ``iq_layout(data_width, 2)`` on both sides, lane 0 = first/oldest sample.
    A frame is ``N/2`` beats; framing is positional (as in the serial FFT: sink ``first``/
    ``last`` markers are accepted but not required), and the source carries ``first``/``last``
    on beats 0 and ``N/2 - 1`` of each output frame. Output beat ``m`` carries the serial
    FFT's (bit-reversed, 1/N-scaled) output stream two beats at a time::

        lane 0 = X[bit_reverse(2m,     log2(N))] = X[r]            r = bit_reverse(m, log2(N/2))
        lane 1 = X[bit_reverse(2m + 1, log2(N))] = X[r + N/2]

    i.e. lanes carry consecutive bit-reversed indices: lane 0 sweeps bins [0, N/2) in
    ``N/2``-point bit-reversed order and lane 1 the mirrored bin ``+ N/2``.

    Throughput is a sustained 2 samples/cycle under free flow (the internal FIFOs absorb the
    butterfly rank's half-frame burst and the output re-pairing; the source starts a frame
    only once enough of it is buffered to stream gap-free). ``self.latency`` is the cycles
    from a frame's first accepted input beat to its first output beat. As with the serial SDF
    FFT, the delay-feedback pipeline holds about one frame: frame ``f`` streams out while
    frame ``f + 1`` streams in.

    Only ``n_samples=2`` and the serial FFT's ``scaling="scaled"`` arithmetic (unconditional
    1/2 per stage, 1/N overall) are implemented; P=4 and block-floating-point ("bfp") are
    planned follow-ups.

    Parameters
    ----------
    N : int
        Transform size (power of two >= 8).
    n_samples : int
        Samples per beat; only 2 is supported (P=4 is a planned follow-up).
    twiddle_width : int
        Twiddle-factor width in bits (signed Q1.(W-1)), as in the serial FFT.
    """
    def __init__(self, N=64, n_samples=2, data_width=16, twiddle_width=16, with_csr=True):
        check(N >= 8 and (N & (N - 1)) == 0, "N must be a power of two >= 8.")
        check(n_samples == 2, "n_samples must be 2 (P=4 is a planned follow-up).")
        self.N          = N
        self.n_samples  = n_samples
        self.data_width = data_width
        self.sink   = stream.Endpoint(iq_layout(data_width, n_samples))
        self.source = stream.Endpoint(iq_layout(data_width, n_samples))

        # # #

        nb    = log2_int(N//2)  # Input/output frame is N/2 beats.
        layout = iq_layout(data_width, 2)

        # Sub-frame pipelines: burst-smoothing FIFO -> 2:1 serializer -> serial N/2 FFT core ->
        # 1:2 pairer -> output half-frame buffer. The "s" branch carries the butterfly sums
        # (even bins, first N/4 output beats), the "d" branch the twiddled differences (odd
        # bins, last N/4 beats). FIFO depths cover the deterministic free-flow occupancy
        # (burst N/4 pairs vs 1-pair-per-2-cycle drain/fill: ~N/8) with slack.
        # -----------------------------------------------------------------------------------
        self.fifo_s = stream.SyncFIFO(layout, N//8 + 2)
        self.fifo_d = stream.SyncFIFO(layout, N//8 + 2)
        self.p2s_s  = LiteDSPIQParallelToSerial(n_samples=2, data_width=data_width)
        self.p2s_d  = LiteDSPIQParallelToSerial(n_samples=2, data_width=data_width)
        self.fft_s  = LiteDSPFFT(N//2, data_width=data_width, twiddle_width=twiddle_width,
            scaling="scaled", with_csr=False)
        self.fft_d  = LiteDSPFFT(N//2, data_width=data_width, twiddle_width=twiddle_width,
            scaling="scaled", with_csr=False)
        self.s2p_s  = LiteDSPIQSerialToParallel(n_samples=2, data_width=data_width)
        self.s2p_d  = LiteDSPIQSerialToParallel(n_samples=2, data_width=data_width)
        self.buf_s  = stream.SyncFIFO(layout, N//4 + 4)
        self.buf_d  = stream.SyncFIFO(layout, N//4 + 4)

        # Butterfly rank (serial stage 0, two butterflies/beat).
        # ------------------------------------------------------
        # Beats 0..N/4-1 of a frame store x[0..N/2-1] in the lane delay line; beats N/4..N/2-1
        # pair the delayed x[p], x[p+1] with the current x[p+N/2], x[p+N/2+1] and emit one
        # sum pair and one twiddled difference pair per beat (a 2-lane burst on both branches
        # during the compute half — average one sample/cycle per branch).
        s_pair = stream.Endpoint(layout)
        d_pair = stream.Endpoint(layout)

        adv  = Signal()  # Butterfly rank advances (both branch outputs free or consumed).
        xfer = Signal()  # An input beat is consumed this cycle.
        self.comb += [
            adv.eq((s_pair.ready | ~s_pair.valid) & (d_pair.ready | ~d_pair.valid)),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        cnt = Signal(nb)  # Beat position in the input frame (framing is positional).
        c   = Signal()    # 0: store half, 1: compute half.
        self.sync += If(xfer, cnt.eq(cnt + 1))
        self.comb += c.eq(cnt[-1])
        addr = cnt[:-1]

        # Lane delay line (both lanes of I and of Q packed per word), depth N/4: written during
        # the store half, read (async) during the compute half — a true N/2-sample delay.
        mem_i = Memory(2*data_width, N//4)
        mem_q = Memory(2*data_width, N//4)
        wp_i, wp_q = mem_i.get_port(write_capable=True), mem_q.get_port(write_capable=True)
        rp_i, rp_q = mem_i.get_port(async_read=True),    mem_q.get_port(async_read=True)
        self.specials += mem_i, mem_q, wp_i, wp_q, rp_i, rp_q
        self.comb += [
            wp_i.adr.eq(addr), wp_i.dat_w.eq(self.sink.i), wp_i.we.eq(xfer & ~c),
            wp_q.adr.eq(addr), wp_q.dat_w.eq(self.sink.q), wp_q.we.eq(xfer & ~c),
            rp_i.adr.eq(addr), rp_q.adr.eq(addr),
        ]

        # Two butterflies per beat: lane k handles p = 2*addr + k, with the serial stage-0
        # arithmetic (sum scaled by 1/2; difference times the quantized W_N^p twiddle, rescaled
        # by the twiddle fraction + 1/2). The stage-0 D = N/2 twiddle ROM is split into even/odd
        # entries so each lane reads its own depth-N/4 ROM at addr.
        cos_init = _twiddle_rom(N//2, math.cos, twiddle_width)
        sin_init = _twiddle_rom(N//2, math.sin, twiddle_width)
        s_lanes  = iq_lanes(s_pair,    data_width, 2)
        d_lanes  = iq_lanes(d_pair,    data_width, 2)
        x_lanes  = iq_lanes(self.sink, data_width, 2)
        for k in range(2):
            cos_rom = Memory(twiddle_width, N//4, init=cos_init[k::2])
            sin_rom = Memory(twiddle_width, N//4, init=sin_init[k::2])
            cos_rp  = cos_rom.get_port(async_read=True)
            sin_rp  = sin_rom.get_port(async_read=True)
            self.specials += cos_rom, sin_rom, cos_rp, sin_rp
            self.comb += [cos_rp.adr.eq(addr), sin_rp.adr.eq(addr)]
            tr, ti = Signal((twiddle_width, True)), Signal((twiddle_width, True))
            self.comb += [tr.eq(cos_rp.dat_r), ti.eq(sin_rp.dat_r)]
            ar, ai = Signal((data_width, True)), Signal((data_width, True))  # x[p] (delayed).
            br, bi = Signal((data_width, True)), Signal((data_width, True))  # x[p + N/2].
            self.comb += [
                ar.eq(rp_i.dat_r[k*data_width:(k + 1)*data_width]),
                ai.eq(rp_q.dat_r[k*data_width:(k + 1)*data_width]),
                br.eq(x_lanes[k][0]),
                bi.eq(x_lanes[k][1]),
            ]
            sum_i, _ = scaled(ar + br, 1, data_width)
            sum_q, _ = scaled(ai + bi, 1, data_width)
            dr, di   = Signal((data_width + 1, True)), Signal((data_width + 1, True))
            self.comb += [dr.eq(ar - br), di.eq(ai - bi)]
            diff_i, _ = scaled(dr*tr - di*ti, twiddle_width, data_width)
            diff_q, _ = scaled(dr*ti + di*tr, twiddle_width, data_width)
            self.sync += If(adv,
                s_lanes[k][0].eq(sum_i),  s_lanes[k][1].eq(sum_q),
                d_lanes[k][0].eq(diff_i), d_lanes[k][1].eq(diff_q),
            )
        self.sync += If(adv,
            s_pair.valid.eq(self.sink.valid & c),
            d_pair.valid.eq(self.sink.valid & c),
        )

        # Branch datapaths.
        # -----------------
        # The serial core outputs its first frame after N/2 - 1 fill (delay-feedback) beats
        # marked valid; those are dropped so the pairer/buffer see frame-aligned data only.
        self.comb += [
            s_pair.connect(self.fifo_s.sink),
            d_pair.connect(self.fifo_d.sink),
            self.fifo_s.source.connect(self.p2s_s.sink),
            self.fifo_d.source.connect(self.p2s_d.sink),
            self.p2s_s.source.connect(self.fft_s.sink),
            self.p2s_d.source.connect(self.fft_d.sink),
            self.s2p_s.source.connect(self.buf_s.sink),
            self.s2p_d.source.connect(self.buf_d.sink),
        ]
        for core, s2p in [(self.fft_s, self.s2p_s), (self.fft_d, self.s2p_d)]:
            skip = Signal(max=N//2)
            done = Signal()
            self.comb += [
                done.eq(skip == (N//2 - 1)),
                If(done,
                    core.source.connect(s2p.sink),
                ).Else(
                    core.source.ready.eq(1),
                ),
            ]
            self.sync += If(~done & core.source.valid, skip.eq(skip + 1))

        # Output scheduler: N/4 beats from the sum branch (even bins), then N/4 from the
        # difference branch (odd bins), with positional first/last framing. A frame starts once
        # enough sum pairs are buffered to stream gap-free at one beat/cycle in free flow
        # (pairs keep arriving at one per two cycles while the frame drains); once streaming,
        # frames are emitted back-to-back.
        # ------------------------------------------------------------------------------------
        threshold = min(N//8 + 2, N//4)
        out_cnt   = Signal(nb)
        active    = Signal()
        sel       = Signal()
        self.comb += [
            sel.eq(out_cnt[-1]),
            If(active,
                If(~sel,
                    self.source.valid.eq(self.buf_s.source.valid),
                    self.source.i.eq(self.buf_s.source.i),
                    self.source.q.eq(self.buf_s.source.q),
                    self.buf_s.source.ready.eq(self.source.ready),
                ).Else(
                    self.source.valid.eq(self.buf_d.source.valid),
                    self.source.i.eq(self.buf_d.source.i),
                    self.source.q.eq(self.buf_d.source.q),
                    self.buf_d.source.ready.eq(self.source.ready),
                ),
                self.source.first.eq(out_cnt == 0),
                self.source.last.eq(out_cnt == (N//2 - 1)),
            ),
        ]
        self.sync += [
            If(~active,
                If(self.buf_s.level >= threshold, active.eq(1)),
            ).Elif(self.source.valid & self.source.ready,
                out_cnt.eq(out_cnt + 1),
            ),
        ]

        # Frame latency (free flow): first accepted input beat of a frame to its first output
        # beat. Butterfly-rank fill (N/4) + FIFO/serializer entry (3) + sub-core register
        # pipeline (log2(N/2)) and delay-feedback fill (N/2 - 1) + re-pairing of the first
        # `threshold` pairs at one per two cycles (2*threshold + 1) + scheduler start (1).
        # Pinned cycle-exact against simulation by test_fft_parallel.
        self.latency = 3*N//4 + 2*threshold + log2_int(N) + 2

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._latency = CSRStatus(32, reset=self.latency, name="latency",
            description="FFT pipeline latency (cycles from frame start to first output).")
