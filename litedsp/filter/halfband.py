#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Half-band FIR decimate/interpolate by 2.

Half-band low-pass filters have ~half their taps equal to zero (and a center tap of ~0.5),
making them the efficient choice for 2x rate change. These wrap the polyphase FIR with
half-band coefficients; pruning the zero taps from the MAC schedule is a future optimization.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout
from litedsp.filter.fir_poly import LiteDSPFIRDecimator, LiteDSPFIRInterpolator
from litedsp.filter.design   import halfband_coefficients

# Half-band Decimator ------------------------------------------------------------------------------

class LiteDSPHalfbandDecimator(LiteXModule):
    """Decimate-by-2 half-band FIR."""
    def __init__(self, n_taps=23, data_width=16, with_csr=True):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        coeffs    = halfband_coefficients(n_taps, data_width=data_width)
        self.core = LiteDSPFIRDecimator(n_taps, 2, data_width=data_width, coefficients=coeffs, with_csr=with_csr)
        self.latency = self.core.latency
        self.comb += [self.sink.connect(self.core.sink), self.core.source.connect(self.source)]

# Half-band Interpolator ---------------------------------------------------------------------------

class LiteDSPHalfbandInterpolator(LiteXModule):
    """Interpolate-by-2 half-band FIR."""
    def __init__(self, n_taps=23, data_width=16, with_csr=True):
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        coeffs    = halfband_coefficients(n_taps, data_width=data_width, gain=2.0)
        self.core = LiteDSPFIRInterpolator(n_taps, 2, data_width=data_width, coefficients=coeffs, with_csr=with_csr)
        self.latency = self.core.latency
        self.comb += [self.sink.connect(self.core.sink), self.core.source.connect(self.source)]
