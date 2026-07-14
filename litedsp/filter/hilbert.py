#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common        import check, real_layout, iq_layout
from litedsp.filter.fir    import LiteDSPFIRFilter
from litedsp.filter.design import hilbert_coefficients

# Hilbert Transformer ------------------------------------------------------------------------------

class LiteDSPHilbert(LiteXModule):
    """Real -> analytic (complex) signal via a Hilbert FIR.

    Two equal-length FIRs run on the real input: the I path is a pure delay (group delay
    ``(n_taps-1)/2``) and the Q path is a Type-III Hilbert filter (90 deg phase shift). The
    matched structure keeps I and Q aligned. Output is the analytic signal (negative-frequency
    image suppressed). ``n_taps`` must be odd.
    """
    def __init__(self, n_taps=23, data_width=16, with_csr=True):
        check(n_taps % 2 == 1, "expected n_taps % 2 == 1")
        self.n_taps = n_taps
        self.latency = None
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # FIR Paths.
        # ----------
        self.fir_i = LiteDSPFIRFilter(n_taps, data_width=data_width)   # Delay path (matches group delay).
        self.fir_q = LiteDSPFIRFilter(n_taps, data_width=data_width)   # Hilbert (90 deg) path.
        self.latency = self.fir_i.latency

        # Coefficients.
        # -------------
        center = (n_taps - 1)//2
        self.fir_i.coeffs[center].reset = (1 << (data_width - 1)) - 1   # Unit delay tap.
        for t, c in enumerate(hilbert_coefficients(n_taps, data_width=data_width)):
            self.fir_q.coeffs[t].reset = c

        # Datapath.
        # ---------
        # Broadcast the input to both FIRs; join valid/ready so I and Q stay lock-step.
        self.comb += [
            self.fir_i.sink.valid.eq(self.sink.valid),
            self.fir_q.sink.valid.eq(self.sink.valid),
            self.fir_i.sink.data.eq(self.sink.data),
            self.fir_q.sink.data.eq(self.sink.data),
            self.sink.ready.eq(self.fir_i.sink.ready & self.fir_q.sink.ready),
            self.source.valid.eq(self.fir_i.source.valid & self.fir_q.source.valid),
            self.source.i.eq(self.fir_i.source.data),
            self.source.q.eq(self.fir_q.source.data),
            self.fir_i.source.ready.eq(self.source.ready),
            self.fir_q.source.ready.eq(self.source.ready),
        ]
