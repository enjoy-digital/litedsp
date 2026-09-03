#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Convolutional (Forney) interleaver / deinterleaver on symbol streams."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, add_bypass, add_bypass_csr, bits_for

# Forney delay engine ------------------------------------------------------------------------------

class _LiteDSPForneyDelay(LiteXModule):
    """``branches`` delay lines of ``delays[j]`` symbols in one RAM (region bases from the
    cumulative delays, one pointer per branch), a commutator cycling the branches per symbol.
    Zero-initialised RAM gives deterministic zeros until each line has filled."""
    def __init__(self, delays, width, with_csr):
        B = len(delays)
        check(B >= 2 and width >= 1, "expected branches >= 2, width >= 1")
        self.branches = B
        self.width    = width
        self.latency  = 2
        self.sink   = stream.Endpoint([("data", width)])
        self.source = stream.Endpoint([("data", width)])
        self.phase_rst = Signal()

        # # #

        bases, total = [], 0
        for d in delays:
            bases.append(total)
            total += d
        depth = max(total, 2)                                           # Migen ports need >= 2 entries.
        self.specials.mem = mem = Memory(width, depth)
        rp = mem.get_port(has_re=True)
        wp = mem.get_port(write_capable=True)
        self.specials += rp, wp
        AW = bits_for(depth - 1)
        adv, xfer = Signal(), Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv), xfer.eq(self.sink.valid & adv)]
        branch = Signal(max=max(B, 2))
        PW_    = max(bits_for(max(delays)), 1)
        ptrs   = [Signal(PW_, name=f"ptr{j}") for j in range(B)]        # Equal widths for the Array.
        addr   = Signal(AW + 1)
        base_sel, ptr_sel = Signal(AW), Signal(PW_)
        self.comb += [
            base_sel.eq(Array([C(bases[j], AW) for j in range(B)])[branch]),
            ptr_sel.eq(Array(ptrs)[branch]),
            addr.eq(base_sel + ptr_sel),
        ]
        self.comb += [rp.adr.eq(addr[:AW]), rp.re.eq(adv)]
        # Pointer / commutator advance per accepted symbol (decoded writes).
        self.sync += [
            If(self.phase_rst,
                branch.eq(0),
            ).Elif(xfer,
                If(branch == B - 1, branch.eq(0)).Else(branch.eq(branch + 1)),
                *[If(branch == j, If(ptrs[j] == delays[j] - 1, ptrs[j].eq(0)).Else(ptrs[j].eq(ptrs[j] + 1)))
                  for j in range(B) if delays[j] > 0],
            ),
        ]
        # S1: the delayed symbol (RAM) or the input for a zero-delay branch; write the input at
        # the address just read (read-before-write, one cycle apart).
        v1, f1, l1 = Signal(), Signal(), Signal()
        x1, a1, b1 = Signal(width), Signal(AW), Signal(max=max(B, 2))
        self.sync += If(adv, v1.eq(xfer), f1.eq(self.sink.first), l1.eq(self.sink.last), x1.eq(self.sink.data), a1.eq(addr[:AW]), b1.eq(branch))
        zero_delay = Signal()
        self.comb += zero_delay.eq(Array([C(int(delays[j] == 0), 1) for j in range(B)])[b1])
        self.comb += [wp.adr.eq(a1), wp.dat_w.eq(x1), wp.we.eq(adv & v1 & ~zero_delay)]
        self.sync += If(adv,
            self.source.valid.eq(v1), self.source.first.eq(f1), self.source.last.eq(l1),
            self.source.data.eq(Mux(zero_delay, x1, rp.dat_r)),
        )
        add_bypass(self)
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("phase_rst", size=1, offset=0, pulse=True, description="Restart the commutator at branch 0."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("branches", size=8, offset=0, description="Branches."),
            CSRField("width",    size=8, offset=8, description="Symbol width."),
        ])
        self.comb += [self.phase_rst.eq(self._control.fields.phase_rst),
                      self._config.fields.branches.eq(self.branches), self._config.fields.width.eq(self.width)]
        add_bypass_csr(self)

@ResetInserter()
class LiteDSPConvolutionalInterleaver(_LiteDSPForneyDelay):
    """Forney convolutional interleaver: branch ``j`` delays by ``j * depth`` symbols (DVB:
    ``branches=12, depth=17`` bytes); all lines share one RAM of ``depth * B (B-1) / 2`` symbols.
    Latency 2; ``bypass``; ``phase_rst`` restarts the commutator."""
    def __init__(self, branches=12, depth=17, width=8, with_csr=True):
        check(depth >= 1, "expected depth >= 1")
        self.depth = depth
        _LiteDSPForneyDelay.__init__(self, [j*depth for j in range(branches)], width, with_csr)

@ResetInserter()
class LiteDSPConvolutionalDeinterleaver(_LiteDSPForneyDelay):
    """The matching deinterleaver: branch ``j`` delays by ``(B - 1 - j) * depth``; the pair
    delays the stream by ``(B - 1) * depth * B`` symbols and spreads a channel burst of ``B``
    symbols to errors ``depth * B - 1`` apart."""
    def __init__(self, branches=12, depth=17, width=8, with_csr=True):
        check(depth >= 1, "expected depth >= 1")
        self.depth = depth
        _LiteDSPForneyDelay.__init__(self, [(branches - 1 - j)*depth for j in range(branches)], width, with_csr)
