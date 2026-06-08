#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common        import iq_layout
from litedsp.filter.farrow import FarrowInterpolator

# Gardner Symbol Timing Recovery -------------------------------------------------------------------

@ResetInserter()
class TimingRecovery(LiteXModule):
    """Gardner symbol timing recovery for a 2-samples/symbol I/Q input.

    A Farrow interpolator resamples the input at a loop-controlled fractional phase; the Gardner
    TED ``e = mid*(strobe - prev_strobe)`` (I and Q) drives a leaky integrator that adjusts the
    interpolation phase. Outputs one (timing-aligned) sample per symbol. ``mu_shift`` sets the
    loop time constant.

    WORK IN PROGRESS: this skeleton adjusts only the fractional phase ``mu``. A complete Gardner
    synchronizer also needs an interpolation *controller* that handles integer sample-slip
    (selecting which sample of each symbol is the strobe) so it can acquire arbitrary timing
    offsets; that piece is not yet implemented and convergence is not guaranteed.
    """
    def __init__(self, data_width=16, frac_bits=15, mu_shift=22, with_csr=True):
        self.data_width = data_width
        self.mu_shift   = mu_shift
        self.sink   = stream.Endpoint(iq_layout(data_width))      # 2 samples/symbol.
        self.source = stream.Endpoint(iq_layout(data_width))      # 1 sample/symbol.

        # # #

        self.farrow = FarrowInterpolator(data_width=data_width, frac_bits=frac_bits, with_csr=False)
        mu = Signal(frac_bits, reset=1 << (frac_bits - 1))        # Start mid-sample.
        self.comb += [self.farrow.mu.eq(mu), self.sink.connect(self.farrow.sink)]
        f = self.farrow.source

        toggle  = Signal()                                       # 0: mid sample, 1: strobe.
        mid_i   = Signal((data_width, True))
        mid_q   = Signal((data_width, True))
        prev_i  = Signal((data_width, True))
        prev_q  = Signal((data_width, True))

        # Consume every interpolated sample; on strobe also emit a symbol (with backpressure).
        out_ok = Signal()
        self.comb += [
            out_ok.eq(self.source.ready | ~self.source.valid),
            f.ready.eq(Mux(toggle, out_ok, 1)),                 # Mid: free; strobe: wait for output.
        ]
        consume = Signal()
        self.comb += consume.eq(f.valid & f.ready)

        # Gardner error (computed on a strobe) and leaky-integrator phase update.
        err = Signal((2*data_width + 2, True))
        self.comb += err.eq(mid_i*(f.i - prev_i) + mid_q*(f.q - prev_q))

        self.sync += [
            If(consume,
                toggle.eq(~toggle),
                If(~toggle,
                    mid_i.eq(f.i), mid_q.eq(f.q),               # Store midpoint.
                ).Else(
                    # Strobe: update timing phase, emit symbol, remember it.
                    mu.eq(mu + (err >> mu_shift)),
                    prev_i.eq(f.i), prev_q.eq(f.q),
                    self.source.i.eq(f.i), self.source.q.eq(f.q),
                    self.source.valid.eq(1),
                )
            ),
            If(self.source.valid & self.source.ready & ~(consume & toggle),
                self.source.valid.eq(0),
            ),
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._mu = CSRStatus(16, name="mu", description="Current interpolation phase.")
        self.comb += self._mu.status.eq(self.farrow.mu)
