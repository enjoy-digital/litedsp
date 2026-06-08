#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common            import iq_layout, real_layout, scaled
from litedsp.generation.cordic import CORDIC

# FM Demodulator -----------------------------------------------------------------------------------

class FMDemod(LiteXModule):
    """FM discriminator: instantaneous frequency = ``angle(x[n] * conj(x[n-1]))``.

    Computes the complex product of each sample with the conjugate of the previous one
    (a phase-difference vector), then takes its angle with a CORDIC in vectoring mode. No phase
    unwrapping needed. Output is the per-sample phase increment (proportional to frequency).
    """
    def __init__(self, data_width=16, angle_width=16, with_csr=True):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(real_layout(angle_width))

        # # #

        self.cordic = CORDIC(data_width=data_width, angle_width=angle_width,
            mode="vectoring", with_csr=False)
        self.latency = self.cordic.latency

        prev_i = Signal((data_width, True))
        prev_q = Signal((data_width, True))
        i, q   = self.sink.i, self.sink.q
        # z = x[n] * conj(x[n-1]); rescale both parts equally (angle is scale-invariant).
        zx, _ = scaled(i*prev_i + q*prev_q, data_width - 1, data_width)
        zy, _ = scaled(q*prev_i - i*prev_q, data_width - 1, data_width)
        self.comb += [
            self.cordic.sink.valid.eq(self.sink.valid),
            self.cordic.sink.x.eq(zx),                     # Re{x · conj(x_prev)}.
            self.cordic.sink.y.eq(zy),                     # Im{x · conj(x_prev)}.
            self.sink.ready.eq(self.cordic.sink.ready),
        ]
        self.sync += If(self.sink.valid & self.sink.ready,
            prev_i.eq(i), prev_q.eq(q),
        )
        self.comb += [
            self.source.valid.eq(self.cordic.source.valid),
            self.source.data.eq(self.cordic.source.angle),
            self.cordic.source.ready.eq(self.source.ready),
        ]
