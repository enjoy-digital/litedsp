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

from litedsp.common import check, iq_layout, scaled

# Helpers ------------------------------------------------------------------------------------------

def bit_reverse(k, bits):
    """Bit-reverse the ``bits``-bit integer ``k`` (FFT output is in bit-reversed order)."""
    r = 0
    for _ in range(bits):
        r = (r << 1) | (k & 1)
        k >>= 1
    return r

def _twiddle_rom(D, func, twiddle_width):
    """ROM of ``func(-pi*p/D)`` for p in 0..D-1, signed Q1.(W-1)."""
    scale = (1 << (twiddle_width - 1)) - 1
    mask  = (1 << twiddle_width) - 1
    return [int(round(func(-math.pi*p/D)*scale)) & mask for p in range(D)]

# FFT Stage (Radix-2 SDF, DIF) ---------------------------------------------------------------------

class LiteDSPFFTStage(LiteXModule):
    """One radix-2 single-path delay-feedback (SDF) DIF stage.

    Delay-feedback length ``D = N >> (stage+1)``. During the store half of each 2D block the
    input is buffered and the previously-computed (twiddled) difference is output; during the
    compute half the butterfly sum is output and the twiddled difference is stored.

    With ``scaling="scaled"`` every output is scaled by 1/2 (round + saturate), giving an
    overall 1/N scaled FFT. With ``scaling="bfp"`` (block floating point) the 1/2 scaling is
    conditional, per frame, with a one-frame-delayed decision: **all** butterflies of frame k
    are scaled by 1/2 iff any butterfly output of frame k-1 overflowed the ``data_width``
    range *unshifted* (the sum ``a + b`` is checked directly; the twiddled difference is
    checked after its ``twiddle_width - 1`` product rounding). Frame 0 is unscaled; a frame
    whose (predicted) decision under-estimates growth saturates, exactly like "scaled" mode.
    When every stage of a cascade shifts, "bfp" arithmetic is bit-identical to "scaled"
    (same rounding position). The endpoints gain a 5-bit ``exp`` param field carrying the
    running per-frame exponent: ``source.exp = sink.exp + shift`` of the frame each output
    beat belongs to (the stage skews frames by D beats; the boundary is tracked so ``exp``
    changes exactly on the output frame boundary).
    """
    def __init__(self, N, stage, data_width=16, twiddle_width=16, inverse=False, scaling="scaled"):
        check(scaling in ("scaled", "bfp"), "scaling must be 'scaled' or 'bfp'.")
        D      = N >> (stage + 1)
        dbits  = D.bit_length() - 1          # log2(D); 0 for D == 1.
        nbits  = N.bit_length() - 1          # log2(N).
        bfp    = (scaling == "bfp")
        self.D          = D
        self.data_width = data_width
        self.latency    = 1
        layout = iq_layout(data_width)
        if bfp:
            layout = stream.EndpointDescription(layout, [("exp", 5)])
        self.sink   = stream.Endpoint(layout)
        self.source = stream.Endpoint(layout)

        # # #

        adv  = Signal()  # Pipeline advances (output slot free or being consumed).
        xfer = Signal()  # An input sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Phase counter: c selects store(0)/compute(1), p indexes the twiddle. In "bfp" mode
        # the counter is widened to count mod N (per-frame shift/exponent tracking) and reset-
        # offset by the stage's accumulated input skew (2*D mod N) so counter == 0 falls on
        # true frame starts; c/p (low bits) are unaffected since the skew is a multiple of 2*D.
        # -------------------------------------------------------------------------------------
        counter = Signal(nbits, reset=(2*D) % N) if bfp else Signal(dbits + 1)
        c       = Signal()
        self.sync += If(xfer, counter.eq(counter + 1))
        self.comb += c.eq(counter[dbits])
        p = counter[:dbits] if dbits > 0 else None

        # Delay-feedback line (I and Q), read-before-write for a true D-deep delay.
        # A depth-1 delay is a register pair; deeper delays use a circular memory.
        # ------------------------------------------------------------------------
        fr, fi      = Signal((data_width, True)), Signal((data_width, True))
        store_i     = Signal((data_width, True))
        store_q     = Signal((data_width, True))
        xr, xi      = self.sink.i, self.sink.q
        if D == 1:
            reg_i, reg_q = Signal((data_width, True)), Signal((data_width, True))
            self.comb += [fr.eq(reg_i), fi.eq(reg_q)]
            self.sync += If(xfer, reg_i.eq(store_i), reg_q.eq(store_q))
        else:
            mem_i = Memory(data_width, D)
            mem_q = Memory(data_width, D)
            wp_i, wp_q = mem_i.get_port(write_capable=True), mem_q.get_port(write_capable=True)
            rp_i, rp_q = mem_i.get_port(async_read=True),    mem_q.get_port(async_read=True)
            self.specials += mem_i, mem_q, wp_i, wp_q, rp_i, rp_q
            ptr = Signal(max=D)
            self.comb += [
                rp_i.adr.eq(ptr), rp_q.adr.eq(ptr), wp_i.adr.eq(ptr), wp_q.adr.eq(ptr),
                fr.eq(rp_i.dat_r), fi.eq(rp_q.dat_r),
                wp_i.dat_w.eq(store_i), wp_i.we.eq(xfer),
                wp_q.dat_w.eq(store_q), wp_q.we.eq(xfer),
            ]
            self.sync += If(xfer, If(ptr == (D - 1), ptr.eq(0)).Else(ptr.eq(ptr + 1)))

        # Butterfly: sum (output), difference (twiddled, stored). "scaled": both unconditionally
        # scaled by 1/2. "bfp": the 1/2 scaling is applied only when this frame's shift decision
        # sh is set; the unshifted overflow flags feed the next frame's decision (see below).
        # --------------------------------------------------------------------------------------
        # Route sums through explicit full-width Signals. In emitted Verilog an inline
        # ``fr + xr`` is otherwise sized to the eventual data_width-bit assignment context,
        # dropping its carry bit before rounding; Migen simulation evaluates the full width.
        sum_i_full = Signal((data_width + 1, True))
        sum_q_full = Signal((data_width + 1, True))
        self.comb += [sum_i_full.eq(fr + xr), sum_q_full.eq(fi + xi)]
        if bfp:
            sh  = Signal()  # 1/2 scaling applied to the current frame's butterflies.
            det = Signal()  # Sticky unshifted-overflow detector (current frame).
            sum_i0, sovf_i = scaled(sum_i_full, 0, data_width)
            sum_q0, sovf_q = scaled(sum_q_full, 0, data_width)
            sum_i1, _      = scaled(sum_i_full, 1, data_width)
            sum_q1, _      = scaled(sum_q_full, 1, data_width)
            sum_i, sum_q   = Mux(sh, sum_i1, sum_i0), Mux(sh, sum_q1, sum_q0)
        else:
            sum_i, _ = scaled(sum_i_full, 1, data_width)
            sum_q, _ = scaled(sum_q_full, 1, data_width)
        dr, di   = Signal((data_width + 1, True)), Signal((data_width + 1, True))
        self.comb += [dr.eq(fr - xr), di.eq(fi - xi)]
        if D > 1:
            sin_func = (lambda a: -math.sin(a)) if inverse else math.sin   # exp(+j) for inverse.
            cos_rom = Memory(twiddle_width, D, init=_twiddle_rom(D, math.cos, twiddle_width))
            sin_rom = Memory(twiddle_width, D, init=_twiddle_rom(D, sin_func, twiddle_width))
            cos_rp  = cos_rom.get_port(async_read=True)
            sin_rp  = sin_rom.get_port(async_read=True)
            self.specials += cos_rom, sin_rom, cos_rp, sin_rp
            self.comb += [cos_rp.adr.eq(p), sin_rp.adr.eq(p)]
            tr, ti = Signal((twiddle_width, True)), Signal((twiddle_width, True))
            self.comb += [tr.eq(cos_rp.dat_r), ti.eq(sin_rp.dat_r)]
            # diff * twiddle, rescaled by twiddle frac + 1 (stage 1/2).
            tw_shift   = (twiddle_width - 1) + 1
            if bfp:
                prod_i = Signal((data_width + twiddle_width + 2, True))
                prod_q = Signal((data_width + twiddle_width + 2, True))
                self.comb += [prod_i.eq(dr*tr - di*ti), prod_q.eq(dr*ti + di*tr)]
                diff_i0, dovf_i = scaled(prod_i, tw_shift - 1, data_width)
                diff_q0, dovf_q = scaled(prod_q, tw_shift - 1, data_width)
                diff_i1, _      = scaled(prod_i, tw_shift, data_width)
                diff_q1, _      = scaled(prod_q, tw_shift, data_width)
                diff_i, diff_q  = Mux(sh, diff_i1, diff_i0), Mux(sh, diff_q1, diff_q0)
            else:
                # Full-width product Signals: an inline product would be sized by its
                # data_width-bit assignment context in the emitted Verilog and silently
                # truncate (found by Verilator co-simulation; Migen's simulator evaluates
                # full-width). The bfp path above is immune: it already routes the products
                # through explicitly sized prod_i/prod_q.
                prod_i = Signal((data_width + twiddle_width + 2, True))
                prod_q = Signal((data_width + twiddle_width + 2, True))
                self.comb += [prod_i.eq(dr*tr - di*ti), prod_q.eq(dr*ti + di*tr)]
                diff_i, _  = scaled(prod_i, tw_shift, data_width)
                diff_q, _  = scaled(prod_q, tw_shift, data_width)
        else:
            if bfp:                                  # Last stage: trivial twiddle (W^0 = 1).
                diff_i0, dovf_i = scaled(dr, 0, data_width)
                diff_q0, dovf_q = scaled(di, 0, data_width)
                diff_i1, _      = scaled(dr, 1, data_width)
                diff_q1, _      = scaled(di, 1, data_width)
                diff_i, diff_q  = Mux(sh, diff_i1, diff_i0), Mux(sh, diff_q1, diff_q0)
            else:
                diff_i, _  = scaled(dr, 1, data_width)   # Last stage: trivial twiddle (W^0 = 1).
                diff_q, _  = scaled(di, 1, data_width)

        out_i = Signal((data_width, True))
        out_q = Signal((data_width, True))
        self.comb += [
            out_i.eq(  Mux(c, sum_i,  fr)),   # compute: sum; store: delayed value.
            out_q.eq(  Mux(c, sum_q,  fi)),
            store_i.eq(Mux(c, diff_i, xr)),   # compute: twiddled diff; store: new input.
            store_q.eq(Mux(c, diff_q, xi)),
        ]

        # BFP per-frame control: shift decision (one-frame-delayed) + exponent chaining.
        # -------------------------------------------------------------------------------
        if bfp:
            ovf     = Signal()   # Some butterfly output of this beat overflows unshifted.
            exp_in  = Signal(5)  # Input exponent of the current frame (latched at frame start).
            exp_prv = Signal(5)  # Output exponent of the previous frame.
            exp_cur = Signal(5)  # Output exponent of the current frame.
            self.comb += [
                ovf.eq(c & (sovf_i | sovf_q | dovf_i | dovf_q)),
                exp_cur.eq(exp_in + sh),
            ]
            self.sync += If(xfer,
                If(counter == 0, exp_in.eq(self.sink.exp)),
                If(counter == (N - 1),
                    sh.eq(det | ovf),
                    det.eq(0),
                    exp_prv.eq(exp_cur),
                ).Elif(ovf,
                    det.eq(1),
                ),
            )

        # Output register + valid pipeline (1 stage).
        # -------------------------------------------
        self.sync += If(adv,
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            self.source.valid.eq(self.sink.valid),
        )
        if bfp:
            # Frame k's outputs occupy counter in [D, N) + [0, D) of the next wrap (D-beat skew).
            self.sync += If(adv, self.source.exp.eq(Mux(counter < D, exp_prv, exp_cur)))

# FFT (Radix-2 SDF) --------------------------------------------------------------------------------

class LiteDSPFFT(LiteXModule):
    """Streaming radix-2 SDF FFT, ``N`` points (power of two), 1 sample/cycle.

    Cascades ``log2(N)`` :class:`LiteDSPFFTStage`s. Output is in **bit-reversed** order (use
    :func:`bit_reverse` to reorder), scaled per ``scaling`` below. ``self.latency`` is the
    cycles from the first input sample of a frame to its first output sample.

    With ``scaling="bfp"`` each stage decides its 1/2 scaling per frame (from the previous
    frame's guard-bit occupancy, see :class:`LiteDSPFFTStage`) and the source endpoint gains a
    5-bit ``exp`` **param** field (constant across each output frame, like ``first``/``last``
    it travels beat-aligned with the payload) carrying the total number of halvings applied:
    ``output = DFT(x) / 2**exp`` up to fixed-point rounding/saturation, with
    ``exp in [0, log2(N)]`` (``exp == log2(N)`` reproduces "scaled"-mode arithmetic
    bit-exactly). Small signals keep up to ``log2(N)`` extra amplitude bits (~6 dB each).
    Downstream analysis blocks (PSD/magnitude) ignore param fields and consume BFP frames
    unnormalized; exp-aware consumption lands with the SSR/consumer work — until then,
    connect a BFP source to exp-less sinks with ``connect(..., omit={"exp"})``.

    Parameters
    ----------
    twiddle_width : int
        Twiddle-factor width in bits (signed Q1.(W-1)); sets the per-stage twiddle ROM width,
        the complex-multiplier size, and the coefficient-quantization noise floor.
    inverse : bool
        Compute the inverse FFT (conjugated, exp(+j) twiddles); output remains 1/N-scaled.
    scaling : str
        Output scaling. ``"scaled"`` (default): unconditional 1/2 per stage (1/N overall).
        ``"bfp"``: block floating point — per-frame conditional scaling, per-frame exponent
        on a 5-bit ``exp`` source param field (see overview above).
    """
    def __init__(self, N, data_width=16, twiddle_width=16, inverse=False, scaling="scaled", with_csr=True):
        check(N >= 2 and (N & (N - 1)) == 0, "N must be a power of two >= 2.")
        check(scaling in ("scaled", "bfp"), "scaling must be 'scaled' or 'bfp'.")
        self.N          = N
        self.bits       = N.bit_length() - 1
        self.data_width = data_width
        self.inverse    = inverse
        self.scaling    = scaling
        self.sink = stream.Endpoint(iq_layout(data_width))
        if scaling == "bfp":
            self.source = stream.Endpoint(stream.EndpointDescription(iq_layout(data_width), [("exp", 5)]))
        else:
            self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Stage cascade: sink -> stage0 -> ... -> stage(log2(N)-1) -> source. In "bfp" mode the
        # 5-bit exp param field chains through the stages (stage0's input exponent is 0) and
        # accumulates each stage's per-frame shift into the source's per-frame exponent.
        self.stages = []
        last = self.sink
        for k in range(self.bits):
            stage = LiteDSPFFTStage(N, k, data_width=data_width, twiddle_width=twiddle_width,
                inverse=inverse, scaling=scaling)
            self.add_module(name=f"stage{k}", module=stage)
            self.comb += last.connect(stage.sink)
            self.stages.append(stage)
            last = stage.source
        self.comb += last.connect(self.source)

        # Frame latency (measured): the combined delay-feedback fill, N-1 cycles. The per-stage
        # output registers are not in the forward path, so they do not add latency.
        self.latency = N - 1

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._latency = CSRStatus(32, reset=self.latency, name="latency",
            description="FFT pipeline latency (cycles from frame start to first output).")
