#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled

# Window Coefficients ------------------------------------------------------------------------------

def window_coefficients(n, window="hann", data_width=16):
    """Return ``n`` real window coefficients in signed Q1.(N-1) (0..1.0)."""
    scale = (1 << (data_width - 1)) - 1
    w     = []
    for k in range(n):
        if window == "rect":
            c = 1.0
        elif window == "hann":
            c = 0.5 - 0.5*math.cos(2*math.pi*k/(n - 1))
        elif window == "hamming":
            c = 0.54 - 0.46*math.cos(2*math.pi*k/(n - 1))
        elif window == "blackman":
            c = 0.42 - 0.5*math.cos(2*math.pi*k/(n - 1)) + 0.08*math.cos(4*math.pi*k/(n - 1))
        else:
            raise ValueError(f"Unknown window: {window}")
        w.append(int(round(c*scale)))
    return w

# Window -------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPWindow(LiteXModule):
    """Apply a length-``n`` window to a complex I/Q stream, framed every ``n`` samples.

    Each I/Q sample is multiplied by the real window coefficient for its position in the frame
    (round + saturate). ``source.first`` / ``source.last`` mark frame boundaries so a
    downstream FFT can align frames. The window is fixed at build time (``window``).
    """
    def __init__(self, n, data_width=16, window="hann", with_csr=True):
        self.n          = n
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Coefficient ROM (asynchronous read).
        # ------------------------------------
        coeffs = window_coefficients(n, window, data_width)
        rom    = Memory(data_width, n, init=coeffs)
        rp     = rom.get_port(async_read=True)
        self.specials += rom, rp

        adv  = Signal()
        xfer = Signal()
        cnt  = Signal(max=n)
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
            rp.adr.eq(cnt),
        ]
        self.sync += If(xfer,
            If(cnt == (n - 1), cnt.eq(0)).Else(cnt.eq(cnt + 1))
        )

        # Windowed sample = sample * coeff, rescaled.
        # -------------------------------------------
        coeff = Signal((data_width, True))
        self.comb += coeff.eq(rp.dat_r)
        res_i, _ = scaled(self.sink.i*coeff, data_width - 1, data_width)
        res_q, _ = scaled(self.sink.q*coeff, data_width - 1, data_width)
        self.sync += If(adv,
            self.source.i.eq(res_i),
            self.source.q.eq(res_q),
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.valid & (cnt == 0)),
            self.source.last.eq( self.sink.valid & (cnt == (n - 1))),
        )
