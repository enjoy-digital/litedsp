#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common  import iq_layout
from litedsp.numeric import LiteDSPISqrt

# RMS ----------------------------------------------------------------------------------------------

class LiteDSPRMS(LiteXModule):
    """RMS magnitude over ``2**window_log2`` samples: ``sqrt(mean(I**2 + Q**2))``.

    Accumulates instantaneous power over a window, averages (shift), and takes the square root
    (:class:`LiteDSPISqrt`). Emits one RMS value per completed window on ``source`` (framed). The
    input is always accepted (the source is produced once per window).
    """
    def __init__(self, data_width=16, window_log2=8, max_window_log2=20, with_csr=True):
        self.data_width = data_width
        acc_width       = 2*data_width + max_window_log2
        self.sink   = stream.Endpoint(iq_layout(data_width))

        # # #

        # ISqrt Core.
        # -----------
        # Sequential sqrt: RMS emits once per window, so the multi-cycle (small) ISqrt is free.
        self.isqrt = LiteDSPISqrt(in_width=2*data_width, pipelined=False, with_csr=False)
        self.source = stream.Endpoint([("data", self.isqrt.out_width)])
        self.window_log2 = Signal(max=max_window_log2 + 1, reset=window_log2)

        # Accumulator.
        # ------------
        inst  = Signal(2*data_width + 1)
        acc   = Signal(acc_width)
        count = Signal(max_window_log2 + 1)
        last  = Signal()
        self.comb += [
            inst.eq(self.sink.i*self.sink.i + self.sink.q*self.sink.q),
            last.eq(count == ((1 << self.window_log2) - 1)),
            self.sink.ready.eq(1),                       # Always consume; emit once per window.
        ]
        avg = Signal(2*data_width)
        self.comb += avg.eq((acc + inst) >> self.window_log2)
        self.sync += [
            self.isqrt.sink.valid.eq(0),
            If(self.sink.valid,
                If(last,
                    self.isqrt.sink.valid.eq(1),
                    self.isqrt.sink.data.eq(avg),
                    acc.eq(0),
                    count.eq(0),
                ).Else(
                    acc.eq(acc + inst),
                    count.eq(count + 1),
                )
            )
        ]

        # Output.
        # -------
        self.comb += self.isqrt.source.connect(self.source)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._window = CSRStorage(self.window_log2.nbits, reset=self.window_log2.reset.value,
            name="window", description="RMS window as power of two (2**window_log2).")
        self.comb += self.window_log2.eq(self._window.storage)
