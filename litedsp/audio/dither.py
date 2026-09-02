#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import (check, tdm_layout, tdm_channel, tdm_channel_bits, rounded, saturated,
    add_bypass, add_bypass_csr)

# Dither / Requantizer -----------------------------------------------------------------------------

SHAPING = ("none", "ef1", "ef2")

@ResetInserter()
class LiteDSPDither(LiteXModule):
    """Word-length reduction with TPDF dither and optional error-feedback noise shaping.

    Requantizes ``data_width`` samples to ``out_width`` bits (the result stays MSB-aligned in
    the ``data_width`` output word, low bits zero): triangular-PDF dither of +/-1 output LSB
    from two independent xorshift32 generators decorrelates the quantization error from the
    signal (no harmonic distortion at low levels), and error feedback of the previous
    requantization error(s) -- measured against the undithered input so the dither noise is
    shaped as well -- moves the noise away from the low frequencies (``"ef1"``: ``v = x +
    e[n-1]``, noise transfer 1 - z^-1; ``"ef2"``: ``v = x + 2e[n-1] - e[n-2]``, (1 - z^-1)^2),
    per channel of the TDM stream. ``dither_enable``/``shaping_enable`` are
    runtime switches; saturation is sticky. Latency 1, no multiplier.

    Parameters
    ----------
    out_width : int
        Output word length in bits (< data_width; e.g. 24 -> 16).
    n_channels : int
        Channels in the TDM frame (per-channel error state).
    shaping : str
        Error-feedback structure built: ``"none"``, ``"ef1"`` or ``"ef2"``.
    seed : int
        Seed of the dither generators (must be non-zero).
    """
    def __init__(self, data_width=24, out_width=16, n_channels=2, shaping="none",
        seed=0x2545F491, with_csr=True):
        check(data_width >= 8, "expected data_width >= 8")
        check(1 <= out_width < data_width, "expected 1 <= out_width < data_width")
        check(n_channels >= 1, "expected n_channels >= 1")
        check(shaping in SHAPING, f"expected shaping in {SHAPING}")
        check(seed != 0, "expected a non-zero seed")
        self.data_width = data_width
        self.out_width  = out_width
        self.n_channels = n_channels
        self.shaping    = shaping
        self.shift      = data_width - out_width
        self.latency    = 1
        shift = self.shift
        self.sink   = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.source = stream.Endpoint(tdm_layout(data_width, n_channels))
        self.dither_enable  = Signal(reset=1)
        self.shaping_enable = Signal(reset=int(shaping != "none"))
        self.clear_sat      = Signal()
        self.sat            = Signal()

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
        ch = tdm_channel(self.sink)

        # TPDF dither: two xorshift32 generators, low `shift` bits each -> +/-1 LSB triangular.
        # ----------------------------------------------------------------------------------
        seeds = [seed & 0xFFFFFFFF, (seed*0x9E3779B1 + 0x7F4A7C15) & 0xFFFFFFFF or 1]
        rnds  = []
        for s0 in seeds:
            r  = Signal(32, reset=s0)
            t1 = Signal(32)
            t2 = Signal(32)
            nx = Signal(32)
            self.comb += [
                t1.eq(r ^ (r << 13)),
                t2.eq(t1 ^ (t1 >> 17)),
                nx.eq(t2 ^ (t2 << 5)),
            ]
            self.sync += If(xfer, r.eq(nx))
            rnds.append(r)
        tpdf = Signal((shift + 2, True))
        self.comb += tpdf.eq(Mux(self.dither_enable,
            rnds[0][:shift] + rnds[1][:shift] - (1 << shift), 0))

        # Error feedback (per-channel state) and requantization.
        # -----------------------------------------------------
        W  = data_width + 3
        e1 = [Signal((shift + 2, True), name=f"e1_{c}") for c in range(n_channels)]
        e2 = [Signal((shift + 2, True), name=f"e2_{c}") for c in range(n_channels)]
        fb = Signal((shift + 4, True))
        if shaping == "ef1":
            self.comb += fb.eq(Array(e1)[ch])
        elif shaping == "ef2":
            self.comb += fb.eq(2*Array(e1)[ch] - Array(e2)[ch])
        u    = Signal((W, True))                              # Input + feedback (undithered).
        v    = Signal((W, True))
        q_r  = Signal((W - shift, True))
        q    = Signal((out_width, True))
        err  = Signal((shift + 2, True))
        self.comb += [
            u.eq(self.sink.data + Mux(self.shaping_enable, fb, 0)),
            v.eq(u + tpdf),
            q_r.eq(rounded(v, shift)),
            q.eq(saturated(q_r, out_width)),
            err.eq(u - (q_r << shift)),                       # Error incl. dither, |err| < 1.5 LSB.
        ]
        ovf = Signal()
        self.comb += ovf.eq(q_r != q)
        for c in range(n_channels):
            self.sync += If(xfer & (ch == c), e1[c].eq(err), e2[c].eq(e1[c]))

        # Output.
        # -------
        self.sync += If(adv,
            self.source.data.eq(Cat(Constant(0, shift), q)),
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
        )
        if n_channels > 1:
            self.sync += If(adv, self.source.channel.eq(ch))
        self.sync += If(self.clear_sat, self.sat.eq(0)).Elif(xfer & ovf, self.sat.eq(1))
        add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("dither_enable",  size=1, offset=0, reset=1, description="Add TPDF dither."),
            CSRField("shaping_enable", size=1, offset=1, reset=int(self.shaping != "none"),
                description="Enable the error-feedback noise shaping."),
            CSRField("clear_sat",      size=1, offset=2, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturation", size=1, description="Output saturated since the last clear."),
        ])
        self.comb += [
            self.dither_enable.eq(self._control.fields.dither_enable),
            self.shaping_enable.eq(self._control.fields.shaping_enable),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.saturation.eq(self.sat),
        ]
        add_bypass_csr(self)
