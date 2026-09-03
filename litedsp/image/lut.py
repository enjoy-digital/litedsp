#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-pixel lookup tables: gamma, tone curves, histogram equalisation."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import check, pixel_layout, pixel_fields, add_bypass, add_bypass_csr
from litedsp.image.design import gamma_table

# Pixel LUT ----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPixelLUT(LiteXModule):
    """Code-to-code lookup on every channel (``2**data_width`` entries per table).

    ``shared`` uses one table for all channels (three read ports), otherwise one table per
    channel; tables initialise to the ``gamma`` curve (1.0 = identity). The host rewrites
    entries through ``lut_addr`` (auto-incremented by a ``lut_data`` write) with ``lut_channel``
    (3 = all tables); loads may happen mid-frame. ``bypass``. Latency 1 (synchronous read).
    """
    def __init__(self, data_width=8, n_channels=1, shared=True, gamma=1.0, with_csr=True):
        check(gamma > 0, "expected gamma > 0")
        self.data_width = data_width
        self.n_channels = n_channels
        self.shared     = shared
        self.latency    = 1
        self.sink   = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.lut_addr    = Signal(data_width)
        self.lut_data    = Signal(data_width)
        self.lut_channel = Signal(2, reset=3)
        self.lut_we      = Signal()

        # # #

        DW = data_width
        fields = pixel_fields(n_channels)
        init   = gamma_table(gamma, DW)
        n_tables = 1 if shared else n_channels
        tables = []
        for t in range(n_tables):
            mem = Memory(DW, 1 << DW, init=init)
            wp  = mem.get_port(write_capable=True)
            self.specials += mem, wp
            self.comb += [wp.adr.eq(self.lut_addr), wp.dat_w.eq(self.lut_data),
                          wp.we.eq(self.lut_we & ((self.lut_channel == 3) | (self.lut_channel == t)))]
            tables.append(mem)
        self.sync += If(self.lut_we, self.lut_addr.eq(self.lut_addr + 1))
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]
        for c, f in enumerate(fields):
            rp = tables[0 if shared else c].get_port(has_re=True)
            self.specials += rp
            self.comb += [rp.adr.eq(getattr(self.sink, f)), rp.re.eq(adv), getattr(self.source, f).eq(rp.dat_r)]
        eol_r = Signal()                                                # Payload fields are all
        self.sync += If(adv,                                            # combinational (the RAM
            self.source.valid.eq(self.sink.valid),                      # read is registered) so the
            self.source.first.eq(self.sink.first), eol_r.eq(self.sink.eol), self.source.last.eq(self.sink.last),   # bypass mux can be too.
        )
        self.comb += self.source.eol.eq(eol_r)
        add_bypass(self, output_registered=False)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        DW = self.data_width
        self._lut_addr = CSRStorage(DW, name="lut_addr", description="Table address (auto-increments on a data write).")
        self._lut_data = CSRStorage(fields=[
            CSRField("data",    size=DW, offset=0,  description="Writing stores the entry at lut_addr."),
            CSRField("channel", size=2,  offset=16, reset=3, description="Table 0..2, 3 = all."),
        ])
        self.sync += If(self._lut_addr.re, self.lut_addr.eq(self._lut_addr.storage))
        self.comb += [
            self.lut_data.eq(self._lut_data.fields.data), self.lut_channel.eq(self._lut_data.fields.channel),
            self.lut_we.eq(self._lut_data.re),
        ]
        add_bypass_csr(self)
