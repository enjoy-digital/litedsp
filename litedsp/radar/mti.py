#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Moving-target indication: pulse-to-pulse cancellers on fast-time (per-pulse) frames."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, scaled, add_bypass, add_bypass_csr

# MTI Canceller ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPMTICanceller(LiteXModule):
    """Two- or three-pulse MTI canceller on framed pulses (one frame = ``n_range_bins`` beats).

    Range bin ``r`` of the previous ``order - 1`` pulses is kept in ``order - 1`` RAMs indexed
    by a range counter that ``first`` resets. Runtime ``mode`` 0 subtracts the previous pulse
    (``y = x - x1``), mode 1 the three-pulse binomial (``y = x - 2 x1 + x2``, needs
    ``order == 3``); the difference is rescaled by ``shift`` (default ``mode + 1``, the
    canceller's DC gain, so the output never saturates). Stationary clutter cancels exactly;
    a target moving ``f`` cycles per pulse is weighted ``|2 sin(pi f)|`` (``4 sin^2(pi f)``).
    Latency 1; ``bypass`` passes pulses through unchanged.
    """
    def __init__(self, n_range_bins=64, data_width=16, order=3, shift=None, with_csr=True):
        check(n_range_bins >= 1, "expected n_range_bins >= 1")
        check(order in (2, 3), "expected order in (2, 3)")
        check(shift is None or 0 <= shift <= 2, "expected 0 <= shift <= 2")
        self.n_range_bins = n_range_bins
        self.data_width   = data_width
        self.order        = order
        self.latency      = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.mode   = Signal(reset=int(order == 3))                    # 0: 2-pulse, 1: 3-pulse.
        self.bypass = Signal()

        # # #

        adv, xfer = Signal(), Signal()
        r = Signal(max=n_range_bins)
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]
        addr = Signal(max=n_range_bins)                                 # Bin of this beat.
        self.comb += addr.eq(Mux(self.sink.first, 0, r))
        self.sync += If(xfer,
            If(addr == n_range_bins - 1, r.eq(0)).Else(r.eq(addr + 1)),
        )
        W = 2*data_width
        x = Cat(self.sink.i, self.sink.q)
        # History RAMs (previous pulses at this range bin): read before write on every transfer.
        hist = []
        prev = x
        for k in range(order - 1):
            mem = Memory(W, n_range_bins)
            rp  = mem.get_port(async_read=True)
            wp  = mem.get_port(write_capable=True)
            self.specials += mem, rp, wp
            self.comb += [rp.adr.eq(addr), wp.adr.eq(addr), wp.we.eq(xfer), wp.dat_w.eq(prev)]
            hist.append(rp.dat_r)
            prev = rp.dat_r                                             # RAM k+1 <- old RAM k value.
        mode3 = self.mode if order == 3 else Constant(0)
        for c, sl in (("i", slice(0, data_width)), ("q", slice(data_width, W))):
            xi  = getattr(self.sink, c)
            x1i = Signal((data_width, True))
            self.comb += x1i.eq(hist[0][sl])
            diff = Signal((data_width + 2, True))
            if order == 3:
                x2i = Signal((data_width, True))
                self.comb += [x2i.eq(hist[1][sl]), diff.eq(Mux(mode3, xi - (x1i << 1) + x2i, xi - x1i))]
            else:
                self.comb += diff.eq(xi - x1i)
            if shift is None:
                out = Mux(mode3, scaled(diff, 2, data_width)[0], scaled(diff, 1, data_width)[0])
            else:
                out = scaled(diff, shift, data_width)[0]
            self.sync += If(adv, getattr(self.source, c).eq(out))
        self.sync += If(adv,
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
        )

        # Bypass / CSR.
        # -------------
        add_bypass(self)
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("mode",   size=1, offset=0, reset=int(self.order == 3), description="0: 2-pulse, 1: 3-pulse canceller."),
        ])
        self.comb += self.mode.eq(self._control.fields.mode)
        add_bypass_csr(self)
