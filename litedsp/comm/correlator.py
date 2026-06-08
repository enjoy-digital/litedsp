#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common     import iq_layout
from litedsp.filter.fir import FIRFilterComplex

# Correlator / Matched Filter ----------------------------------------------------------------------

class Correlator(LiteXModule):
    """Sliding correlation of the I/Q stream against a known real ``sequence``.

    Implemented as a complex FIR whose taps are the time-reversed reference (matched filter):
    the output peaks when the input aligns with the sequence. For a +/-1 PN/Barker code pass
    the code as ``sequence`` (taps become +/- full-scale). Follow with ``Magnitude`` + a
    threshold for preamble detection.
    """
    def __init__(self, sequence, data_width=16, with_csr=True):
        n_taps = len(sequence)
        self.sequence = sequence
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        scale  = (1 << (data_width - 1)) - 1
        # Matched filter: taps = time-reversed reference, scaled to Q1.(N-1).
        coeffs = [int(round(c*scale)) for c in reversed(sequence)]
        self.fir = FIRFilterComplex(n_taps=n_taps, data_width=data_width,
            coefficients=coeffs, with_csr=False)
        self.latency = self.fir.latency
        self.comb += [
            self.sink.connect(self.fir.sink),
            self.fir.source.connect(self.source),
        ]
