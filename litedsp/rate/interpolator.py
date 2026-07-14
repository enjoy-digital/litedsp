#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout
from litedsp.filter.cic      import LiteDSPCICInterpolator
from litedsp.filter.fir_poly import LiteDSPFIRInterpolator
from litedsp.filter.design   import firwin_lowpass

# Interpolator -------------------------------------------------------------------------------------

class LiteDSPInterpolator(LiteXModule):
    """Integer interpolator: rate expand + anti-image filter.

    ``method="cic"`` (default) uses a portable CIC; ``method="fir"`` uses a polyphase
    interpolating FIR with a windowed-sinc low-pass (gain ``L`` to offset zero-stuff loss).
    """
    def __init__(self, data_width=16, factor=8, method="cic", n_taps=None, cutoff=0.4,
        stages=4, with_csr=True):
        assert method in ["cic", "fir"]
        self.factor = factor
        self.method = method
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        if method == "cic":
            self.core = LiteDSPCICInterpolator(data_width=data_width, R=factor, N=stages, with_csr=with_csr)
        else:
            n_taps = n_taps or (8*factor + 1)  # ~8 taps per polyphase branch.
            coeffs = firwin_lowpass(n_taps, cutoff/factor, data_width=data_width, gain=factor)  # Cutoff at the output (high) rate.
            self.core = LiteDSPFIRInterpolator(n_taps, factor, data_width=data_width,
                coefficients=coeffs, with_csr=with_csr)
        self.latency = self.core.latency
        self.comb += [
            self.sink.connect(self.core.sink),
            self.core.source.connect(self.source),
        ]
