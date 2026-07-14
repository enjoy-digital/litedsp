#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Compact iterative (memory-based) radix-2 FFT.

A single radix-2 butterfly works in place on synchronous-read RAM, processing an N-sample burst
in ~N + 1.5*N*log2(N) + N cycles. Each I/Q sample memory is one true-dual-port block RAM (two
R/W ports, synchronous read), so the design maps to BRAM rather than fabric LUTs. DIT in-place:
the input is written bit-reversed, log2(N) stages of butterflies run (each butterfly = read,
twiddle-product register, write — one multiply level per cycle), then the result is read out in
natural order. Output is 1/N-scaled.
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, scaled

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

class LiteDSPFFTIter(LiteXModule):
    """Iterative in-place radix-2 FFT, ``N`` points, natural-order output (BRAM-mapped).

    Parameters
    ----------
    twiddle_width : int
        Twiddle-factor width in bits (signed Q1.(W-1)); sets the N/2-entry cos/sin ROM width,
        the butterfly multiplier size, and the coefficient-quantization noise floor.
    """
    def __init__(self, N, data_width=16, twiddle_width=16, with_csr=True):
        check((N & (N - 1)) == 0 and N >= 4, "expected (N & (N - 1)) == 0 and N >= 4")
        self.N    = N
        S         = N.bit_length() - 1
        self.bits = S
        self.data_width = data_width
        self.latency    = N + (3*N*S)//2 + N             # 3 cycles per butterfly.
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Memories.
        # ---------
        # Sample RAMs (I and Q): two synchronous-read R/W ports each -> one TDP BRAM per memory.
        mi, mq = Memory(data_width, N), Memory(data_width, N)
        ai, bi = mi.get_port(write_capable=True), mi.get_port(write_capable=True)
        aq, bq = mq.get_port(write_capable=True), mq.get_port(write_capable=True)
        cos_rom = Memory(twiddle_width, N//2, init=_tw_rom(N, math.cos, twiddle_width))
        sin_rom = Memory(twiddle_width, N//2, init=_tw_rom(N, math.sin, twiddle_width))
        cos_rp  = cos_rom.get_port(async_read=True)
        sin_rp  = sin_rom.get_port(async_read=True)
        self.specials += mi, mq, ai, bi, aq, bq, cos_rom, sin_rom, cos_rp, sin_rp

        # Address Generation.
        # -------------------
        s   = Signal(max=max(2, S))                  # Stage index (0..S-1).
        b   = Signal(max=max(2, N//2))               # Butterfly index within the stage (N/2 per stage).
        idx = Signal(max=N)                          # Load/unload sample index.

        half   = Signal(S)
        addr_a = Signal(S)
        addr_b = Signal(S)
        j      = Signal(S)
        self.comb += [
            half.eq(1 << s),                         # Butterfly span at stage s.
            j.eq(b & (half - 1)),                    # Offset within the group.
            addr_a.eq(((b >> s) << (s + 1)) | j),    # Group base (2*half per group) + offset.
            addr_b.eq(addr_a | half),                # Partner element, half above addr_a.
            cos_rp.adr.eq(j << (S - 1 - s)), sin_rp.adr.eq(j << (S - 1 - s)),  # Twiddle j*N/2**(s+1).
        ]

        # Datapath.
        # ---------
        # Butterfly arithmetic (operands are the registered reads from the previous cycle).
        # The twiddle product is registered in its own cycle (BFLY_CALC) so each clock carries
        # one multiply level: read -> product register -> write.
        tr, ti = Signal((twiddle_width, True)), Signal((twiddle_width, True))
        self.comb += [tr.eq(cos_rp.dat_r), ti.eq(sin_rp.dat_r)]
        Ar, Aq = Signal((data_width, True)), Signal((data_width, True))
        Br, Bq = Signal((data_width, True)), Signal((data_width, True))
        self.comb += [Ar.eq(ai.dat_r), Aq.eq(aq.dat_r), Br.eq(bi.dat_r), Bq.eq(bq.dat_r)]
        pr, pi = Signal((data_width, True)), Signal((data_width, True))
        self.sync += [
            pr.eq(scaled(Br*tr - Bq*ti, twiddle_width - 1, data_width)[0]),   # b*tw.
            pi.eq(scaled(Br*ti + Bq*tr, twiddle_width - 1, data_width)[0]),
        ]
        sum_i, _ = scaled(Ar + pr, 1, data_width)                      # (a + b*tw)/2.
        sum_q, _ = scaled(Aq + pi, 1, data_width)
        dif_i, _ = scaled(Ar - pr, 1, data_width)                      # (a - b*tw)/2.
        dif_q, _ = scaled(Aq - pi, 1, data_width)

        # FSM and single-driver port wiring.
        # ----------------------------------
        self.fsm = fsm = FSM(reset_state="LOAD")
        load  = fsm.ongoing("LOAD")
        read  = fsm.ongoing("BFLY_READ")
        write = fsm.ongoing("BFLY_WRITE")
        uread = fsm.ongoing("UNLD_READ")
        uemit = fsm.ongoing("UNLD_EMIT")
        brev  = Array([_bitrev(k, S) for k in range(N)])

        # Port A: load-write / butterfly addr_a (read+write) / unload-read.
        self.comb += [
            ai.adr.eq(Mux(load, brev[idx], Mux(uread | uemit, idx, addr_a))),
            aq.adr.eq(ai.adr),
            ai.dat_w.eq(Mux(load, self.sink.i, sum_i)), aq.dat_w.eq(Mux(load, self.sink.q, sum_q)),
            ai.we.eq((load & self.sink.valid) | write), aq.we.eq(ai.we),
            # Port B: butterfly addr_b only.
            bi.adr.eq(addr_b), bq.adr.eq(addr_b),
            bi.dat_w.eq(dif_i), bq.dat_w.eq(dif_q),
            bi.we.eq(write), bq.we.eq(write),
        ]

        fsm.act("LOAD",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                If(idx == (N - 1),
                    NextValue(idx, 0), NextValue(s, 0), NextValue(b, 0), NextState("BFLY_READ"),
                ).Else(NextValue(idx, idx + 1)),
            )
        )
        fsm.act("BFLY_READ", NextState("BFLY_CALC"))       # Reads issued; data ready next cycle.
        fsm.act("BFLY_CALC", NextState("BFLY_WRITE"))      # Twiddle product registers.
        fsm.act("BFLY_WRITE",
            If(b == (N//2 - 1),
                NextValue(b, 0),
                If(s == (S - 1), NextState("UNLD_READ")).Else(NextValue(s, s + 1), NextState("BFLY_READ")),
            ).Else(NextValue(b, b + 1), NextState("BFLY_READ")),
        )
        fsm.act("UNLD_READ", NextState("UNLD_EMIT"))       # Read of idx issued.
        fsm.act("UNLD_EMIT",
            self.source.valid.eq(1),
            self.source.i.eq(ai.dat_r), self.source.q.eq(aq.dat_r),
            self.source.first.eq(idx == 0), self.source.last.eq(idx == (N - 1)),
            If(self.source.ready,
                If(idx == (N - 1), NextValue(idx, 0), NextState("LOAD"))
                .Else(NextValue(idx, idx + 1), NextState("UNLD_READ")),
            )
        )

        # CSR.
        # ----
        if with_csr:
            self._latency = CSRStatus(32, reset=self.latency, name="latency",
                description="Iterative FFT burst latency (cycles).")
