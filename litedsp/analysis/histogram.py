#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import real_layout

# Histogram ----------------------------------------------------------------------------------------

class LiteDSPHistogram(LiteXModule):
    """Sample-distribution histogram (e.g. for ADC characterization).

    Bins by the top ``bits`` of ``(x + 2**(data_width-1))`` (offset to unsigned). Accumulates
    over ``2**window_log2`` samples into a ``2**bits``-entry RAM, then streams the bin counts
    (natural order, framed) while backpressuring the input; each bin is cleared as it is read,
    so the next window starts from zero.
    """
    def __init__(self, data_width=16, bits=8, window_log2=12, with_csr=True):
        self.data_width = data_width
        self.bits       = bits
        count_width     = window_log2 + 1  # A bin can hold all 2**window_log2 samples.
        B = 1 << bits                      # Number of bins.
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint([("data", count_width)])

        # # #

        # Memory.
        # -------
        mem = Memory(count_width, B)               # Zero-initialized.
        wp  = mem.get_port(write_capable=True)
        rp  = mem.get_port(async_read=True)
        self.specials += mem, wp, rp

        # Binning.
        # --------
        # Offset-binary conversion (+ half range) then keep the top `bits` as the bin address.
        bin_addr = Signal(bits)
        self.comb += bin_addr.eq((self.sink.data + (1 << (data_width - 1)))[data_width - bits:])

        # FSM.
        # ----
        sample   = Signal(window_log2 + 1)  # Samples accumulated in the current window.
        read_cnt = Signal(bits)             # Bin readout index.
        accept   = Signal()                 # Sample accepted (accumulate write).
        reading  = Signal()                 # 1 during readout (muxes RAM addresses to read_cnt).

        self.fsm = fsm = FSM(reset_state="ACC")
        self.comb += [
            rp.adr.eq(Mux(reading, read_cnt, bin_addr)),
            wp.adr.eq(Mux(reading, read_cnt, bin_addr)),
            wp.dat_w.eq(Mux(reading, 0, rp.dat_r + 1)),   # Clear on read; +1 on accumulate.
        ]
        fsm.act("ACC",
            self.sink.ready.eq(1),
            accept.eq(self.sink.valid),
            wp.we.eq(self.sink.valid),
            If(self.sink.valid,
                If(sample == ((1 << window_log2) - 1),
                    NextValue(sample, 0),
                    NextState("READ"),
                ).Else(
                    NextValue(sample, sample + 1),
                )
            )
        )
        fsm.act("READ",
            reading.eq(1),
            self.source.valid.eq(1),
            self.source.data.eq(rp.dat_r),
            self.source.first.eq(read_cnt == 0),
            self.source.last.eq(read_cnt == (B - 1)),
            If(self.source.ready,
                wp.we.eq(1),                              # Clear this bin.
                If(read_cnt == (B - 1),
                    NextValue(read_cnt, 0),
                    NextState("ACC"),
                ).Else(
                    NextValue(read_cnt, read_cnt + 1),
                )
            )
        )
