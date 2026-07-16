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

# Native Parallel FFT Stage ------------------------------------------------------------------------

class _LiteDSPFFTVectorStage(LiteXModule):
    """One radix-2 SDF stage advanced by ``n_samples`` consecutive samples per clock.

    This is the serial :class:`LiteDSPFFTStage` recurrence unrolled across the lanes of one
    beat.  Each stage keeps one shared delay-feedback line and therefore avoids the branch
    FIFOs, serializers and duplicated serial cores used by the original split architecture.
    A register between every FFT rank keeps the cascade elastic and limits the combinational
    path to one rank.  The few final ranks whose delay is shorter than a beat forward their
    state within the beat, exactly matching consecutive serial updates.
    """
    def __init__(self, N, stage, n_samples=2, data_width=16, twiddle_width=16):
        D     = N >> (stage + 1)
        dbits = D.bit_length() - 1
        pbits = n_samples.bit_length() - 1
        self.D       = D
        self.latency = 1
        self.sink    = stream.Endpoint(iq_layout(data_width, n_samples))
        self.source  = stream.Endpoint(iq_layout(data_width, n_samples))

        # # #

        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        counter = Signal(dbits + 1)
        if D >= n_samples:
            self.sync += If(xfer, counter.eq(counter + n_samples))

        in_lanes  = iq_lanes(self.sink,   data_width, n_samples)
        out_lanes = iq_lanes(self.source, data_width, n_samples)

        # For D >= P, all lanes are in the same store/compute half and address distinct
        # feedback entries. Split each asynchronous twiddle ROM into P banks and prefetch
        # the next beat's coefficients, removing counter -> ROM from the multiplier path.
        if D >= n_samples:
            c = counter[dbits]
            depth = D//n_samples

            # Store all P feedback lanes in one word. Deeper ranks infer distributed RAM with
            # one async read and one write port, just like the serial SDF delay; D=P is a
            # single packed register. This avoids a large register-array read/write mux.
            feedback_i = Signal(n_samples*data_width)
            feedback_q = Signal(n_samples*data_width)
            store_word_i = Signal(n_samples*data_width)
            store_word_q = Signal(n_samples*data_width)
            if depth == 1:
                reg_i = Signal(n_samples*data_width)
                reg_q = Signal(n_samples*data_width)
                self.comb += [feedback_i.eq(reg_i), feedback_q.eq(reg_q)]
                self.sync += If(xfer, reg_i.eq(store_word_i), reg_q.eq(store_word_q))
            else:
                mem_i = Memory(n_samples*data_width, depth)
                mem_q = Memory(n_samples*data_width, depth)
                wp_i = mem_i.get_port(write_capable=True)
                wp_q = mem_q.get_port(write_capable=True)
                rp_i = mem_i.get_port(async_read=True)
                rp_q = mem_q.get_port(async_read=True)
                self.specials += mem_i, mem_q, wp_i, wp_q, rp_i, rp_q
                addr = counter[pbits:dbits]
                self.comb += [
                    rp_i.adr.eq(addr), rp_q.adr.eq(addr),
                    wp_i.adr.eq(addr), wp_q.adr.eq(addr),
                    feedback_i.eq(rp_i.dat_r), feedback_q.eq(rp_q.dat_r),
                    wp_i.dat_w.eq(store_word_i), wp_q.dat_w.eq(store_word_q),
                    wp_i.we.eq(xfer), wp_q.we.eq(xfer),
                ]
            twiddles = []
            if D > 1:
                cos_init = _twiddle_rom(D, math.cos, twiddle_width)
                sin_init = _twiddle_rom(D, math.sin, twiddle_width)
                next_counter = Signal(dbits + 1)
                self.comb += next_counter.eq(counter + n_samples)
                for k in range(n_samples):
                    depth   = D//n_samples
                    if depth > 1:
                        cos_rom = Memory(twiddle_width, depth, init=cos_init[k::n_samples])
                        sin_rom = Memory(twiddle_width, depth, init=sin_init[k::n_samples])
                        cos_rp  = cos_rom.get_port(async_read=True)
                        sin_rp  = sin_rom.get_port(async_read=True)
                        self.specials += cos_rom, sin_rom, cos_rp, sin_rp
                        self.comb += [
                            cos_rp.adr.eq(next_counter[pbits:dbits]),
                            sin_rp.adr.eq(next_counter[pbits:dbits]),
                        ]
                        tr = Signal((twiddle_width, True), reset=cos_init[k])
                        ti = Signal((twiddle_width, True), reset=sin_init[k])
                        self.sync += If(xfer, tr.eq(cos_rp.dat_r), ti.eq(sin_rp.dat_r))
                    else:
                        sign = 1 << (twiddle_width - 1)
                        tr_v = cos_init[k] - (1 << twiddle_width) if cos_init[k] & sign else cos_init[k]
                        ti_v = sin_init[k] - (1 << twiddle_width) if sin_init[k] & sign else sin_init[k]
                        tr = Constant(tr_v, (twiddle_width, True))
                        ti = Constant(ti_v, (twiddle_width, True))
                    twiddles.append((tr, ti))

            for k in range(n_samples):
                xr, xq = Signal((data_width, True)), Signal((data_width, True))
                fr, fq = Signal((data_width, True)), Signal((data_width, True))
                self.comb += [
                    xr.eq(in_lanes[k][0]), xq.eq(in_lanes[k][1]),
                    fr.eq(feedback_i[k*data_width:(k + 1)*data_width]),
                    fq.eq(feedback_q[k*data_width:(k + 1)*data_width]),
                ]
                sum_i_full = Signal((data_width + 1, True))
                sum_q_full = Signal((data_width + 1, True))
                dr = Signal((data_width + 1, True))
                dq = Signal((data_width + 1, True))
                self.comb += [
                    sum_i_full.eq(fr + xr), sum_q_full.eq(fq + xq),
                    dr.eq(fr - xr), dq.eq(fq - xq),
                ]
                sum_i, _ = scaled(sum_i_full, 1, data_width)
                sum_q, _ = scaled(sum_q_full, 1, data_width)
                if D > 1:
                    tr, ti = twiddles[k]
                    prod_i = Signal((data_width + twiddle_width + 2, True))
                    prod_q = Signal((data_width + twiddle_width + 2, True))
                    self.comb += [prod_i.eq(dr*tr - dq*ti), prod_q.eq(dr*ti + dq*tr)]
                    diff_i, _ = scaled(prod_i, twiddle_width, data_width)
                    diff_q, _ = scaled(prod_q, twiddle_width, data_width)
                else:
                    diff_i, _ = scaled(dr, 1, data_width)
                    diff_q, _ = scaled(dq, 1, data_width)
                store_i = Mux(c, diff_i, xr)
                store_q = Mux(c, diff_q, xq)
                self.comb += [
                    store_word_i[k*data_width:(k + 1)*data_width].eq(store_i),
                    store_word_q[k*data_width:(k + 1)*data_width].eq(store_q),
                ]
                self.sync += If(adv,
                    out_lanes[k][0].eq(Mux(c, sum_i, fr)),
                    out_lanes[k][1].eq(Mux(c, sum_q, fq)),
                )

        # For D < P a beat contains several complete 2D blocks. Symbolically forward each
        # feedback update to the following lane(s), then commit the final state at the edge.
        # This is a small late-rank network (at most two dependent butterflies for P=4).
        else:
            state_i = [Signal((data_width, True), name=f"state_i{p}") for p in range(D)]
            state_q = [Signal((data_width, True), name=f"state_q{p}") for p in range(D)]
            cur_i = list(state_i)
            cur_q = list(state_q)
            for k in range(n_samples):
                p = k % D
                c = (k // D) & 1
                xr = Signal((data_width, True))
                xq = Signal((data_width, True))
                self.comb += [xr.eq(in_lanes[k][0]), xq.eq(in_lanes[k][1])]
                fr, fq = cur_i[p], cur_q[p]
                if c:
                    sum_i_full = Signal((data_width + 1, True))
                    sum_q_full = Signal((data_width + 1, True))
                    dr = Signal((data_width + 1, True))
                    dq = Signal((data_width + 1, True))
                    self.comb += [
                        sum_i_full.eq(fr + xr), sum_q_full.eq(fq + xq),
                        dr.eq(fr - xr), dq.eq(fq - xq),
                    ]
                    out_i, _ = scaled(sum_i_full, 1, data_width)
                    out_q, _ = scaled(sum_q_full, 1, data_width)
                    if D > 1:
                        cos_init = _twiddle_rom(D, math.cos, twiddle_width)
                        sin_init = _twiddle_rom(D, math.sin, twiddle_width)
                        sign = 1 << (twiddle_width - 1)
                        tr_v = cos_init[p] - (1 << twiddle_width) if cos_init[p] & sign else cos_init[p]
                        ti_v = sin_init[p] - (1 << twiddle_width) if sin_init[p] & sign else sin_init[p]
                        tr = Constant(tr_v, (twiddle_width, True))
                        ti = Constant(ti_v, (twiddle_width, True))
                        prod_i = Signal((data_width + twiddle_width + 2, True))
                        prod_q = Signal((data_width + twiddle_width + 2, True))
                        self.comb += [prod_i.eq(dr*tr - dq*ti), prod_q.eq(dr*ti + dq*tr)]
                        next_i, _ = scaled(prod_i, twiddle_width, data_width)
                        next_q, _ = scaled(prod_q, twiddle_width, data_width)
                    else:
                        next_i, _ = scaled(dr, 1, data_width)
                        next_q, _ = scaled(dq, 1, data_width)
                else:
                    out_i, out_q = fr, fq
                    next_i, next_q = xr, xq
                self.sync += If(adv,
                    out_lanes[k][0].eq(out_i), out_lanes[k][1].eq(out_q),
                )
                cur_i[p], cur_q[p] = next_i, next_q
            for p in range(D):
                self.sync += If(xfer, state_i[p].eq(cur_i[p]), state_q[p].eq(cur_q[p]))

        self.sync += If(adv, self.source.valid.eq(self.sink.valid))


class LiteDSPNativeParallelFFT(LiteXModule):
    """Native vector-SDF FFT with a sustained P=2 or P=4 samples/clock."""
    def __init__(self, N=64, n_samples=2, data_width=16, twiddle_width=16, with_csr=True):
        check(N >= 8 and (N & (N - 1)) == 0, "N must be a power of two >= 8.")
        check(n_samples in (2, 4), "native n_samples must be 2 or 4.")
        check(N >= 2*n_samples, "N must be at least twice n_samples.")
        self.N          = N
        self.n_samples  = n_samples
        self.data_width = data_width
        self.core_architecture         = "native"
        self.implementation            = "native"
        self.peak_samples_per_cycle    = n_samples
        self.average_samples_per_cycle = n_samples
        self.sink   = stream.Endpoint(iq_layout(data_width, n_samples))
        self.source = stream.Endpoint(iq_layout(data_width, n_samples))

        # # #

        stages = []
        for stage in range(log2_int(N)):
            s = _LiteDSPFFTVectorStage(N, stage, n_samples, data_width, twiddle_width)
            setattr(self.submodules, f"stage{stage}", s)
            stages.append(s)
        self.comb += self.sink.connect(stages[0].sink)
        for a, b in zip(stages, stages[1:]):
            self.comb += a.source.connect(b.sink)

        # The SDF cascade's first valid frame begins at scalar offset N-1. Realign that
        # lane-P-1 sample with the following beat so output frames again contain P samples.
        raw       = stages[-1].source
        raw_lanes = iq_lanes(raw, data_width, n_samples)
        out_lanes = iq_lanes(self.source, data_width, n_samples)
        warm_beats = N//n_samples
        warm       = Signal(max=warm_beats)
        primed     = Signal()
        tail_i     = Signal((data_width, True))
        tail_q     = Signal((data_width, True))
        out_count  = Signal(max=N//n_samples)
        adv        = Signal()
        take       = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            raw.ready.eq(Mux(primed, adv, 1)),
            take.eq(raw.valid & raw.ready),
        ]
        self.sync += [
            If(~primed,
                self.source.valid.eq(0),
                If(take,
                    If(warm == (warm_beats - 1),
                        tail_i.eq(raw_lanes[-1][0]),
                        tail_q.eq(raw_lanes[-1][1]),
                        primed.eq(1),
                    ).Else(
                        warm.eq(warm + 1),
                    ),
                ),
            ).Elif(adv,
                self.source.valid.eq(raw.valid),
                If(raw.valid,
                    out_lanes[0][0].eq(tail_i),
                    out_lanes[0][1].eq(tail_q),
                    *[out_lanes[k][0].eq(raw_lanes[k - 1][0]) for k in range(1, n_samples)],
                    *[out_lanes[k][1].eq(raw_lanes[k - 1][1]) for k in range(1, n_samples)],
                    tail_i.eq(raw_lanes[-1][0]),
                    tail_q.eq(raw_lanes[-1][1]),
                    self.source.first.eq(out_count == 0),
                    self.source.last.eq(out_count == (N//n_samples - 1)),
                    out_count.eq(out_count + 1),
                ),
            ),
        ]

        self.latency = log2_int(N) + N//n_samples + 1
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._latency = CSRStatus(32, reset=self.latency, name="latency",
            description="FFT pipeline latency (cycles from frame start to first output).")

# Parallel FFT (Radix-2 DIF split, 2 samples/cycle) -------------------------------------------------

class LiteDSPParallelFFT(LiteXModule):
    """Streaming ``N``-point FFT at P samples/cycle (super-sample-rate wideband path).

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

    The default ``implementation="split"`` preserves the original P=2 architecture. With
    ``core_architecture="classic"`` it sustains 2 samples/cycle; ``"folded"`` adds a timing
    register to the wide butterfly rank and uses two-cycle serial sub-cores, for a peak width
    of two and an average rate of one sample/cycle.

    ``implementation="native"`` instead advances a single SDF feedback line by P consecutive
    samples per clock. It supports P=2 and P=4, sustains P samples/cycle, eliminates the split
    implementation's branch FIFOs/serializers/duplicated cores, and remains bit-identical to
    the serial FFT on the flattened lane stream. Both implementations currently use the
    serial FFT's ``scaling="scaled"`` arithmetic (1/2 per stage, 1/N overall).

    Parameters
    ----------
    N : int
        Transform size (power of two >= 8).
    n_samples : int
        Samples per beat; 2 for ``"split"``, or 2/4 for ``"native"``.
    twiddle_width : int
        Twiddle-factor width in bits (signed Q1.(W-1)), as in the serial FFT.
    core_architecture : str
        ``"classic"`` for sustained two-sample/cycle throughput, or ``"folded"`` for a
        registered timing-oriented split path with one-sample/cycle average throughput.
    implementation : str
        ``"split"`` (compatibility default) or the scalable ``"native"`` vector-SDF engine.
    """
    def __init__(self, N=64, n_samples=2, data_width=16, twiddle_width=16,
        core_architecture="classic", implementation="split", with_csr=True):
        check(N >= 8 and (N & (N - 1)) == 0, "N must be a power of two >= 8.")
        check(implementation in ("split", "native"),
            "implementation must be 'split' or 'native'.")
        if implementation == "native":
            self.native = LiteDSPNativeParallelFFT(N, n_samples, data_width, twiddle_width,
                with_csr=with_csr)
            self.N          = self.native.N
            self.n_samples  = self.native.n_samples
            self.data_width = self.native.data_width
            self.core_architecture         = self.native.core_architecture
            self.implementation            = implementation
            self.peak_samples_per_cycle    = self.native.peak_samples_per_cycle
            self.average_samples_per_cycle = self.native.average_samples_per_cycle
            self.latency = self.native.latency
            self.sink    = self.native.sink
            self.source  = self.native.source
            return
        check(n_samples == 2, "split n_samples must be 2; use implementation='native' for P=4.")
        check(core_architecture in ("classic", "folded"),
            "core_architecture must be 'classic' or 'folded'.")
        self.N          = N
        self.n_samples  = n_samples
        self.data_width = data_width
        self.core_architecture       = core_architecture
        self.implementation          = implementation
        self.peak_samples_per_cycle  = 2
        self.average_samples_per_cycle = 2 if core_architecture == "classic" else 1
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
        fifo_depth = (N//8 + 2) if core_architecture == "classic" else (N//4 + 2)
        self.fifo_s = stream.SyncFIFO(layout, fifo_depth)
        self.fifo_d = stream.SyncFIFO(layout, fifo_depth)
        self.p2s_s  = LiteDSPIQParallelToSerial(n_samples=2, data_width=data_width)
        self.p2s_d  = LiteDSPIQParallelToSerial(n_samples=2, data_width=data_width)
        self.fft_s  = LiteDSPFFT(N//2, data_width=data_width, twiddle_width=twiddle_width,
            scaling="scaled", architecture=core_architecture, with_csr=False)
        self.fft_d  = LiteDSPFFT(N//2, data_width=data_width, twiddle_width=twiddle_width,
            scaling="scaled", architecture=core_architecture, with_csr=False)
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

        rank_pipeline = (core_architecture == "folded")
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
        if rank_pipeline:
            work_valid = Signal()
            work_c     = Signal()
            self.sync += If(adv,
                work_valid.eq(self.sink.valid),
                If(xfer, work_c.eq(c)),
            )
        for k in range(2):
            cos_rom = Memory(twiddle_width, N//4, init=cos_init[k::2])
            sin_rom = Memory(twiddle_width, N//4, init=sin_init[k::2])
            cos_rp  = cos_rom.get_port(async_read=True)
            sin_rp  = sin_rom.get_port(async_read=True)
            self.specials += cos_rom, sin_rom, cos_rp, sin_rp
            self.comb += [cos_rp.adr.eq(addr), sin_rp.adr.eq(addr)]
            tr, ti = Signal((twiddle_width, True)), Signal((twiddle_width, True))
            ar, ai = Signal((data_width, True)), Signal((data_width, True))  # x[p] (delayed).
            br, bi = Signal((data_width, True)), Signal((data_width, True))  # x[p + N/2].
            sum_i_full = Signal((data_width + 1, True))
            sum_q_full = Signal((data_width + 1, True))
            dr, di   = Signal((data_width + 1, True)), Signal((data_width + 1, True))
            prod_i = Signal((data_width + twiddle_width + 2, True))
            prod_q = Signal((data_width + twiddle_width + 2, True))
            self.comb += [
                tr.eq(cos_rp.dat_r), ti.eq(sin_rp.dat_r),
                ar.eq(rp_i.dat_r[k*data_width:(k + 1)*data_width]),
                ai.eq(rp_q.dat_r[k*data_width:(k + 1)*data_width]),
                br.eq(x_lanes[k][0]), bi.eq(x_lanes[k][1]),
                dr.eq(ar - br), di.eq(ai - bi),
            ]
            if rank_pipeline:
                term_width = data_width + twiddle_width + 1
                prod_rr = Signal((term_width, True))
                prod_ii = Signal((term_width, True))
                prod_ri = Signal((term_width, True))
                prod_ir = Signal((term_width, True))
                self.sync += If(xfer,
                    sum_i_full.eq(ar + br), sum_q_full.eq(ai + bi),
                    prod_rr.eq(dr*tr), prod_ii.eq(di*ti),
                    prod_ri.eq(dr*ti), prod_ir.eq(di*tr),
                )
                self.comb += [
                    prod_i.eq(prod_rr - prod_ii), prod_q.eq(prod_ri + prod_ir),
                ]
            else:
                self.comb += [
                    sum_i_full.eq(ar + br), sum_q_full.eq(ai + bi),
                    prod_i.eq(dr*tr - di*ti), prod_q.eq(dr*ti + di*tr),
                ]
            sum_i, _  = scaled(sum_i_full, 1, data_width)
            sum_q, _  = scaled(sum_q_full, 1, data_width)
            diff_i, _ = scaled(prod_i, twiddle_width, data_width)
            diff_q, _ = scaled(prod_q, twiddle_width, data_width)
            self.sync += If(adv,
                s_lanes[k][0].eq(sum_i),  s_lanes[k][1].eq(sum_q),
                d_lanes[k][0].eq(diff_i), d_lanes[k][1].eq(diff_q),
            )
        self.sync += If(adv,
            s_pair.valid.eq((work_valid & work_c) if rank_pipeline else (self.sink.valid & c)),
            d_pair.valid.eq((work_valid & work_c) if rank_pipeline else (self.sink.valid & c)),
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
        threshold = min(N//8 + 2, N//4) if core_architecture == "classic" else N//4
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
        if core_architecture == "classic":
            self.latency = 3*N//4 + 2*threshold + log2_int(N) + 2
        else:
            # Folded-core latency is pinned by the architecture tests after construction;
            # one extra cycle accounts for the registered wide butterfly rank.
            self.latency = 5*N//4 + 4*threshold + 2*log2_int(N)

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._latency = CSRStatus(32, reset=self.latency, name="latency",
            description="FFT pipeline latency (cycles from frame start to first output).")
