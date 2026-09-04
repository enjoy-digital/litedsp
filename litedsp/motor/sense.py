#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Current sensing: isolated sigma-delta demodulation with a fast over-current path, and an
over-current trip on a three-phase sample stream."""

from functools import reduce
from operator  import and_, or_

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceProcess
from litex.soc.interconnect                  import stream

from litedsp.common           import check, abc_layout, real_layout
from litedsp.filter.bitstream import LiteDSPBitstreamDecimator, bitstream_shift

# Sigma-Delta Current Sense ------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSigmaDeltaFilter(LiteXModule):
    """Isolated sigma-delta current sense: per-phase sinc^N demodulators + fast trip path.

    ``sinks[k]`` carry the modulator bitstreams of the ``n_channels`` phases (consumed in
    lock-step); ``source`` emits the demodulated currents (``abc_layout`` for three channels,
    ``real_layout`` for one) at ``1/rate`` of the bit rate through the runtime-rate
    :class:`~litedsp.filter.bitstream.LiteDSPBitstreamDecimator` (``rate``/``shift``
    controls, reset from ``decimation``). Every phase also feeds a second, short sinc^N of fixed
    ``fast_decimation`` whose output is compared against ``threshold``: an over-current trips
    the per-phase sticky ``overcurrent`` bits (cleared by ``clear``; ``ev.overcurrent`` with
    ``with_irq=True``) within ``fast_decimation`` bits, independently of the slower control
    path. Latency 1 (as the runtime CIC).

    Parameters
    ----------
    n_channels : int
        Number of phases (1 or 3).
    decimation : int
        Reset decimation rate of the control path (bits per sample).
    n_stages : int
        Sinc order of both paths (3 is the usual choice for current sense).
    r_max : int
        Maximum runtime rate of the control path.
    fast_decimation : int
        Fixed decimation of the over-current path (short, e.g. 8-32 bits).
    """
    def __init__(self, data_width=16, n_channels=3, decimation=64, n_stages=3, r_max=256,
        fast_decimation=16, with_csr=True, with_irq=False):
        check(n_channels in (1, 3), "expected n_channels in (1, 3)")
        check(fast_decimation >= 2, "expected fast_decimation >= 2")
        self.data_width      = data_width
        self.n_channels      = n_channels
        self.decimation      = decimation
        self.fast_decimation = fast_decimation
        self.latency         = 1
        self.sinks  = [stream.Endpoint([("data", 1)]) for _ in range(n_channels)]
        self.source = stream.Endpoint(abc_layout(data_width) if n_channels == 3
                                      else real_layout(data_width))
        self.threshold   = Signal(data_width, reset=(1 << (data_width - 1)) - 1)  # Trip level.
        self.clear       = Signal()                                # Clear the trip flags.
        self.overcurrent = Signal(n_channels)                      # Sticky per-phase trips.
        self.fast_value  = [Signal((data_width, True)) for _ in range(n_channels)]

        # # #

        fields = ["a", "b", "c"] if n_channels == 3 else ["data"]

        # Demodulators (control path, runtime rate) and fast trip path per phase.
        # ---------------------------------------------------------------------
        self.mains = []
        self.fasts = []
        for k in range(n_channels):
            main = LiteDSPBitstreamDecimator(data_width=data_width, decimation=decimation,
                n_stages=n_stages, r_max=r_max, with_csr=False)
            fast = LiteDSPBitstreamDecimator(data_width=data_width, decimation=fast_decimation,
                n_stages=n_stages, with_csr=False)
            self.add_module(name=f"main{k}", module=main)
            self.add_module(name=f"fast{k}", module=fast)
            self.mains.append(main)
            self.fasts.append(fast)
        self.rate, self.shift = self.mains[0].rate, self.mains[0].shift
        for main in self.mains[1:]:
            self.comb += [main.rate.eq(self.rate), main.shift.eq(self.shift)]

        # Lock-step join of the bit sinks (the fast paths never stall: always-ready sources).
        # ---------------------------------------------------------------------------------
        all_valid = reduce(and_, [s.valid for s in self.sinks])
        all_ready = reduce(and_,
                           [m.sink.ready for m in self.mains] + [f.sink.ready for f in self.fasts])
        go        = Signal()
        self.comb += go.eq(all_valid & all_ready)
        for k in range(n_channels):
            self.comb += [
                self.sinks[k].ready.eq(go),
                self.mains[k].sink.valid.eq(go),
                self.mains[k].sink.data.eq(self.sinks[k].data),
                self.fasts[k].sink.valid.eq(go),
                self.fasts[k].sink.data.eq(self.sinks[k].data),
                self.fasts[k].source.ready.eq(1),
            ]

        # Control-path output (the lock-stepped demodulators emit together).
        # -----------------------------------------------------------------
        self.comb += self.source.valid.eq(self.mains[0].source.valid)
        for k, field in enumerate(fields):
            self.comb += [
                getattr(self.source, field).eq(self.mains[k].source.data),
                self.mains[k].source.ready.eq(self.source.ready),
            ]

        # Fast path: latch, compare, latch trips.
        # ---------------------------------------
        trips = []
        for k in range(n_channels):
            fast = self.fasts[k]
            mag  = Signal(data_width + 1)
            trip = Signal()
            self.comb += [
                mag.eq(Mux(fast.source.data[-1], -fast.source.data, fast.source.data)),
                trip.eq(fast.source.valid & (mag > self.threshold)),
            ]
            self.sync += [
                If(fast.source.valid, self.fast_value[k].eq(fast.source.data)),
                If(self.clear, self.overcurrent[k].eq(0)).Elif(trip, self.overcurrent[k].eq(1)),
            ]
            trips.append(trip)

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev = EventManager()
        self.ev.overcurrent = EventSourceProcess(edge="rising",
            description="A phase current exceeded the trip threshold (fast path).")
        self.ev.finalize()
        self.comb += self.ev.overcurrent.trigger.eq(reduce(or_, [self.overcurrent[k]
            for k in range(self.n_channels)]))

    def add_csr(self):
        self._rate  = CSRStorage(len(self.rate), reset=self.rate.reset.value, name="rate",
            description="Control-path decimation rate (bits per sample).")
        self._shift = CSRStorage(len(self.shift), reset=self.shift.reset.value, name="shift",
            description="Control-path rescale shift (bitstream_shift(rate, ...)).")
        self._threshold = CSRStorage(self.data_width, reset=self.threshold.reset.value,
            name="threshold", description="Over-current trip magnitude (fast path, per-unit).")
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the trip flags."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("overcurrent", size=self.n_channels, description="Sticky per-phase trips."),
        ])
        self.comb += [
            self.rate.eq(self._rate.storage),
            self.shift.eq(self._shift.storage),
            self.threshold.eq(self._threshold.storage),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.overcurrent.eq(self.overcurrent),
        ]
        for k in range(self.n_channels):
            csr = CSRStatus(self.data_width, name=f"fast_value{k}",
                description=f"Last fast-path sample of phase {k}.")
            setattr(self, f"_fast_value{k}", csr)
            self.comb += csr.status.eq(self.fast_value[k])

# Over-Current Trip --------------------------------------------------------------------------------

class LiteDSPOvercurrentTrip(LiteXModule):
    """Window comparator on a three-phase stream: combinational passthrough + sticky trip.

    Any accepted sample with ``|phase| > threshold`` sets ``fault`` (sticky), the ``phase``
    bit(s) that tripped and increments ``count``; ``clear`` releases them. Wire ``fault`` to
    :class:`~litedsp.motor.pwm.LiteDSPPWM`'s ``fault`` input to switch the inverter off within
    one cycle. ``with_irq=True`` adds ``ev.fault``. Latency 0.
    """
    def __init__(self, data_width=16, with_csr=True, with_irq=False):
        check(data_width >= 4, "expected data_width >= 4")
        self.data_width = data_width
        self.latency    = 0
        self.sink   = stream.Endpoint(abc_layout(data_width))
        self.source = stream.Endpoint(abc_layout(data_width))
        self.threshold = Signal(data_width, reset=(1 << (data_width - 1)) - 1)  # Trip magnitude.
        self.clear     = Signal()
        self.fault     = Signal()                                  # Sticky trip.
        self.phase     = Signal(3)                                 # Sticky per-phase trips.
        self.count     = Signal(32)                                # Trips since clear.

        # # #

        # Passthrough.
        # ------------
        self.comb += self.sink.connect(self.source)
        xfer = Signal()
        self.comb += xfer.eq(self.sink.valid & self.sink.ready)

        # Comparators.
        # ------------
        over = Signal(3)
        for k, field in enumerate(("a", "b", "c")):
            x   = getattr(self.sink, field)
            mag = Signal(data_width + 1)
            self.comb += [mag.eq(Mux(x[-1], -x, x)), over[k].eq(mag > self.threshold)]
        trip = Signal()
        self.comb += trip.eq(xfer & (over != 0))
        self.sync += [
            If(self.clear,
                self.fault.eq(0), self.phase.eq(0), self.count.eq(0),
            ).Elif(trip,
                self.fault.eq(1), self.phase.eq(self.phase | over), self.count.eq(self.count + 1),
            ),
        ]

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev       = EventManager()
        self.ev.fault = EventSourceProcess(edge="rising", description="Over-current trip.")
        self.ev.finalize()
        self.comb += self.ev.fault.trigger.eq(self.fault)

    def add_csr(self):
        self._threshold = CSRStorage(self.data_width, reset=self.threshold.reset.value,
            name="threshold", description="Trip magnitude (per-unit).")
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear fault, phases and count."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("fault", size=1, offset=0, description="Sticky trip."),
            CSRField("phase", size=3, offset=1, description="Phases that tripped (a, b, c)."),
        ])
        self._count = CSRStatus(32, name="count", description="Trips since clear.")
        self.comb += [
            self.threshold.eq(self._threshold.storage),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.fault.eq(self.fault),
            self._status.fields.phase.eq(self.phase),
            self._count.status.eq(self.count),
        ]
