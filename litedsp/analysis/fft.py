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
    compute half the butterfly sum is output and the twiddled difference is stored. Every
    output is scaled by 1/2 (round + saturate), giving an overall 1/N scaled FFT.
    """
    def __init__(self, N, stage, data_width=16, twiddle_width=16, inverse=False):
        D      = N >> (stage + 1)
        dbits  = D.bit_length() - 1          # log2(D); 0 for D == 1.
        self.D          = D
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        adv  = Signal()  # Pipeline advances (output slot free or being consumed).
        xfer = Signal()  # An input sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Phase counter: c selects store(0)/compute(1), p indexes the twiddle.
        # --------------------------------------------------------------------
        counter = Signal(dbits + 1)
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

        # Butterfly: sum (output), difference (twiddled, stored), both scaled by 1/2.
        # ---------------------------------------------------------------------------
        sum_i, _ = scaled(fr + xr, 1, data_width)
        sum_q, _ = scaled(fi + xi, 1, data_width)
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
            diff_i, _  = scaled(dr*tr - di*ti, tw_shift, data_width)
            diff_q, _  = scaled(dr*ti + di*tr, tw_shift, data_width)
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

        # Output register + valid pipeline (1 stage).
        # -------------------------------------------
        self.sync += If(adv,
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            self.source.valid.eq(self.sink.valid),
        )

# FFT (Radix-2 SDF) --------------------------------------------------------------------------------

class LiteDSPFFT(LiteXModule):
    """Streaming radix-2 SDF FFT, ``N`` points (power of two), 1 sample/cycle.

    Cascades ``log2(N)`` :class:`LiteDSPFFTStage`s. Output is a 1/N-scaled FFT in **bit-reversed**
    order (use :func:`bit_reverse` to reorder). ``self.latency`` is the cycles from the first
    input sample of a frame to its first output sample.
    """
    def __init__(self, N, data_width=16, twiddle_width=16, inverse=False, with_csr=True):
        check((N & (N - 1)) == 0, "N must be a power of two.")
        self.N          = N
        self.bits       = N.bit_length() - 1
        self.data_width = data_width
        self.inverse    = inverse
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Stage cascade: sink -> stage0 -> ... -> stage(log2(N)-1) -> source.
        self.stages = []
        last = self.sink
        for k in range(self.bits):
            stage = LiteDSPFFTStage(N, k, data_width=data_width, twiddle_width=twiddle_width, inverse=inverse)
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
