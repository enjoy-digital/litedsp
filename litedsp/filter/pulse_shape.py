#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout
from litedsp.filter.fir_poly import LiteDSPFIRInterpolator
from litedsp.filter.design   import rrc_coefficients

# Pulse Shaper -------------------------------------------------------------------------------------

class LiteDSPPulseShaper(LiteXModule):
    """Root-raised-cosine pulse-shaping interpolator (``sps`` samples/symbol).

    An interpolating polyphase FIR loaded with RRC taps: maps a 1-sample-per-symbol I/Q stream
    to ``sps`` samples/symbol with matched-filter pulse shaping. Use the same RRC at RX.

    Matched-pair performance
    ------------------------
    Validated as a TX -> RX pair (this shaper followed by a complex FIR loaded with the same
    unit-energy ``rrc_coefficients`` taps, ``test/test_matched_pair.py``): the composite
    raised cosine at the default config (sps=4, span=8, beta=0.35, Q1.15) measures -39.8 dB
    worst symbol-spaced ISI sidelobe and -36.5 dB EVM on random QPSK at the optimal sampling
    instant; sps=2, span=10, beta=0.25 measures -41.9 dB ISI and -38.4 dB EVM. The floor is
    set by RRC truncation (finite span), not tap quantization (< 0.1 dB): increase ``span``
    for a lower ISI floor (more taps/latency); smaller ``beta`` narrows the spectrum but
    slows sidelobe decay, needing a longer span for the same floor.

    Parameters
    ----------
    sps : int
        Samples per symbol (interpolation factor); the output rate is sps x the input rate.
        Also the number of polyphase branches of the underlying FIR interpolator.
    span : int
        Filter span in symbols (n_taps = sps*span + 1). Longer span = closer to the ideal RRC
        (better stopband/ISI) at the cost of more taps and latency.
    beta : float
        RRC roll-off factor, 0 < beta <= 1. Excess bandwidth fraction; the occupied bandwidth
        is (1 + beta) x symbol_rate / 2 per side. Smaller = sharper but longer pulses.
    """
    def __init__(self, sps=4, span=8, beta=0.35, data_width=16, with_csr=True):
        self.sps  = sps
        self.span = span
        self.beta = beta
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        n_taps    = sps*span + 1                 # Odd, symmetric: span symbols at sps samples each.
        # RRC taps; the overall gain of sps compensates the 1/L amplitude loss of interpolation.
        # sps x the unit-energy RRC peak (~0.55*sps) does not fit Q1.15, so split the gain: the
        # power-of-two part 2**s goes into the output shift, the residual sps/2**s (<= 1) into
        # the taps — no tap clamps (clamping would degrade the composite-RC ISI floor from the
        # ~-40 dB truncation limit to ~-20 dB).
        s         = max(0, math.ceil(math.log2(sps)))
        coeffs    = rrc_coefficients(sps, span, beta, data_width=data_width, gain=sps/2**s)
        self.core = LiteDSPFIRInterpolator(n_taps=n_taps, interpolation=sps, data_width=data_width,
            coefficients=coeffs, shift=data_width - 1 - s, with_csr=with_csr)
        self.latency = self.core.latency
        self.comb += [self.sink.connect(self.core.sink), self.core.source.connect(self.source)]
