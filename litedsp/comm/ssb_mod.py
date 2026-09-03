#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Single-sideband modulator (phasing method) onto a complex baseband."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common         import check, real_layout, iq_layout
from litedsp.filter.hilbert import LiteDSPHilbert

# SSB Modulator ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSSBModulator(LiteXModule):
    """SSB by the phasing method: ``s = x + j * sgn * hilbert(x)`` on a complex baseband
    (``sideband`` runtime: 0 upper, 1 lower), the Q path negated with saturation for LSB. Feed a
    DUC for the RF carrier. Latency = the Hilbert filter's (``n_taps`` odd, ``(n_taps - 1) / 2``
    group delay on the I path). Opposite-sideband rejection is set by the Hilbert length
    (~40 dB with 31 taps away from DC).
    """
    def __init__(self, n_taps=31, data_width=16, with_csr=True):
        check(n_taps >= 11 and n_taps % 2 == 1, "expected an odd n_taps >= 11")
        self.data_width = data_width
        self.hilbert  = LiteDSPHilbert(n_taps=n_taps, data_width=data_width, with_csr=False)
        self.latency  = self.hilbert.latency
        self.sink     = self.hilbert.sink
        self.source   = stream.Endpoint(iq_layout(data_width))
        self.sideband = Signal()

        # # #

        DW = data_width
        q  = self.hilbert.source.q
        neg = Signal((DW, True))
        self.comb += [
            neg.eq(Mux(q == -(1 << (DW - 1)), (1 << (DW - 1)) - 1, -q)),   # Saturating negate.
            self.hilbert.source.connect(self.source, omit={"q"}),
            self.source.q.eq(Mux(self.sideband, neg, q)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("sideband", size=1, offset=0, description="0: upper sideband, 1: lower sideband."),
        ])
        self.comb += self.sideband.eq(self._control.fields.sideband)
