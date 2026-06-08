#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import real_layout

# Log2 ---------------------------------------------------------------------------------------------

@ResetInserter()
class Log2(LiteXModule):
    """Fixed-point base-2 logarithm of an unsigned input (priority-encoder + mantissa).

    ``log2(x) ~= msb_position + fraction`` where the fraction is the ``frac_bits`` bits just
    below the most-significant set bit (linear-in-mantissa approximation, error < ~0.086).
    Output is ``log2`` in unsigned Q(int).``frac_bits``. ``x == 0`` yields 0.
    """
    def __init__(self, in_width=32, frac_bits=8, with_csr=True):
        self.in_width  = in_width
        self.frac_bits = frac_bits
        out_int        = max(1, (in_width - 1).bit_length())
        self.out_width = out_int + frac_bits
        self.latency   = 1
        self.sink   = stream.Endpoint(real_layout(in_width))   # Treated as unsigned magnitude.
        self.source = stream.Endpoint([("data", self.out_width)])

        # # #

        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        x   = Signal(in_width)
        self.comb += x.eq(self.sink.data)
        msb = Signal(max=in_width)
        for i in range(in_width):
            self.comb += If(x[i], msb.eq(i))                   # Highest set bit (last wins).

        shifted = Signal(2*in_width)
        self.comb += shifted.eq(x << (in_width - 1 - msb))     # Align MSB to bit in_width-1.
        mant = shifted[in_width - 1 - frac_bits:in_width - 1]
        res  = Signal(self.out_width)
        self.comb += If(x != 0, res.eq(Cat(mant, msb)))        # msb*2**frac + mantissa.
        self.sync += If(adv,
            self.source.data.eq(res),
            self.source.valid.eq(self.sink.valid),
        )

# Log-Power (dB) -----------------------------------------------------------------------------------

class LogPower(LiteXModule):
    """Power-to-dB: ``10*log10(x) = 3.0103 * log2(x)`` (x is a power value, unsigned).

    Internally a :class:`Log2` followed by a constant scale. Output is dB in Q?.``out_frac``.
    """
    def __init__(self, in_width=32, out_frac=4, with_csr=True):
        self.sink   = stream.Endpoint(real_layout(in_width))
        DB_PER_BIT  = 3.010299957                              # 10*log10(2).
        # # #
        self.log2 = Log2(in_width=in_width, frac_bits=8, with_csr=False)
        scale     = int(round(DB_PER_BIT*(1 << out_frac)))     # dB per log2-unit, Q(out_frac+).
        self.out_width = self.log2.out_width + scale.bit_length()
        self.source = stream.Endpoint([("data", self.out_width)])
        self.latency = self.log2.latency + 1
        self.comb += self.sink.connect(self.log2.sink)
        adv = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.log2.source.ready.eq(adv),
        ]
        self.sync += If(adv,
            # log2 is Q?.8; scale is Q?.out_frac dB/unit -> dB in Q?.(8+out_frac), then >>8.
            self.source.data.eq((self.log2.source.data*scale) >> 8),
            self.source.valid.eq(self.log2.source.valid),
        )
