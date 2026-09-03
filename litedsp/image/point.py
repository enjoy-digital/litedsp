#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Point operations: threshold with hysteresis, per-channel gain and offset."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, pixel_layout, pixel_fields, clamped, rounded, add_bypass, add_bypass_csr, bits_for

# Threshold ----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPThreshold(LiteXModule):
    """Binary threshold with hysteresis along the scan line (mono).

    The output is full scale when the pixel is at or above ``high``, zero when below ``low``, and
    keeps the previous decision in between (a Schmitt trigger along the line: the state resets
    at ``first`` and at every ``eol``); ``low = high`` gives a plain threshold. ``invert`` swaps
    the two levels. Runtime ``high`` / ``low``; ``bypass``. Latency 1.
    """
    def __init__(self, data_width=8, high=128, low=None, invert=False, with_csr=True):
        if low is None:
            low = high
        check(0 <= low <= high < 2**data_width, "expected 0 <= low <= high < 2**data_width")
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(pixel_layout(data_width, 1))
        self.source = stream.Endpoint(pixel_layout(data_width, 1))
        self.high   = Signal(data_width, reset=high)
        self.low    = Signal(data_width, reset=low)
        self.invert = Signal(reset=int(invert))

        # # #

        DW = data_width
        adv, xfer = Signal(), Signal()
        state, nstate = Signal(), Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
            nstate.eq(Mux(self.sink.data >= self.high, 1, Mux(self.sink.data < self.low, 0, state & ~self.sink.first))),
        ]
        self.sync += If(xfer, state.eq(Mux(self.sink.eol, 0, nstate)))
        self.sync += If(adv,
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first), self.source.eol.eq(self.sink.eol), self.source.last.eq(self.sink.last),
            self.source.data.eq(Mux(nstate ^ self.invert, (1 << DW) - 1, 0)),
        )
        add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        DW = self.data_width
        self._levels = CSRStorage(fields=[
            CSRField("high", size=DW, offset=0,  reset=self.high.reset.value, description="Set level."),
            CSRField("low",  size=DW, offset=16, reset=self.low.reset.value,  description="Reset level (<= high)."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("invert", size=1, offset=0, reset=self.invert.reset.value, description="Swap the output levels."),
        ])
        self.comb += [
            self.high.eq(self._levels.fields.high), self.low.eq(self._levels.fields.low),
            self.invert.eq(self._control.fields.invert),
        ]
        add_bypass_csr(self)

# Pixel Gain ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPixelGain(LiteXModule):
    """Per-channel gain and offset: ``y = clamped(rounded(x * gain, gain_frac) + offset)``.

    Gains are unsigned Q4.gain_frac (reset 1.0), offsets signed ``data_width + 1`` bits; the
    products are registered, the sticky ``sat`` flags a clamp. White balance, brightness and
    contrast in one block (see ``PixelGainDriver``). ``bypass``. Latency 2.
    """
    def __init__(self, data_width=8, n_channels=3, gain_frac=8, with_csr=True):
        check(1 <= gain_frac <= data_width + 2, "expected 1 <= gain_frac <= data_width + 2")
        self.data_width = data_width
        self.n_channels = n_channels
        self.gain_frac  = gain_frac
        self.latency    = 2
        self.sink   = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.source = stream.Endpoint(pixel_layout(data_width, n_channels))
        self.gain   = [Signal(gain_frac + 4, reset=1 << gain_frac, name=f"gain{c}") for c in range(n_channels)]
        self.offset = [Signal((data_width + 1, True), name=f"offset{c}") for c in range(n_channels)]
        self.sat    = Signal()
        self.clear_sat = Signal()

        # # #

        DW, GF = data_width, gain_frac
        fields = pixel_fields(n_channels)
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]
        v1, f1, e1, l1 = Signal(), Signal(), Signal(), Signal()
        prods = [Signal(DW + GF + 4, name=f"prod{c}") for c in range(n_channels)]
        x1 = [Signal(DW, name=f"x1_{c}") for c in range(n_channels)]
        self.sync += If(adv,
            v1.eq(self.sink.valid), f1.eq(self.sink.first), e1.eq(self.sink.eol), l1.eq(self.sink.last),
            *[prods[c].eq(getattr(self.sink, f)*self.gain[c]) for c, f in enumerate(fields)],
            *[x1[c].eq(getattr(self.sink, f)) for c, f in enumerate(fields)],
        )
        ys = [Signal((DW + 6, True), name=f"y{c}") for c in range(n_channels)]
        rs = [Signal((DW + 5, True), name=f"r{c}") for c in range(n_channels)]
        ovf = Signal()
        for c in range(n_channels):
            ps = Signal((DW + GF + 5, True))
            self.comb += [ps.eq(prods[c]), rs[c].eq(rounded(ps, GF)), ys[c].eq(rs[c] + self.offset[c])]
        self.comb += ovf.eq(reduce_or([(y < 0) | (y > (1 << DW) - 1) for y in ys]))
        self.sync += [
            If(adv,
                self.source.valid.eq(v1), self.source.first.eq(f1), self.source.eol.eq(e1), self.source.last.eq(l1),
                *[getattr(self.source, f).eq(clamped(ys[c], DW)) for c, f in enumerate(fields)],
            ),
            If(self.clear_sat, self.sat.eq(0)).Elif(adv & v1 & ovf, self.sat.eq(1)),
        ]
        add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        DW, GF = self.data_width, self.gain_frac
        for c in range(self.n_channels):
            setattr(self, f"_gain{c}", CSRStorage(fields=[
                CSRField("gain",   size=GF + 4,  offset=0,  reset=1 << GF, description=f"Channel {c} gain (unsigned Q4.{GF})."),
                CSRField("offset", size=DW + 1,  offset=16, description=f"Channel {c} offset (signed)."),
            ], name=f"gain{c}"))
            csr = getattr(self, f"_gain{c}")
            self.comb += [self.gain[c].eq(csr.fields.gain), self.offset[c].eq(csr.fields.offset)]
        self._control = CSRStorage(fields=[
            CSRField("clear_sat", size=1, offset=0, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[CSRField("sat", size=1, offset=0, description="Sticky: an output clamped.")])
        self.comb += [self.clear_sat.eq(self._control.fields.clear_sat), self._status.fields.sat.eq(self.sat)]
        add_bypass_csr(self)

def reduce_or(terms):
    out = 0
    for t in terms:
        out = out | t
    return out
