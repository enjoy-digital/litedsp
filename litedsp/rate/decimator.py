#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common         import check, iq_layout
from litedsp.filter.cic     import LiteDSPCICDecimator
from litedsp.filter.fir_poly import LiteDSPFIRDecimator
from litedsp.filter.design  import firwin_lowpass

# Decimator ----------------------------------------------------------------------------------------

class LiteDSPDecimator(LiteXModule):
    """Integer decimator: anti-alias filter + rate drop.

    ``method="cic"`` (default) uses a portable CIC (efficient for large factors); ``method="fir"``
    uses a polyphase decimating FIR with a windowed-sinc low-pass (cleaner passband).

    Parameters
    ----------
    cutoff : float
        Anti-alias low-pass cutoff, normalized to the output (decimated) sample rate (0..0.5);
        used by ``method="fir"`` only (the CIC response is fixed by its structure).
    """
    def __init__(self, data_width=16, decimation=8, method="cic", n_taps=None, cutoff=0.4,
        n_stages=4, with_csr=True):
        check(method in ["cic", "fir"], "expected method in ['cic', 'fir']")
        self.decimation = decimation
        self.method     = method
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        if method == "cic":
            self.core = LiteDSPCICDecimator(data_width=data_width, decimation=decimation,
                n_stages=n_stages, with_csr=with_csr)
        else:
            n_taps = n_taps or (8*decimation + 1)  # ~8 taps per polyphase branch.
            coeffs = firwin_lowpass(n_taps, cutoff/decimation, data_width=data_width)  # Cutoff at the input (high) rate.
            self.core = LiteDSPFIRDecimator(n_taps=n_taps, decimation=decimation, data_width=data_width,
                coefficients=coeffs, with_csr=with_csr)
        self.latency = self.core.latency
        self.comb += [
            self.sink.connect(self.core.sink),
            self.core.source.connect(self.source),
        ]
