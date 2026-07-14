#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import check, iq_layout
from litedsp.filter.fir_poly import LiteDSPFIRInterpolator, LiteDSPFIRDecimator
from litedsp.filter.design   import firwin_lowpass

# Rational Resampler -------------------------------------------------------------------------------

class LiteDSPRationalResampler(LiteXModule):
    """Resample by ``L/M``: polyphase interpolate-by-L then decimate-by-M.

    The shared anti-alias/anti-image low-pass runs at the interpolated rate (cutoff set by the
    larger of L, M). Built from the polyphase FIRs. For arbitrary (non-rational) ratios use the
    Farrow interpolator with a phase accumulator instead.
    """
    def __init__(self, interpolation=3, decimation=2, data_width=16, n_taps=None, with_csr=True):
        L, M = interpolation, decimation  # Literature names.
        check(L >= 1 and M >= 1, "expected interpolation >= 1 and decimation >= 1")
        self.interpolation, self.decimation = L, M
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.latency = None  # Variable (rate-changing composite; phase-dependent).

        # # #

        # Polyphase Cores.
        # ----------------
        cutoff  = 0.4/max(L, M)          # 0.5/max(L, M) ideal; 0.4 leaves a transition band.
        ntaps_i = (n_taps or (8*L + 1))  # ~8 taps per polyphase branch by default.
        ntaps_d = (n_taps or (8*M + 1))
        self.interp = LiteDSPFIRInterpolator(n_taps=ntaps_i, interpolation=L, data_width=data_width,
            coefficients=firwin_lowpass(ntaps_i, cutoff, data_width=data_width, gain=L),
            with_csr=False)
        self.decim  = LiteDSPFIRDecimator(n_taps=ntaps_d, decimation=M, data_width=data_width,
            coefficients=firwin_lowpass(ntaps_d, cutoff, data_width=data_width),
            with_csr=False)

        # Datapath.
        # ---------
        self.comb += [
            self.sink.connect(self.interp.sink),
            self.interp.source.connect(self.decim.sink),
            self.decim.source.connect(self.source),
        ]
