#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common          import iq_layout, real_layout
from litedsp.analysis.window import LiteDSPWindow
from litedsp.analysis.fft    import LiteDSPFFT
from litedsp.analysis.psd    import LiteDSPPSD

# Welch PSD ----------------------------------------------------------------------------------------

class LiteDSPWelchPSD(LiteXModule):
    """Windowed, averaged power spectral density: Window -> FFT -> PSD.

    Applies a window before the FFT (reducing spectral leakage vs a bare PSD) and averages
    ``2**avg_log2`` frames. Output is the averaged spectrum in natural bin order. (Segment
    *overlap* is not yet implemented — a future refinement.)

    Parameters
    ----------
    avg_log2 : int
        Windowed FFT frames averaged per emitted spectrum, as a power of two (``2**avg_log2``);
        more averaging lowers the variance of the estimate but lengthens the update interval.
    """
    def __init__(self, N=256, data_width=16, avg_log2=2, window="hann", with_csr=True):
        self.N = N
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.latency = None  # Variable (frame-accumulating composite).

        # # #

        self.window = LiteDSPWindow(N, data_width=data_width, window=window, with_csr=False)
        self.fft    = LiteDSPFFT(N, data_width=data_width, with_csr=False)
        self.psd    = LiteDSPPSD(N, fft_latency=self.fft.latency, data_width=data_width,
            avg_log2=avg_log2, with_csr=with_csr)
        self.source = self.psd.source
        self.comb += [
            self.sink.connect(self.window.sink),
            self.window.source.connect(self.fft.sink),
            self.fft.source.connect(self.psd.sink),
        ]
