#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

# Proportional-Integral Loop Filter ----------------------------------------------------------------

class PILoop(LiteXModule):
    """Proportional-integral loop filter with shift-based gains (for PLL/Costas/timing/AGC).

    ``out = (error >> kp_shift) + integral`` where ``integral += (error >> ki_shift)`` each
    enabled cycle. Drive ``error``/``ce``; read ``out`` (and ``integral`` for the frequency
    state). Larger shifts = slower/tighter loop.
    """
    def __init__(self, error_width=18, out_width=32, kp_shift=4, ki_shift=12):
        self.error    = Signal((error_width, True))
        self.ce       = Signal()
        self.out      = Signal((out_width, True))
        self.integral = Signal((out_width, True))

        # # #

        self.sync += If(self.ce, self.integral.eq(self.integral + (self.error >> ki_shift)))
        self.comb += self.out.eq(self.integral + (self.error >> kp_shift))
