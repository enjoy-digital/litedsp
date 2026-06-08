#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Compact iterative (memory-based) radix-2 FFT.

A single butterfly + in-place RAM processes an N-sample burst in ~N + (N/2)*log2(N) cycles —
far smaller than the pipelined SDF FFT (one complex multiplier) at the cost of throughput. DIT
in-place: the input is written bit-reversed, log2(N) stages of butterflies run, then the
result is read out in natural order. Output is 1/N-scaled (1/2 per stage, round + saturate).
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled

# Helpers ------------------------------------------------------------------------------------------

def _bitrev(k, bits):
    r = 0
    for _ in range(bits):
        r = (r << 1) | (k & 1)
        k >>= 1
    return r

def _tw_rom(N, func, width):
    scale = (1 << (width - 1)) - 1
    mask  = (1 << width) - 1
    return [int(round(func(-2*math.pi*i/N)*scale)) & mask for i in range(N//2)]

# Iterative FFT ------------------------------------------------------------------------------------

class FFTIter(LiteXModule):
    """Iterative in-place radix-2 FFT, ``N`` points, natural-order output."""
    def __init__(self, N, data_width=16, twiddle_width=16, with_csr=True):
        assert (N & (N - 1)) == 0 and N >= 4
        self.N    = N
        S         = N.bit_length() - 1
        self.bits = S
        self.data_width = data_width
        self.latency    = N + (N//2)*S + N
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Sample RAMs (I and Q), 2 read + 2 write ports for one butterfly per cycle.
        mi, mq = Memory(data_width, N), Memory(data_width, N)
        ra_i, rb_i = mi.get_port(async_read=True), mi.get_port(async_read=True)
        wa_i, wb_i = mi.get_port(write_capable=True), mi.get_port(write_capable=True)
        ra_q, rb_q = mq.get_port(async_read=True), mq.get_port(async_read=True)
        wa_q, wb_q = mq.get_port(write_capable=True), mq.get_port(write_capable=True)
        self.specials += mi, mq, ra_i, rb_i, wa_i, wb_i, ra_q, rb_q, wa_q, wb_q

        cos_rom = Memory(twiddle_width, N//2, init=_tw_rom(N, math.cos, twiddle_width))
        sin_rom = Memory(twiddle_width, N//2, init=_tw_rom(N, math.sin, twiddle_width))
        cos_rp, sin_rp = cos_rom.get_port(async_read=True), sin_rom.get_port(async_read=True)
        self.specials += cos_rom, sin_rom, cos_rp, sin_rp

        s   = Signal(max=max(2, S))            # Stage.
        b   = Signal(max=max(2, N//2))         # Butterfly index within stage.
        idx = Signal(max=N)                    # Load/unload index.

        half   = Signal(S)
        addr_a = Signal(S)
        addr_b = Signal(S)
        j      = Signal(S)
        tw_idx = Signal(S)
        self.comb += [
            half.eq(1 << s),
            j.eq(b & (half - 1)),
            addr_a.eq(((b >> s) << (s + 1)) | (b & (half - 1))),
            addr_b.eq(addr_a | half),
            tw_idx.eq(j << (S - 1 - s)),
            cos_rp.adr.eq(tw_idx), sin_rp.adr.eq(tw_idx),
        ]

        # Butterfly arithmetic.
        ai, aq = Signal((data_width, True)), Signal((data_width, True))
        bi, bq = Signal((data_width, True)), Signal((data_width, True))
        tr, ti = Signal((twiddle_width, True)), Signal((twiddle_width, True))
        self.comb += [
            ai.eq(ra_i.dat_r), aq.eq(ra_q.dat_r),
            bi.eq(rb_i.dat_r), bq.eq(rb_q.dat_r),
            tr.eq(cos_rp.dat_r), ti.eq(sin_rp.dat_r),
        ]
        pr, _ = scaled(bi*tr - bq*ti, twiddle_width - 1, data_width)   # b*tw (real).
        pi, _ = scaled(bi*ti + bq*tr, twiddle_width - 1, data_width)   # b*tw (imag).
        oa_i, _ = scaled(ai + pr, 1, data_width)                       # (a + b*tw)/2.
        oa_q, _ = scaled(aq + pi, 1, data_width)
        ob_i, _ = scaled(ai - pr, 1, data_width)                       # (a - b*tw)/2.
        ob_q, _ = scaled(aq - pi, 1, data_width)

        # FSM state flags and single-driver port wiring.
        self.fsm = fsm = FSM(reset_state="LOAD")
        loading   = fsm.ongoing("LOAD")
        computing = fsm.ongoing("COMPUTE")
        unloading = fsm.ongoing("UNLOAD")
        brev      = Array([_bitrev(k, S) for k in range(N)])
        self.comb += [
            ra_i.adr.eq(Mux(unloading, idx, addr_a)), ra_q.adr.eq(Mux(unloading, idx, addr_a)),
            rb_i.adr.eq(addr_b), rb_q.adr.eq(addr_b),
            wa_i.adr.eq(Mux(loading, brev[idx], addr_a)), wa_q.adr.eq(Mux(loading, brev[idx], addr_a)),
            wb_i.adr.eq(addr_b), wb_q.adr.eq(addr_b),
            wa_i.dat_w.eq(Mux(loading, self.sink.i, oa_i)), wa_q.dat_w.eq(Mux(loading, self.sink.q, oa_q)),
            wb_i.dat_w.eq(ob_i), wb_q.dat_w.eq(ob_q),
            wa_i.we.eq((loading & self.sink.valid) | computing),
            wa_q.we.eq((loading & self.sink.valid) | computing),
            wb_i.we.eq(computing), wb_q.we.eq(computing),
        ]

        fsm.act("LOAD",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                If(idx == (N - 1),
                    NextValue(idx, 0), NextValue(s, 0), NextValue(b, 0), NextState("COMPUTE"),
                ).Else(NextValue(idx, idx + 1)),
            )
        )
        fsm.act("COMPUTE",
            If(b == (N//2 - 1),
                NextValue(b, 0),
                If(s == (S - 1), NextState("UNLOAD")).Else(NextValue(s, s + 1)),
            ).Else(NextValue(b, b + 1)),
        )
        fsm.act("UNLOAD",
            self.source.valid.eq(1),
            self.source.i.eq(ra_i.dat_r), self.source.q.eq(ra_q.dat_r),
            self.source.first.eq(idx == 0), self.source.last.eq(idx == (N - 1)),
            If(self.source.ready,
                If(idx == (N - 1), NextValue(idx, 0), NextState("LOAD")).Else(NextValue(idx, idx + 1)),
            )
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._latency = CSRStatus(32, reset=self.latency, name="latency",
            description="Iterative FFT burst latency (cycles).")
