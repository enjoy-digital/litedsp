#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Frame statistics tap: sum, min, max and zone sums of one channel."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourcePulse
from litex.soc.interconnect                  import stream

from litedsp.common       import check, pixel_layout, pixel_fields, bits_for
from litedsp.image.common import LiteDSPPixelCounter

# Pixel Stats --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPixelStats(LiteXModule):
    """Zero-latency passthrough that measures one channel per frame.

    ``sum``, ``min``, ``max`` and ``count`` over the frame plus ``zones x zones`` zone sums (zone
    index from the pixel coordinates against the runtime ``zone_width`` / ``zone_height``,
    clamped to the last zone) accumulate on the selected channel and are latched at ``last``
    (``update`` pulse, optional ``ev.frame`` interrupt); the mean is host-side. ``max_pixels``
    sizes the accumulators. Latency 0 (``sink`` connects to ``source``).
    """
    def __init__(self, data_width=8, n_channels=1, channel=0, zones=4, max_pixels=1920*1080,
                 coord_bits=12,
        with_csr=True, with_irq=False):
        check(zones in (1, 2, 4, 8), "expected zones in (1, 2, 4, 8)")
        check(0 <= channel < n_channels, "expected channel < n_channels")
        self.data_width = data_width
        self.n_channels = n_channels
        self.zones      = zones
        self.latency    = 0
        AW = data_width + bits_for(max_pixels)
        self.sink   = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.channel     = Signal(2, reset=channel)
        self.zone_width  = Signal(coord_bits, reset=max(1, 640//zones))
        self.zone_height = Signal(coord_bits, reset=max(1, 480//zones))
        self.sum   = Signal(AW)
        self.min   = Signal(data_width)
        self.max   = Signal(data_width)
        self.count = Signal(bits_for(max_pixels))
        self.zone  = [Signal(AW, name=f"zone{k}") for k in range(zones*zones)]
        self.update = Signal()

        # # #

        fields = pixel_fields(n_channels)
        xfer = Signal()
        self.comb += [self.sink.connect(self.source), xfer.eq(self.sink.valid & self.sink.ready)]
        x = Signal(data_width)
        self.comb += x.eq(Array([getattr(self.sink, f) for f in fields])[
            self.channel] if n_channels > 1 else self.sink.data)
        self.counter = cnt = LiteDSPPixelCounter(coord_bits)
        self.comb += [cnt.xfer.eq(xfer), cnt.first.eq(self.sink.first), cnt.eol.eq(self.sink.eol),
                      cnt.last.eq(self.sink.last)]
        # Zone index: per-line pixel counter against zone_width, per-frame line counter against
        # zone_height (no dividers), clamped to the last zone.
        ZB = bits_for(zones - 1) if zones > 1 else 1
        zx, zy = Signal(ZB), Signal(ZB)
        px, py = Signal(coord_bits), Signal(coord_bits)
        zx_c, zy_c = Signal(ZB), Signal(ZB)
        self.comb += [zx_c.eq(Mux(cnt.first | (cnt.col == 0), 0, zx)),
                      zy_c.eq(Mux(cnt.first, 0, zy))]
        px_c, py_c = Signal(coord_bits), Signal(coord_bits)
        self.comb += [px_c.eq(Mux(cnt.first | (cnt.col == 0), 0, px)),
                      py_c.eq(Mux(cnt.first, 0, py))]
        self.sync += If(xfer,
            If(px_c == self.zone_width - 1,
                px.eq(0), zx.eq(Mux(zx_c == zones - 1, zones - 1, zx_c + 1)),
            ).Else(
                px.eq(px_c + 1), zx.eq(zx_c),
            ),
            If(self.sink.eol,
                px.eq(0), zx.eq(0),
                If(py_c == self.zone_height - 1,
                    py.eq(0), zy.eq(Mux(zy_c == zones - 1, zones - 1, zy_c + 1)),
                ).Else(
                    py.eq(py_c + 1), zy.eq(zy_c),
                ),
            ),
            If(self.sink.last, px.eq(0), py.eq(0), zx.eq(0), zy.eq(0)),
        )
        zidx = Signal(2*ZB)
        self.comb += zidx.eq(zy_c*zones + zx_c)
        # Accumulators (restart at first) and the latches at last.
        acc_sum   = Signal(AW)
        acc_min   = Signal(data_width, reset=(1 << data_width) - 1)
        acc_max   = Signal(data_width)
        acc_count = Signal(bits_for(max_pixels))
        acc_zone  = [Signal(AW, name=f"acc_zone{k}") for k in range(zones*zones)]
        base_sum   = Signal(AW)
        base_min   = Signal(data_width)
        base_max   = Signal(data_width)
        base_count = Signal(bits_for(max_pixels))
        self.comb += [
            base_sum.eq(Mux(self.sink.first, 0, acc_sum)),
            base_min.eq(Mux(self.sink.first, (1 << data_width) - 1, acc_min)),
            base_max.eq(Mux(self.sink.first, 0, acc_max)),
            base_count.eq(Mux(self.sink.first, 0, acc_count)),
        ]
        self.sync += [
            self.update.eq(0),
            If(xfer,
                acc_sum.eq(base_sum + x),
                acc_min.eq(Mux(x < base_min, x, base_min)),
                acc_max.eq(Mux(x > base_max, x, base_max)),
                acc_count.eq(base_count + 1),
                *[If(zidx == k, acc_zone[k].eq(Mux(self.sink.first, 0, acc_zone[k]) + x))
                  .Elif(self.sink.first, acc_zone[k].eq(0)) for k in range(zones*zones)],
                If(self.sink.last,
                    self.sum.eq(base_sum + x),
                    self.min.eq(Mux(x < base_min, x, base_min)),
                    self.max.eq(Mux(x > base_max, x, base_max)),
                    self.count.eq(base_count + 1),
                    *[self.zone[k].eq(Mux(zidx == k, Mux(self.sink.first, 0, acc_zone[k]) + x,
                                          Mux(self.sink.first, 0, acc_zone[k])))
                      for k in range(zones*zones)],
                    self.update.eq(1),
                ),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_csr(self):
        AW, DW = len(self.sum), self.data_width
        self._control = CSRStorage(fields=[
            CSRField("channel", size=2, offset=0, reset=self.channel.reset.value, description="Measured channel."),
        ])
        self._zone_size = CSRStorage(fields=[
            CSRField("width",  size=16, offset=0,  reset=self.zone_width.reset.value,  description="Zone width (pixels)."),
            CSRField("height", size=16, offset=16, reset=self.zone_height.reset.value, description="Zone height (lines)."),
        ])
        self._sum   = CSRStatus(AW, name="sum", description="Frame sum of the channel.")
        self._minmax = CSRStatus(fields=[
            CSRField("min", size=DW, offset=0,  description="Frame minimum."),
            CSRField("max", size=DW, offset=16, description="Frame maximum."),
        ])
        self._count = CSRStatus(len(self.count), name="count", description="Pixels in the frame.")
        self._zone_index = CSRStorage(bits_for(len(self.zone) - 1) if len(self.zone) > 1 else 1,
                                      name="zone_index", description="Zone to read.")
        self._zone_sum   = CSRStatus(AW, name="zone_sum", description="Sum of the selected zone.")
        self.comb += [
            self.channel.eq(self._control.fields.channel),
            self.zone_width.eq(self._zone_size.fields.width),
            self.zone_height.eq(self._zone_size.fields.height),
            self._sum.status.eq(self.sum), self._minmax.fields.min.eq(self.min),
            self._minmax.fields.max.eq(self.max),
            self._count.status.eq(self.count),
            self._zone_sum.status.eq(Array(self.zone)[self._zone_index.storage]),
        ]

    def add_irq(self):
        self.ev = EventManager()
        self.ev.frame = EventSourcePulse(description="Frame statistics latched.")
        self.ev.finalize()
        self.comb += self.ev.frame.trigger.eq(self.update)
