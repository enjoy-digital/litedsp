#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Extra filters: tunable notch, comb, and 1st-order allpass (per I/Q)."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled, saturated

# Tunable Notch ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPNotch(LiteXModule):
    """Tunable 2nd-order notch (zeros on the unit circle, poles at radius ``r``).

    Notch frequency set at runtime by ``cos_w0`` (= cos(2*pi*f0), signed Q.``frac``). ``r`` (build
    time, <1) sets the notch width. Direct-form-I biquad with round + saturate (per I/Q).
    """
    def __init__(self, data_width=16, frac=14, r=0.96, with_csr=True):
        self.frac = frac
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.cos_w0 = Signal((data_width, True))          # cos(2*pi*f0) in Q.frac.

        # # #

        # Coefficients.
        # -------------
        rq   = int(round(r*(1 << frac)))                  # r   (pole radius) in Q.frac.
        r2q  = int(round(r*r*(1 << frac)))                # r^2 in Q.frac.
        gq   = int(round(((1 + r*r)/2)*(1 << frac)))      # Passband normalization.

        # Handshake.
        # ----------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        two_cos = Signal((data_width + 2, True))
        b1      = Signal((data_width + 2, True))          # -g*2cos.
        a1      = Signal((data_width + 2, True))          # +2r*cos (= r*2cos).
        self.comb += [
            two_cos.eq(2*self.cos_w0),
            b1.eq(-((gq*two_cos) >> frac)),
            a1.eq((rq*two_cos) >> frac),
        ]
        for f in ["i", "q"]:
            x  = getattr(self.sink, f)
            x1, x2 = Signal((data_width, True)), Signal((data_width, True))   # x[n-1], x[n-2].
            y1, y2 = Signal((data_width, True)), Signal((data_width, True))   # y[n-1], y[n-2].
            # DF1 biquad: zeros on the unit circle at +/-w0, poles at radius r behind them.
            yf = gq*x + b1*x1 + gq*x2 + a1*y1 - r2q*y2
            y  = scaled(yf, frac, data_width)[0]
            self.sync += If(xfer, x2.eq(x1), x1.eq(x), y2.eq(y1), y1.eq(y))
            self.sync += If(adv, getattr(self.source, f).eq(y))

        # Output.
        # -------
        valid = Signal()
        self.sync += If(adv, valid.eq(self.sink.valid))
        self.comb += self.source.valid.eq(valid)

        # CSR.
        # ----
        if with_csr:
            self._cos = CSRStorage(data_width, name="cos_w0", description="cos(2*pi*f0), Q.frac.")
            self.comb += self.cos_w0.eq(self._cos.storage)

# Comb Filter --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCombFilter(LiteXModule):
    """Feed-forward comb ``y[n] = x[n] - x[n-D]`` (nulls at multiples of fs/D), per I/Q."""
    def __init__(self, depth=8, data_width=16, with_csr=True):
        self.depth  = depth
        self.latency = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Handshake.
        # ----------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        for f in ["i", "q"]:
            x   = getattr(self.sink, f)
            mem = Memory(data_width, depth)
            wp  = mem.get_port(write_capable=True)
            rp  = mem.get_port(async_read=True)
            self.specials += mem, wp, rp
            ptr = Signal(max=depth)              # Write/read pointer (wraps at depth = D).
            old = Signal((data_width, True))     # x[n-D].
            # Circular delay line: the async read at ptr returns x[n-D] just before the
            # same-address write replaces it.
            self.comb += [rp.adr.eq(ptr), wp.adr.eq(ptr), old.eq(rp.dat_r), wp.dat_w.eq(x), wp.we.eq(xfer)]
            self.sync += If(xfer, If(ptr == (depth - 1), ptr.eq(0)).Else(ptr.eq(ptr + 1)))
            self.sync += If(adv, getattr(self.source, f).eq(saturated(x - old, data_width)))

        # Output.
        # -------
        valid = Signal()
        self.sync += If(adv, valid.eq(self.sink.valid))
        self.comb += self.source.valid.eq(valid)

# Allpass ------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPAllpass(LiteXModule):
    """1st-order allpass ``y[n] = -a*x[n] + x[n-1] + a*y[n-1]`` (flat magnitude), per I/Q."""
    def __init__(self, data_width=16, frac=14, with_csr=True):
        self.frac = frac
        self.latency = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.a      = Signal((data_width, True), reset=int(round(0.5*(1 << frac))))   # Q.frac.

        # # #

        # Handshake.
        # ----------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Datapath.
        # ---------
        for f in ["i", "q"]:
            x  = getattr(self.sink, f)
            x1 = Signal((data_width, True))      # x[n-1].
            y1 = Signal((data_width, True))      # y[n-1].
            # (x1 << frac) aligns the unscaled delay tap with the Q.frac products.
            y  = scaled(-self.a*x + (x1 << frac) + self.a*y1, frac, data_width)[0]
            self.sync += If(xfer, x1.eq(x), y1.eq(y))
            self.sync += If(adv, getattr(self.source, f).eq(y))

        # Output.
        # -------
        valid = Signal()
        self.sync += If(adv, valid.eq(self.sink.valid))
        self.comb += self.source.valid.eq(valid)

        # CSR.
        # ----
        if with_csr:
            self._a = CSRStorage(data_width, reset=self.a.reset.value, name="a",
                description="Allpass coefficient (Q.frac).")
            self.comb += self.a.eq(self._a.storage)
