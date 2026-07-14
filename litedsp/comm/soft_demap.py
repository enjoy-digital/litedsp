#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, check, rounded

# Soft Demapper Constants ----------------------------------------------------------------------------

SOFT_DEMAP_SCALE_WIDTH = 16                            # llr_scale width (unsigned Q1.15).
SOFT_DEMAP_SCALE_FRAC  = 15                            # llr_scale fractional bits.
SOFT_DEMAP_SCALE_ONE   = 1 << SOFT_DEMAP_SCALE_FRAC    # 1.0 (identity, reset value).

# Soft Demapper --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSoftDemapper(LiteXModule):
    """Gray-coded square-QAM max-log soft demapper: per-axis folded piecewise-linear LLRs.

    Companion to :class:`~litedsp.comm.slicer.LiteDSPSlicer`, on the same constellation:
    ``L = 2**bits_per_axis`` PAM levels per axis at ``(2k-(L-1))*spacing`` (decision boundaries
    at even multiples of ``spacing``). Each axis carries ``bits_per_axis`` bits as the Gray
    label ``g = k ^ (k >> 1)`` of the level index ``k``; bit ``j``'s max-log LLR is the standard
    folded absolute-value function of the axis value ``x`` (adds/compares only, no divider):

        raw[B-1] = -x                                       (axis MSB)
        raw[j]   = |d[j+1]| - 2**(j+1)*spacing              (d[j] = -raw[j], d[B-1] = x)

    Sign convention: **positive LLR = bit 0 more likely**; the hard decision is the LLR sign bit
    (LLR < 0 -> bit 1), agreeing with bit ``j`` of ``gray(k)`` from the hard slicer wherever the
    LLR is nonzero (LLR = 0 exactly on that bit's decision boundary). Raw LLRs are in axis-LSB
    units; ``llr_scale`` (unsigned Q1.15, reset 1.0) rescales them (round half up) before
    symmetric saturation to +/-(2**(llr_bits-1)-1) — program it with the host's 1/noise-variance
    normalization, e.g. ~``2**15 * (2**(llr_bits-1)-1) / max|raw|`` to span the full LLR range.

    Output: one beat per input sample; ``source.llrs`` packs ``2*bits_per_axis`` signed
    ``llr_bits`` LLRs LSB-first — I-axis bits first, Gray LSB (bit 0) first, so slot ``n`` sits
    at bits ``[n*llr_bits +: llr_bits]`` and slot order matches the slicer's ``[q_bits | i_bits]``
    Gray-coded symbol. QPSK = ``bits_per_axis=1``, 16-QAM = ``2``, 64-QAM = ``3``.

    Parameters
    ----------
    bits_per_axis : int
        Bits per I/Q axis: L = 2**bits_per_axis PAM levels per axis (1 = QPSK, 2 = 16-QAM,
        3 = 64-QAM); the output beat carries 2*bits_per_axis LLRs.
    spacing : int
        Half the distance between adjacent PAM levels, in input LSBs; levels sit at
        (2k-(L-1))*spacing (same convention as the slicer). (L-1)*spacing must fit data_width.
    llr_bits : int
        Width of each output LLR (signed, saturated symmetrically to +/-(2**(llr_bits-1)-1)).
    """
    def __init__(self, bits_per_axis=1, spacing=8000, llr_bits=4, data_width=16, with_csr=True):
        check(bits_per_axis >= 1, "expected bits_per_axis >= 1")
        check(spacing       >= 1, "expected spacing >= 1")
        check(llr_bits      >= 2, "expected llr_bits >= 2")
        L = 1 << bits_per_axis
        check((L - 1)*spacing < (1 << (data_width - 1)),
            "expected (2**bits_per_axis - 1)*spacing < 2**(data_width - 1)")
        self.bits_per_axis = bits_per_axis
        self.llr_bits      = llr_bits
        self.latency       = 2
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint([("llrs", 2*bits_per_axis*llr_bits)])
        self.llr_scale = Signal(SOFT_DEMAP_SCALE_WIDTH, reset=SOFT_DEMAP_SCALE_ONE)  # Q1.15.

        # # #

        B = bits_per_axis
        W = data_width + 1  # Folding guard bit (|x| and fold constants stay in range).

        # Handshake.
        # ----------
        adv = Signal()  # Advance when the output slot is free or being consumed.
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]
        valid_sr = Signal(self.latency)
        self.sync += If(adv, valid_sr.eq(Cat(self.sink.valid, valid_sr[:-1])))
        self.comb += self.source.valid.eq(valid_sr[-1])

        # Stage 1: per-axis Gray-bit folding (raw LLRs in axis-LSB units), registered.
        # -----------------------------------------------------------------------------
        def fold(x, axis):
            raws = [Signal((W, True), name=f"raw_{axis}{j}") for j in range(B)]
            d    = Signal((W, True), name=f"d_{axis}{B - 1}")
            self.comb += [d.eq(x), raws[B - 1].eq(-d)]
            for j in range(B - 2, -1, -1):
                d_abs  = Signal((W, True), name=f"d_abs_{axis}{j + 1}")
                d_next = Signal((W, True), name=f"d_{axis}{j}")
                self.comb += [
                    d_abs.eq( Mux(d < 0, -d, d)),                # |d[j+1]|.
                    raws[j].eq(d_abs - (1 << (j + 1))*spacing),  # |d[j+1]| - 2**(j+1)*spacing.
                    d_next.eq(-raws[j]),
                ]
                d = d_next
            return raws  # LSB-first: raws[j] = Gray bit j.

        raws   = fold(self.sink.i, "i") + fold(self.sink.q, "q")
        raws_r = [Signal((W, True), name=f"raw{n}_r") for n in range(2*B)]
        self.sync += If(adv, *[r.eq(raw) for r, raw in zip(raws_r, raws)])

        # Stage 2: scale (Q1.15, round half up) + symmetric saturation, registered output.
        # ---------------------------------------------------------------------------------
        # Signed view of the unsigned scale: Verilog sizes/signs '*' from its operands, so a
        # mixed signed*unsigned product would go unsigned in the emitted RTL.
        scale_s = Signal((SOFT_DEMAP_SCALE_WIDTH + 1, True))
        self.comb += scale_s.eq(self.llr_scale)
        hi = (1 << (llr_bits - 1)) - 1
        for n, raw_r in enumerate(raws_r):
            prod = Signal((W + SOFT_DEMAP_SCALE_WIDTH + 1, True), name=f"prod{n}")
            v    = Signal((W + 2, True), name=f"llr{n}")  # Post-shift, pre-saturation.
            sat  = Signal((llr_bits, True), name=f"sat{n}")
            self.comb += [
                prod.eq(raw_r * scale_s),
                v.eq(rounded(prod, SOFT_DEMAP_SCALE_FRAC)),
                sat.eq(Mux(v > hi, hi, Mux(v < -hi, -hi, v))),
            ]
            self.sync += If(adv, self.source.llrs[n*llr_bits:(n + 1)*llr_bits].eq(sat))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("llr_scale", size=SOFT_DEMAP_SCALE_WIDTH, offset=0,
                reset=SOFT_DEMAP_SCALE_ONE, description=
                "LLR scale, unsigned Q1.15 (1.0 = 0x8000, identity): raw LLRs (axis-LSB units) "
                "are multiplied by llr_scale/2**15 (round half up) before symmetric saturation "
                "to +/-(2**(llr_bits-1)-1). Program the 1/noise-variance normalization here."),
        ])
        self.comb += self.llr_scale.eq(self._control.fields.llr_scale)
