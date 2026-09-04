#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, real_layout, add_bypass, add_bypass_csr

# Slew Limiter -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSlewLimiter(LiteXModule):
    """Rate limiter for references (speed/torque ramps): ``y += clamp(x - y, +/-rate)``.

    The output follows the input at most ``rate`` per accepted sample (a trapezoidal ramp
    generator when fed a setpoint step), reaching a step of size ``D`` in exactly
    ``ceil(D/rate)`` samples with no overshoot. ``rate`` is a positive per-sample increment
    (reset: full scale = limiter off); ``bypass`` passes the input through. Fixed 1-cycle
    latency, no multiplier.
    """
    def __init__(self, data_width=16, with_csr=True):
        check(data_width >= 4, "expected data_width >= 4")
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(real_layout(data_width))
        self.rate   = Signal(data_width, reset=(1 << (data_width - 1)) - 1)  # Max step/sample.

        # # #

        # Handshake.
        # ----------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath: step toward the input, clamped to +/-rate.
        # ----------------------------------------------------
        y      = Signal((data_width, True))          # Last emitted value (state).
        delta  = Signal((data_width + 1, True))
        step   = Signal((data_width + 1, True))
        y_next = Signal((data_width, True))
        self.comb += [
            delta.eq(self.sink.data - y),
            step.eq(Mux(delta > self.rate, self.rate, Mux(delta < -self.rate, -self.rate, delta))),
            y_next.eq(y + step),                     # Never leaves [min(x, y), max(x, y)].
        ]
        self.sync += If(xfer, y.eq(y_next))

        # Output.
        # -------
        self.sync += If(adv,
            self.source.data.eq(y_next),
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
        )
        add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._rate = CSRStorage(self.data_width, reset=(1 << (self.data_width - 1)) - 1,
                                name="rate",
            description="Maximum change per sample (positive; full scale disables the limiter).")
        self.comb += self.rate.eq(self._rate.storage)
        add_bypass_csr(self)
