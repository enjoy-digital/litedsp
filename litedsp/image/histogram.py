#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-frame histogram of one channel, streamed out after the frame."""

from migen import *
from migen.genlib.fsm import FSM, NextState, NextValue

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, pixel_layout, pixel_fields, bits_for

# Pixel Histogram ----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPixelHistogram(LiteXModule):
    """Histogram of one channel per frame into ``2**bins_log2`` bins (the code's top bits).

    Counts accumulate in one RAM per bank (ping-pong, one read and one write port each) at one
    pixel per clock (read-modify-write with a same-bin forwarding register); ``last`` seals a
    bank and the block streams its bins out
    (``data`` = count, ``first`` on bin 0, ``last`` on the final bin, one beat per bin) while
    clearing them for reuse. A frame ending before the previous histogram drained sets the
    sticky ``overrun``. ``max_pixels`` sizes the counts. ``latency = None``; one output beat
    per bin per frame.
    """
    def __init__(self, data_width=8, n_channels=1, channel=0, bins_log2=8, max_pixels=1920*1080,
                 with_csr=True):
        check(1 <= bins_log2 <= data_width, "expected 1 <= bins_log2 <= data_width")
        check(0 <= channel < n_channels, "expected channel < n_channels")
        self.data_width = data_width
        self.bins_log2  = bins_log2
        self.latency    = None
        CW = bits_for(max_pixels)
        self.sink   = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint([("data", CW)])
        self.channel = Signal(2, reset=channel)
        self.overrun = Signal()
        self.clear   = Signal()
        self.frames  = Signal(32)

        # # #

        NB = 1 << bins_log2
        fields = pixel_fields(n_channels)
        # One RAM per bank (a single write and read port each, block-RAM friendly): the input
        # side owns the bank being counted, the readout the sealed one; the port sources are
        # muxed by the bank bits.
        mems = [Memory(CW, NB, name=f"bank{b}") for b in range(2)]
        rps  = [m.get_port(has_re=True) for m in mems]
        wps  = [m.get_port(write_capable=True) for m in mems]
        self.specials += mems + rps + wps
        # Input side: RMW at one pixel per clock (S0 read, S1 write with forwarding).
        xfer = Signal()
        self.comb += [self.sink.ready.eq(1), xfer.eq(self.sink.valid)]
        x = Signal(data_width)
        self.comb += x.eq(Array([getattr(self.sink, f) for f in fields])[
            self.channel] if n_channels > 1 else self.sink.data)
        bin0 = Signal(bins_log2)
        wbank = Signal()
        self.comb += bin0.eq(x[data_width - bins_log2:])
        v1, last1 = Signal(), Signal()
        bin1, bank1 = Signal(bins_log2), Signal()
        fwd_bin, fwd_cnt, fwd_v = Signal(bins_log2), Signal(CW), Signal()
        cnt_new = Signal(CW)
        in_rd = Signal(CW)
        self.sync += [v1.eq(xfer), last1.eq(xfer & self.sink.last), bin1.eq(bin0), bank1.eq(wbank)]
        self.comb += [
            in_rd.eq(Array([rp.dat_r for rp in rps])[bank1]),
            cnt_new.eq(Mux(fwd_v & (fwd_bin == bin1), fwd_cnt, in_rd) + 1),
        ]
        self.sync += [
            fwd_v.eq(v1), fwd_bin.eq(bin1), fwd_cnt.eq(cnt_new),
            If(v1 & last1, fwd_v.eq(0)),                            # A new frame: no stale forward.
        ]
        # Frame end: seal the bank (the write of the last pixel lands at S1 of the same cycle).
        sealed = [Signal(name=f"sealed{b}") for b in range(2)]
        self.sync += If(xfer & self.sink.last,
            wbank.eq(~wbank),
            self.frames.eq(self.frames + 1),
            *[If(wbank == b, sealed[b].eq(1), If(sealed[b] | sealed[1 - b], self.overrun.eq(1)))
                for b in range(2)],
        )
        self.sync += If(self.clear, self.overrun.eq(0))
        # Output side: stream the sealed bank, clearing each bin (after the last write landed).
        adv = Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        rbank = Signal()
        ri = Signal(bins_log2)
        rec_a = Signal()
        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            If(Array(sealed)[rbank] & ~v1 & adv,                        # Wait for the tail write.
                NextValue(ri, 0),
                NextState("READ"),
            ),
        )
        rlast = Signal()
        self.comb += rlast.eq(ri == NB - 1)
        fsm.act("READ",
            rec_a.eq(1),
            If(adv,
                NextValue(ri, ri + 1),
                If(rlast, NextState("RELEASE")),
            ),
        )
        fsm.act("RELEASE",
            *[If(rbank == b, NextValue(sealed[b], 0)) for b in range(2)],
            NextValue(rbank, ~rbank),
            NextState("IDLE"),
        )
        b_addr = Signal(bins_log2)
        b_bank = Signal()
        self.sync += If(adv,
            self.source.valid.eq(rec_a), self.source.first.eq(ri == 0), self.source.last.eq(rlast),
            b_addr.eq(ri), b_bank.eq(rbank),
        )
        out_rd = Signal(CW)
        self.comb += [out_rd.eq(Array([rp.dat_r for rp in rps])[b_bank]),
                      self.source.data.eq(out_rd)]
        # Port muxes per bank: reads (input at bin0 while counting, readout at ri) and writes
        # (the count while counting, the clear while draining).
        for b in range(2):
            counting = (wbank == b)
            self.comb += [
                rps[b].adr.eq(Mux(counting, bin0, ri)),
                rps[b].re.eq(Mux(counting, 1, adv)),
                wps[b].adr.eq(Mux(bank1 == b, bin1, b_addr)),
                wps[b].dat_w.eq(Mux(bank1 == b, cnt_new, 0)),
                wps[b].we.eq(Mux(bank1 == b, v1, adv & self.source.valid & (b_bank == b))),
            ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("channel", size=2, offset=0, reset=self.channel.reset.value, description="Measured channel."),
            CSRField("clear",   size=1, offset=4, pulse=True, description="Clear the overrun flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("overrun", size=1, offset=0, description="Sticky: a frame ended before the previous histogram drained."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("bins_log2", size=4, offset=0, description="log2 of the bin count."),
        ])
        self._frames = CSRStatus(32, name="frames", description="Frames counted.")
        self.comb += [
            self.channel.eq(self._control.fields.channel),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.overrun.eq(self.overrun),
            self._config.fields.bins_log2.eq(self.bins_log2),
            self._frames.status.eq(self.frames),
        ]
