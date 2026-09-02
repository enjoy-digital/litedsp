#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

import math

from litedsp.common import check, real_layout

# Log2 ---------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLog2(LiteXModule):
    """Fixed-point base-2 logarithm of an unsigned input (priority-encoder + mantissa).

    ``log2(x) ~= msb_position + fraction`` where the fraction is the ``frac_bits`` bits just
    below the most-significant set bit (linear-in-mantissa approximation, error < ~0.086,
    i.e. 0.5 dB). With ``lut=True`` the mantissa addresses a ``2**frac_bits`` entry ROM of
    ``log2(1 + m)`` instead (error < 2**-frac_bits, 0.02 dB at 8 bits -- what the audio
    dynamics processor and meters need), at one more cycle of latency. Output is ``log2`` in
    unsigned Q(int).``frac_bits``. ``x == 0`` yields 0.

    Parameters
    ----------
    in_width : int
        Width in bits of the unsigned input. Sets the integer output bits (enough to encode
        the MSB index) and the size of the priority encoder / alignment shifter.
    lut : bool
        Refine the mantissa through a log2 ROM (latency 2) instead of the linear approximation.
    """
    def __init__(self, in_width=32, frac_bits=8, with_csr=True, lut=False):
        check(in_width >= 2 and frac_bits >= 1, "expected in_width >= 2, frac_bits >= 1")
        self.in_width  = in_width
        self.frac_bits = frac_bits
        self.lut       = lut
        out_int        = max(1, (in_width - 1).bit_length())   # Integer bits to hold the MSB index.
        self.out_width = out_int + frac_bits
        self.latency   = 2 if lut else 1
        self.sink   = stream.Endpoint(real_layout(in_width))   # Treated as unsigned magnitude.
        self.source = stream.Endpoint([("data", self.out_width)])

        # # #

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        # Priority Encoder.
        # -----------------
        x   = Signal(in_width)
        self.comb += x.eq(self.sink.data)
        msb = Signal(max=in_width)
        for i in range(in_width):
            self.comb += If(x[i], msb.eq(i))                   # Highest set bit (last wins).

        # Mantissa Extraction.
        # --------------------
        shifted = Signal(2*in_width)                           # Holds x << (up to in_width-1).
        self.comb += shifted.eq(x << (in_width - 1 - msb))     # Align MSB to bit in_width-1.
        mant = shifted[in_width - 1 - frac_bits:in_width - 1]

        if lut:
            # ROM refinement: log2(1 + m/2**F) in Q.F (registered read), msb/valid delayed.
            # ----------------------------------------------------------------------------
            rom = Memory(frac_bits, 1 << frac_bits,
                init=[int(round(math.log2(1 + m/(1 << frac_bits))*(1 << frac_bits)))
                      for m in range(1 << frac_bits)])
            rp  = rom.get_port(has_re=True)
            self.specials += rom, rp
            msb1, nz1, v1 = Signal.like(msb), Signal(), Signal()
            self.comb += [rp.re.eq(adv), rp.adr.eq(mant)]
            self.sync += If(adv,
                msb1.eq(msb), nz1.eq(x != 0), v1.eq(self.sink.valid),
                self.source.data.eq(Mux(nz1, Cat(rp.dat_r, msb1), 0)),
                self.source.valid.eq(v1),
            )
        else:
            res = Signal(self.out_width)
            self.comb += If(x != 0, res.eq(Cat(mant, msb)))    # msb*2**frac + mantissa.

            # Output.
            # -------
            self.sync += If(adv,
                self.source.data.eq(res),
                self.source.valid.eq(self.sink.valid),
            )

# Log-Power (dB) -----------------------------------------------------------------------------------

class LiteDSPLogPower(LiteXModule):
    """Power-to-dB: ``10*log10(x) = 3.0103 * log2(x)`` (x is a power value, unsigned).

    Internally a :class:`LiteDSPLog2` followed by a constant scale. Output is dB in Q?.``out_frac``.

    Parameters
    ----------
    in_width : int
        Width in bits of the unsigned power input (e.g. 2*data_width for an I**2 + Q**2 value);
        sizes the internal Log2 core and hence the dB dynamic range covered.
    out_frac : int
        Fractional bits of the dB output (resolution = 2**-out_frac dB). More bits widen the
        constant-scale multiplier and the output word accordingly.
    """
    def __init__(self, in_width=32, out_frac=4, with_csr=True):
        self.sink   = stream.Endpoint(real_layout(in_width))
        DB_PER_BIT  = 3.010299957                              # 10*log10(2).
        # # #

        # Log2 Core.
        # ----------
        self.log2 = LiteDSPLog2(in_width=in_width, frac_bits=8, with_csr=False)
        scale     = int(round(DB_PER_BIT*(1 << out_frac)))     # dB per log2-unit, Q(out_frac+).
        self.out_width = self.log2.out_width + scale.bit_length()
        self.source = stream.Endpoint([("data", self.out_width)])
        self.latency = self.log2.latency + 1                   # + scale output register.
        self.comb += self.sink.connect(self.log2.sink)

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.log2.source.ready.eq(adv),
        ]

        # Output.
        # -------
        self.sync += If(adv,
            # log2 is Q?.8; scale is Q?.out_frac dB/unit -> dB in Q?.(8+out_frac), then >>8.
            self.source.data.eq((self.log2.source.data*scale) >> 8),
            self.source.valid.eq(self.log2.source.valid),
        )

# Exp2 (antilog) -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPExp2(LiteXModule):
    """Fixed-point ``2**v`` of a signed log2-domain value (ROM mantissa + integer shift).

    The input ``v`` is signed Q(in_width-frac_bits).``frac_bits`` (the format of
    :class:`LiteDSPLog2` outputs and dB-domain gains); the output is unsigned ``2**v`` in
    Q(out_width-out_frac).``out_frac``, saturated at the top and rounded to zero at the bottom.
    A ``2**frac_bits`` entry ROM gives ``2**(f/2**frac_bits)`` for the fractional part, the
    integer part shifts it (left: saturating, right: rounding). The inverse of the log block
    for gain computers (compressor make-up/reduction, dB volume). Latency 2.

    Parameters
    ----------
    in_width, frac_bits : int
        Input format (signed, ``frac_bits`` fractional bits).
    out_frac, out_width : int
        Output format: ``2**0 = 2**out_frac``; values >= 2**out_width saturate.
    """
    def __init__(self, in_width=16, frac_bits=8, out_frac=20, out_width=25, with_csr=True):
        check(0 < frac_bits < in_width, "expected 0 < frac_bits < in_width")
        check(out_frac >= 1 and out_width > out_frac, "expected out_frac >= 1 and out_width > out_frac")
        self.in_width  = in_width
        self.frac_bits = frac_bits
        self.out_frac  = out_frac
        self.out_width = out_width
        self.latency   = 2
        self.sink   = stream.Endpoint([("data", (in_width, True))])
        self.source = stream.Endpoint([("data", out_width)])

        # # #

        F, OF, OW = frac_bits, out_frac, out_width
        LMAX = OW - OF                                         # Larger left shifts saturate.
        RMAX = OF + 2                                          # Larger right shifts give 0.

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        # Stage 1: ROM read of the fraction, integer part registered.
        # -----------------------------------------------------------
        rom = Memory(OF + 1, 1 << F,
            init=[int(round(2**(f/(1 << F))*(1 << OF))) for f in range(1 << F)])
        rp  = rom.get_port(has_re=True)
        self.specials += rom, rp
        ipart  = Signal((in_width - F, True))
        ipart1 = Signal((in_width - F, True))
        v1     = Signal()
        self.comb += [ipart.eq(self.sink.data[F:]), rp.re.eq(adv), rp.adr.eq(self.sink.data[:F])]
        self.sync += If(adv, ipart1.eq(ipart), v1.eq(self.sink.valid))

        # Stage 2: shift left (saturate) or right (round).
        # ------------------------------------------------
        neg    = Signal()
        l_amt  = Signal(max=LMAX + 1)
        r_amt  = Signal(max=RMAX + 1)
        big    = Signal(OF + 1 + LMAX)
        half   = Signal(RMAX + 1)
        small  = Signal(OF + 2)
        self.comb += [
            neg.eq(ipart1[-1]),
            l_amt.eq(Mux(ipart1 > LMAX, LMAX, ipart1)),
            r_amt.eq(Mux(-ipart1 > RMAX, RMAX, -ipart1)),
            big.eq(rp.dat_r << l_amt),
            half.eq((1 << r_amt) >> 1),                       # Round-half-up bias (0 for r_amt 0).
            small.eq((rp.dat_r + half) >> r_amt),
        ]
        self.sync += If(adv,
            If(neg,
                self.source.data.eq(small),
            ).Elif((ipart1 > LMAX) | (big >= (1 << OW)),
                self.source.data.eq((1 << OW) - 1),
            ).Else(
                self.source.data.eq(big),
            ),
            self.source.valid.eq(v1),
        )
