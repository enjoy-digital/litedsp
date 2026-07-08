#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceProcess
from litex.soc.interconnect                  import stream

from litedsp.common import iq_layout, real_layout

# Energy / CFAR Detector ---------------------------------------------------------------------------

@ResetInserter()
class EnergyDetector(LiteXModule):
    """Signal-presence detector with an adaptive noise floor (CFAR-style).

    Passes the I/Q stream through and asserts ``detect`` when instantaneous power exceeds the
    estimated noise floor by ``2**threshold_log2``. The floor is a leaky average of power,
    updated only while no signal is detected (so the signal does not raise the floor).
    With ``with_irq=True``, a detection edge raises an interrupt (``ev.detect``).
    """
    def __init__(self, data_width=16, avg_shift=10, threshold_log2=3, with_csr=True, with_irq=False):
        self.threshold_log2 = threshold_log2
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.detect = Signal()

        # # #

        self.comb += self.sink.connect(self.source)
        xfer = Signal()
        self.comb += xfer.eq(self.sink.valid & self.sink.ready)

        pw    = Signal(2*data_width + 1)
        # Start high so the floor converges DOWN to the noise level (avoids the bootstrap where
        # floor=0 makes everything look like signal and the floor never adapts).
        floor = Signal(2*data_width + 1, reset=1 << (2*data_width - 1))
        self.comb += pw.eq(self.sink.i*self.sink.i + self.sink.q*self.sink.q)
        self.comb += self.detect.eq(pw > (floor << threshold_log2))
        self.sync += If(xfer & ~self.detect,                        # Track noise only.
            floor.eq(floor + ((pw - floor) >> avg_shift)),
        )

        if with_csr:
            self._status = CSRStatus(fields=[CSRField("detect", size=1, description="Signal present.")])
            self.comb += self._status.fields.detect.eq(self.detect)
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev        = EventManager()
        self.ev.detect = EventSourceProcess(edge="rising", description="Signal detected (power above floor).")
        self.ev.finalize()
        self.comb += self.ev.detect.trigger.eq(self.detect)

# Frequency Estimator (firmware-assisted parabolic) ------------------------------------------------

@ResetInserter()
class FrequencyEstimator(LiteXModule):
    """Find the peak bin of a framed real spectrum and expose the 3 bins around it.

    Per frame (delimited by ``sink.first``/``sink.last``), emits ``index`` (argmax) plus the
    peak value and its left/right neighbours so firmware can do 3-point parabolic interpolation
    for a sub-bin frequency estimate (keeping the divide off-chip).
    """
    def __init__(self, data_width=32, index_width=12, with_csr=True):
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint([
            ("index", index_width), ("peak", data_width),
            ("left", data_width), ("right", data_width),
        ])
        self.latency = 1

        # # #

        idx       = Signal(index_width)
        best_idx  = Signal(index_width)
        best_val  = Signal(data_width)
        best_left = Signal(data_width)
        best_right= Signal(data_width)
        prev      = Signal(data_width)
        cap_right = Signal()                          # Next sample is the peak's right neighbour.

        self.comb += self.sink.ready.eq(self.source.ready | ~self.source.valid)
        xfer = Signal()
        self.comb += xfer.eq(self.sink.valid & self.sink.ready)
        better = Signal()
        self.comb += better.eq(self.sink.first | (self.sink.data > best_val))

        self.sync += [
            If(self.source.valid & self.source.ready, self.source.valid.eq(0)),
            If(xfer,
                prev.eq(self.sink.data),
                If(cap_right, best_right.eq(self.sink.data), cap_right.eq(0)),
                If(better,
                    best_val.eq(self.sink.data),
                    best_idx.eq(idx),
                    best_left.eq(Mux(self.sink.first, 0, prev)),
                    cap_right.eq(1),
                ),
                idx.eq(Mux(self.sink.last, 0, idx + 1)),
                If(self.sink.last,
                    self.source.index.eq(Mux(better, idx, best_idx)),
                    self.source.peak.eq(Mux(better, self.sink.data, best_val)),
                    self.source.left.eq(Mux(better, Mux(self.sink.first, 0, prev), best_left)),
                    self.source.right.eq(best_right),
                    self.source.valid.eq(1),
                )
            )
        ]
