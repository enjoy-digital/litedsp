#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Line codes on bit streams: NRZI (space / mark), Manchester and differential Manchester."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check

CODES = ("nrzi_s", "nrzi_m", "manchester", "diff_manchester")

# Line Encoder -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLineEncoder(LiteXModule):
    """Bit stream to line code (``[("data", 1)]`` in and out).

    ``nrzi_s``: the level toggles on a 0 (HDLC / AIS), ``nrzi_m``: toggles on a 1 (rate 1:1,
    latency 1). ``manchester``: two chips per bit, ``b`` then ``~b`` (a 1 is high-then-low);
    ``diff_manchester``: a transition mid-bit always, a transition at the bit start for a 0
    (rate 2:1, the sink accepts one bit per two chips). ``invert`` flips the output;
    ``phase_rst`` restarts the chip phase / level.
    """
    def __init__(self, code="nrzi_s", invert=False, with_csr=True):
        check(code in CODES, f"expected code in {CODES}")
        self.code    = code
        self.latency = 1
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])
        self.invert    = Signal(reset=int(invert))
        self.phase_rst = Signal()

        # # #

        adv, xfer = Signal(), Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        level = Signal()
        out   = Signal()
        if code in ("nrzi_s", "nrzi_m"):
            self.comb += [self.sink.ready.eq(adv), xfer.eq(self.sink.valid & adv)]
            toggle = Signal()
            self.comb += toggle.eq(~self.sink.data if code == "nrzi_s" else self.sink.data)
            nxt = Signal()
            self.comb += nxt.eq(Mux(self.phase_rst, 0, level ^ toggle))
            self.sync += If(xfer, level.eq(nxt))
            self.sync += If(adv,
                self.source.valid.eq(self.sink.valid), self.source.first.eq(self.sink.first), self.source.last.eq(self.sink.last),
                self.source.data.eq(nxt ^ self.invert),
            )
        else:
            phase = Signal()                                            # 0: first chip, 1: second.
            bit   = Signal()
            self.comb += [self.sink.ready.eq(adv & ~phase), xfer.eq(self.sink.valid & self.sink.ready)]
            first_chip, second_chip = Signal(), Signal()
            if code == "manchester":
                self.comb += [first_chip.eq(self.sink.data), second_chip.eq(~bit)]
            else:
                # Differential: start level = ~level for a 0 (transition), = level for a 1; the
                # second chip is the complement of the first.
                start = Signal()
                self.comb += [start.eq(Mux(self.sink.data, level, ~level)), first_chip.eq(start), second_chip.eq(~bit)]
            self.sync += [
                If(self.phase_rst, phase.eq(0), level.eq(0)),
                If(adv,
                    If(~phase,
                        self.source.valid.eq(self.sink.valid), self.source.first.eq(self.sink.first), self.source.last.eq(0),
                        self.source.data.eq(first_chip ^ self.invert),
                        If(xfer, phase.eq(1), bit.eq(first_chip), level.eq(~first_chip)),
                    ).Else(
                        self.source.valid.eq(1), self.source.first.eq(0), self.source.last.eq(self.sink.last),
                        self.source.data.eq(second_chip ^ self.invert),
                        phase.eq(0),
                    ),
                ),
            ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("invert",    size=1, offset=0, reset=self.invert.reset.value, description="Invert the line."),
            CSRField("phase_rst", size=1, offset=1, pulse=True, description="Restart the chip phase / level."),
        ])
        self.comb += [self.invert.eq(self._control.fields.invert), self.phase_rst.eq(self._control.fields.phase_rst)]

# Line Decoder -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPLineDecoder(LiteXModule):
    """Line code to bits. NRZI: a bit from each level change (rate 1:1, latency 1). Manchester
    codes consume chip pairs (rate 1:2; ``phase_rst`` re-aligns the pair phase): a pair without a
    mid-bit transition is a ``violation`` (counted, sticky flag, the bit is taken from the first
    chip). ``invert`` flips the input."""
    def __init__(self, code="nrzi_s", invert=False, with_csr=True):
        check(code in CODES, f"expected code in {CODES}")
        self.code    = code
        self.latency = 1
        self.sink   = stream.Endpoint([("data", 1)])
        self.source = stream.Endpoint([("data", 1)])
        self.invert     = Signal(reset=int(invert))
        self.phase_rst  = Signal()
        self.violation  = Signal()                                      # Sticky.
        self.violations = Signal(32)
        self.clear      = Signal()

        # # #

        adv, xfer = Signal(), Signal()
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        d = Signal()
        self.comb += d.eq(self.sink.data ^ self.invert)
        level = Signal()
        if code in ("nrzi_s", "nrzi_m"):
            self.comb += [self.sink.ready.eq(adv), xfer.eq(self.sink.valid & adv)]
            changed = Signal()
            self.comb += changed.eq(d ^ level)
            self.sync += If(xfer, level.eq(d)), If(self.phase_rst, level.eq(0))
            self.sync += If(adv,
                self.source.valid.eq(self.sink.valid), self.source.first.eq(self.sink.first), self.source.last.eq(self.sink.last),
                self.source.data.eq(~changed if code == "nrzi_s" else changed),
            )
        else:
            phase = Signal()
            chip0 = Signal()
            self.comb += [self.sink.ready.eq(adv), xfer.eq(self.sink.valid & adv)]
            bit = Signal()
            if code == "manchester":
                self.comb += bit.eq(chip0)
            else:
                self.comb += bit.eq(~(chip0 ^ level))                   # No start transition: 1.
            viol = Signal()
            self.comb += viol.eq(d == chip0)
            self.sync += [
                If(self.phase_rst, phase.eq(0), level.eq(0)),
                If(xfer,
                    phase.eq(~phase),
                    If(~phase, chip0.eq(d)).Else(level.eq(d)),
                ),
                If(adv,
                    self.source.valid.eq(xfer & phase),
                    self.source.first.eq(0), self.source.last.eq(self.sink.last),
                    self.source.data.eq(bit),
                ),
                If(xfer & phase & viol, self.violation.eq(1), self.violations.eq(self.violations + 1)),
                If(self.clear, self.violation.eq(0)),
            ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("invert",    size=1, offset=0, reset=self.invert.reset.value, description="Invert the input."),
            CSRField("phase_rst", size=1, offset=1, pulse=True, description="Re-align the chip phase."),
            CSRField("clear",     size=1, offset=2, pulse=True, description="Clear the violation flag."),
        ])
        self._status = CSRStatus(fields=[CSRField("violation", size=1, offset=0, description="Sticky: a chip pair without a mid-bit transition.")])
        self._violations = CSRStatus(32, name="violations", description="Violations since reset.")
        self.comb += [
            self.invert.eq(self._control.fields.invert), self.phase_rst.eq(self._control.fields.phase_rst),
            self.clear.eq(self._control.fields.clear),
            self._status.fields.violation.eq(self.violation), self._violations.status.eq(self.violations),
        ]
