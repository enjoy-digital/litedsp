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

    Parameters
    ----------
    n : int
        Window length in samples (frame size); sets the coefficient ROM depth and must match
        the downstream FFT size.
    """
    def __init__(self, n, data_width=16, window="hann", with_csr=True):
        self.n          = n
        self.data_width = data_width
        self.latency    = 2
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Coefficient ROM (asynchronous read).
        # ------------------------------------
        coeffs = window_coefficients(n, window, data_width)
        rom    = Memory(data_width, n, init=coeffs)
        rp     = rom.get_port(async_read=True)
        self.specials += rom, rp

        adv  = Signal()       # Pipeline advances (output slot free or being consumed).
        xfer = Signal()       # An input sample is consumed this beat.
        cnt  = Signal(max=n)  # Position within the frame (coefficient index).
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
        # Full-width product Signals: an inline product would be sized by its assignment
        # context in the emitted Verilog and truncate (found by Verilator co-simulation).
        prod_i = Signal((2*data_width, True))
        prod_q = Signal((2*data_width, True))
        self.comb += coeff.eq(rp.dat_r)
        res_i, _ = scaled(prod_i, data_width - 1, data_width)
        res_q, _ = scaled(prod_q, data_width - 1, data_width)
        valid_d = Signal()
        first_d = Signal()
        last_d  = Signal()
        self.sync += If(adv,
            # Register the full-width DSP products before rounding/saturation. This cuts the
            # product-to-carry-chain timing path without changing arithmetic or throughput.
            prod_i.eq(self.sink.i*coeff),
            prod_q.eq(self.sink.q*coeff),
            valid_d.eq(self.sink.valid),
            first_d.eq(self.sink.valid & (cnt == 0)),
            last_d.eq( self.sink.valid & (cnt == (n - 1))),
            self.source.i.eq(res_i),
            self.source.q.eq(res_q),
            self.source.valid.eq(valid_d),
            self.source.first.eq(first_d),
            self.source.last.eq(last_d),
        )
