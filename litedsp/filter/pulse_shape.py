#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout
from litedsp.filter.fir_poly import FIRInterpolator
from litedsp.filter.design   import rrc_coefficients

# Pulse Shaper -------------------------------------------------------------------------------------

class PulseShaper(LiteXModule):
    """Root-raised-cosine pulse-shaping interpolator (``sps`` samples/symbol).

    An interpolating polyphase FIR loaded with RRC taps: maps a 1-sample-per-symbol I/Q stream
    to ``sps`` samples/symbol with matched-filter pulse shaping. Use the same RRC at RX.
    """
    def __init__(self, sps=4, span=8, beta=0.35, data_width=16, with_csr=True):
        self.sps  = sps
        self.span = span
        self.beta = beta
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        n_taps    = sps*span + 1
        coeffs    = rrc_coefficients(sps, span, beta, data_width=data_width, gain=sps)
        self.core = FIRInterpolator(n_taps, sps, data_width=data_width,
            coefficients=coeffs, with_csr=with_csr)
        self.latency = self.core.latency
        self.comb += [self.sink.connect(self.core.sink), self.core.source.connect(self.source)]
