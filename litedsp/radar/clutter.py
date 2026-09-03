#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Clutter map: per-cell exponential average across scans as the detection threshold."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, real_layout, cell_layout

# Clutter Map --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPClutterMap(LiteXModule):
    """Scan-to-scan clutter map detector on framed cell streams.

    Keeps one exponential average per cell (``n_range_bins * n_doppler_bins`` cells, addressed
    by a counter that ``first`` restarts) in a RAM holding ``sum = average << avg_shift``:
    ``sum += x - (sum >> avg_shift)`` on every scan unless the cell detects (censored update,
    overridden by ``learn_all``) or ``freeze`` is set. The scan after reset or ``clear`` (up to its ``last``)
    initialises the visited cells (``sum = x << avg_shift``, no detection); scans must cover every
    cell. ``threshold =
    rounded(sum * alpha, threshold_frac + avg_shift)`` saturated and floored at ``threshold_min``,
    ``detect = x > threshold``. Output on :func:`~litedsp.common.cell_layout`; latency 4.
    """
    def __init__(self, n_range_bins=64, n_doppler_bins=1, data_width=17, avg_shift=3, alpha_width=16,
        threshold_frac=8, with_csr=True):
        check(1 <= avg_shift <= 8, "expected 1 <= avg_shift <= 8")
        check(n_range_bins*n_doppler_bins >= 8, "expected at least 8 cells (the update pipeline depth)")
        check(0 < threshold_frac < alpha_width, "expected 0 < threshold_frac < alpha_width")
        self.n_range_bins   = n_range_bins
        self.n_doppler_bins = n_doppler_bins
        self.data_width     = data_width
        self.avg_shift      = avg_shift
        self.alpha_width    = alpha_width
        self.threshold_frac = threshold_frac
        self.latency        = 4
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(cell_layout(data_width))
        self.alpha         = Signal(alpha_width, reset=int(round(4.0*(1 << threshold_frac))))
        self.threshold_min = Signal(data_width)
        self.learn_all     = Signal()
        self.freeze        = Signal()
        self.clear         = Signal()                                   # Invalidate the map.
        self.detections    = Signal(32)
        self.scans         = Signal(32)

        # # #

        n_cells = n_range_bins*n_doppler_bins
        SW   = data_width + avg_shift
        init = Signal(reset=1)                                          # Initialisation scan.
        self.specials.mem = mem = Memory(SW, n_cells)
        rp = mem.get_port(has_re=True)
        wp = mem.get_port(write_capable=True)
        self.specials += rp, wp
        adv, xfer = Signal(), Signal()
        addr = Signal(max=n_cells)
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
            rp.adr.eq(Mux(self.sink.first, 0, addr)),
            rp.re.eq(adv),
        ]
        self.sync += [
            If(xfer,
                If(self.sink.first,
                    addr.eq(1 % n_cells),
                    self.scans.eq(self.scans + 1),
                ).Elif(addr == n_cells - 1,
                    addr.eq(0),
                ).Else(
                    addr.eq(addr + 1),
                ),
            ),
            If(self.clear,
                init.eq(1),
            ).Elif(xfer & self.sink.last,
                init.eq(0),
            ),
        ]

        # S1: cell, tags, the map entry; S2 / S3: products; S4: decision, output, write back.
        # ------------------------------------------------------------------------------------
        recip = 1 << (16 - avg_shift)
        x1, v1, f1, l1 = Signal(data_width), Signal(), Signal(), Signal()
        a1   = Signal(max=n_cells)
        valid1 = Signal()
        self.sync += If(adv, x1.eq(self.sink.data), v1.eq(xfer), f1.eq(self.sink.first), l1.eq(self.sink.last),
                        a1.eq(rp.adr), valid1.eq(~init))
        s_old  = Signal(SW)
        self.comb += s_old.eq(rp.dat_r)
        p1 = Signal(SW + alpha_width)
        p2 = Signal(SW + alpha_width + 17)
        x2, v2, f2, l2, a2, s2, ok2 = Signal(data_width), Signal(), Signal(), Signal(), Signal(max=n_cells), Signal(SW), Signal()
        x3, v3, f3, l3, a3, s3, ok3 = Signal(data_width), Signal(), Signal(), Signal(), Signal(max=n_cells), Signal(SW), Signal()
        thr_full = Signal(SW + alpha_width + 17)
        thr_r    = Signal(SW + alpha_width + 1)
        thr_c    = Signal(data_width)
        thr      = Signal(data_width)
        detect   = Signal()
        s_new    = Signal(SW)
        s_upd    = Signal(SW + 1)
        self.comb += [
            thr_full.eq(p2 + (1 << (threshold_frac + 15))),
            thr_r.eq(thr_full[threshold_frac + 16:]),
            thr_c.eq(Mux(thr_r > (1 << data_width) - 1, (1 << data_width) - 1, thr_r[:data_width])),
            thr.eq(Mux(ok3, Mux(thr_c < self.threshold_min, self.threshold_min, thr_c), (1 << data_width) - 1)),
            detect.eq(ok3 & (x3 > thr)),
            s_upd.eq(s3 + x3 - (s3 >> avg_shift)),
            s_new.eq(Mux(ok3, Mux(detect & ~self.learn_all, s3, s_upd[:SW]), x3 << avg_shift)),   # Positive select.
            wp.adr.eq(a3), wp.dat_w.eq(s_new), wp.we.eq(adv & v3 & ~self.freeze),
        ]
        self.sync += [
            If(adv,
                p1.eq(s_old*self.alpha), x2.eq(x1), v2.eq(v1), f2.eq(f1), l2.eq(l1), a2.eq(a1), s2.eq(s_old), ok2.eq(valid1),
                p2.eq(p1*recip),         x3.eq(x2), v3.eq(v2), f3.eq(f2), l3.eq(l2), a3.eq(a2), s3.eq(s2), ok3.eq(ok2),
                self.source.valid.eq(v3),
                self.source.data.eq(x3),
                self.source.threshold.eq(thr),
                self.source.detect.eq(detect),
                self.source.first.eq(f3),
                self.source.last.eq(l3),
            ),
            If(adv & v3 & detect, self.detections.eq(self.detections + 1)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._alpha = CSRStorage(self.alpha_width, reset=self.alpha.reset.value, name="alpha",
            description=f"Threshold factor on the cell's clutter average (unsigned Q.{self.threshold_frac}).")
        self._threshold_min = CSRStorage(self.data_width, name="threshold_min", description="Threshold floor (unsigned cell units).")
        self._control = CSRStorage(fields=[
            CSRField("learn_all", size=1, offset=0, description="Update the map with detected cells too."),
            CSRField("freeze",    size=1, offset=1, description="Stop updating the map."),
            CSRField("clear",     size=1, offset=2, pulse=True, description="Invalidate the map (re-learned on the next scan)."),
        ])
        self._config = CSRStatus(fields=[
            CSRField("n_cells",   size=20, offset=0,  description="Map cells."),
            CSRField("avg_shift", size=4,  offset=20, description="Averaging time constant (scans = 2^avg_shift)."),
            CSRField("frac",      size=8,  offset=24, description="Fractional bits of alpha."),
        ])
        self._detections = CSRStatus(32, name="detections", description="Detections since reset.")
        self._scans      = CSRStatus(32, name="scans", description="Scans (frames) since reset.")
        self.comb += [
            self.alpha.eq(self._alpha.storage),
            self.threshold_min.eq(self._threshold_min.storage),
            self.learn_all.eq(self._control.fields.learn_all),
            self.freeze.eq(self._control.fields.freeze),
            self.clear.eq(self._control.fields.clear),
            self._config.fields.n_cells.eq(self.n_range_bins*self.n_doppler_bins),
            self._config.fields.avg_shift.eq(self.avg_shift),
            self._config.fields.frac.eq(self.threshold_frac),
            self._detections.status.eq(self.detections),
            self._scans.status.eq(self.scans),
        ]
