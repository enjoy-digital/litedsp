#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import check, iq_layout
from litedsp.analysis.fft import bit_reverse

# Bit-Reverse Reorder ------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPBitReverse(LiteXModule):
    """Reorder ``N``-beat frames from bit-reversed to natural order (the FFT's output order).

    Frames are written into a ``2 x N`` ping-pong RAM at the bit-reversed address of their
    position and read back sequentially, framed with ``first``/``last``; while one bank drains
    the other fills, so a continuous stream flows at one beat per cycle after the first frame.
    Frame boundaries are counted from reset (the FFT does not carry them through its pipeline):
    ``fft_latency`` initial fill beats are discarded first, exactly as :class:`LiteDSPPSD` does.
    Any payload ``layout`` (default ``iq_layout(data_width)``) is carried as raw bits.

    Parameters
    ----------
    N : int
        Frame length (power of two >= 2), the upstream FFT size.
    fft_latency : int
        Upstream pipeline fill beats to skip after reset (``LiteDSPFFT.latency``; 0 when the
        stream is already frame-aligned).
    """
    def __init__(self, N=64, data_width=16, layout=None, fft_latency=0, with_csr=True):
        check(N >= 2 and (N & (N - 1)) == 0, "expected N a power of two >= 2")
        check(fft_latency >= 0, "expected fft_latency >= 0")
        if layout is None:
            layout = iq_layout(data_width)
        self.N           = N
        self.data_width  = data_width
        self.fft_latency = fft_latency
        self.latency     = None                                        # Frame buffered.
        self.sink   = stream.Endpoint(layout)
        self.source = stream.Endpoint(layout)
        self.filled = Signal(2)                                        # Sealed banks (0..2).

        # # #

        bits  = (N - 1).bit_length()
        width = len(self.sink.payload)
        mem   = Memory(width, 2*N)
        wp    = mem.get_port(write_capable=True)
        rp    = mem.get_port(has_re=True)                              # Registered read: block RAM.
        self.specials += mem, wp, rp

        # Write side: skip the FFT fill, then one frame per bank at bit-reversed addresses.
        # -------------------------------------------------------------------------------
        skip    = Signal(max=max(2, fft_latency + 1))
        skipping = Signal(reset=int(fft_latency > 0))
        wr_bank, wr_pos = Signal(), Signal(bits)
        wr_xfer, wr_done = Signal(), Signal()
        rev = Signal(bits)
        self.comb += [
            rev.eq(Cat(*[wr_pos[b] for b in reversed(range(bits))])),
            self.sink.ready.eq(skipping | (self.filled != 2)),
            wr_xfer.eq(self.sink.valid & self.sink.ready & ~skipping),
            wr_done.eq(wr_xfer & (wr_pos == N - 1)),
            wp.adr.eq(Cat(rev, wr_bank)),
            wp.dat_w.eq(self.sink.payload.raw_bits()),
            wp.we.eq(wr_xfer),
        ]
        if fft_latency > 0:
            self.sync += If(skipping & self.sink.valid,
                If(skip == fft_latency - 1, skipping.eq(0)).Else(skip.eq(skip + 1)),
            )
        self.sync += If(wr_xfer,
            If(wr_pos == N - 1, wr_pos.eq(0), wr_bank.eq(~wr_bank)).Else(wr_pos.eq(wr_pos + 1)),
        )

        # Read side: sequential, framed; the RAM's registered read port is the output register
        # (read enable = the elastic advance, so the data holds through stalls).
        # -----------------------------------------------------------------------------------
        rd_bank, rd_pos = Signal(), Signal(bits)
        adv, rd_issue, rd_done = Signal(), Signal(), Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            rd_issue.eq(adv & (self.filled != 0)),
            rd_done.eq(rd_issue & (rd_pos == N - 1)),
            rp.adr.eq(Cat(rd_pos, rd_bank)),
            rp.re.eq(adv),
            self.source.payload.raw_bits().eq(rp.dat_r),
        ]
        self.sync += [
            If(adv,
                self.source.valid.eq(self.filled != 0),
                self.source.first.eq(rd_pos == 0),
                self.source.last.eq(rd_pos == N - 1),
            ),
            If(rd_issue,
                If(rd_pos == N - 1, rd_pos.eq(0), rd_bank.eq(~rd_bank)).Else(rd_pos.eq(rd_pos + 1)),
            ),
            self.filled.eq(self.filled + wr_done - rd_done),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("n",           size=16, offset=0,  description="Frame length."),
            CSRField("fft_latency", size=16, offset=16, description="Fill beats skipped after reset."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("filled", size=2, offset=0, description="Frames buffered (0..2)."),
        ])
        self.comb += [
            self._config.fields.n.eq(self.N),
            self._config.fields.fft_latency.eq(self.fft_latency),
            self._status.fields.filled.eq(self.filled),
        ]
