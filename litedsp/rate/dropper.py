#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Naive integer rate changers (no filtering).

``Downsampler`` keeps one of every ``factor`` samples; ``Upsampler`` emits ``factor`` output
samples per input (sample-and-hold or zero-stuff). They do **no** anti-alias / anti-image
filtering — pair them with a FIR/CIC (e.g. filter then ``Downsampler``, or ``Upsampler`` then
filter), or use the polyphase rate blocks when those land.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# Downsampler --------------------------------------------------------------------------------------

@ResetInserter()
class Downsampler(LiteXModule):
    """Keep one of every ``factor`` I/Q samples (naive decimation, no anti-alias filter)."""
    def __init__(self, data_width=16, factor_bits=16, with_csr=True):
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.factor = Signal(factor_bits, reset=1)  # Decimation factor (>= 1).

        # # #

        advance = Signal()
        keep    = Signal()
        count   = Signal(factor_bits)
        consume = Signal()
        self.comb += [
            advance.eq(self.source.ready | ~self.source.valid),
            keep.eq(count == 0),
            # Dropped samples are consumed freely; kept samples wait for an output slot.
            self.sink.ready.eq(Mux(keep, advance, 1)),
            consume.eq(self.sink.valid & self.sink.ready),
        ]
        self.sync += If(consume,
            If(count == (self.factor - 1), count.eq(0)).Else(count.eq(count + 1))
        )
        self.sync += [
            If(consume & keep,
                self.source.i.eq(self.sink.i),
                self.source.q.eq(self.sink.q),
                self.source.valid.eq(1),
            ).Elif(advance,
                self.source.valid.eq(0),
            )
        ]

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._factor = CSRStorage(self.factor.nbits, reset=1, name="factor",
            description="Decimation factor (keep 1 of every N samples).")
        self.comb += self.factor.eq(self._factor.storage)

# Upsampler ----------------------------------------------------------------------------------------

@ResetInserter()
class Upsampler(LiteXModule):
    """Emit ``factor`` I/Q samples per input: sample-and-hold (default) or zero-stuff."""
    def __init__(self, data_width=16, factor_bits=16, zero_stuff=False, with_csr=True):
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.factor = Signal(factor_bits, reset=1)  # Interpolation factor (>= 1).

        # # #

        advance = Signal()
        first   = Signal()
        phase   = Signal(factor_bits)
        held_i  = Signal((data_width, True))
        held_q  = Signal((data_width, True))
        self.comb += [
            advance.eq(self.source.ready | ~self.source.valid),
            first.eq(phase == 0),
            self.sink.ready.eq(first & advance),  # Consume one input per output group.
        ]
        self.sync += If(advance,
            If(first,
                If(self.sink.valid,
                    self.source.i.eq(self.sink.i),
                    self.source.q.eq(self.sink.q),
                    self.source.valid.eq(1),
                    held_i.eq(self.sink.i),
                    held_q.eq(self.sink.q),
                    phase.eq(Mux(self.factor == 1, 0, 1)),
                ).Else(
                    self.source.valid.eq(0),  # No input available yet.
                )
            ).Else(
                self.source.i.eq(0 if zero_stuff else held_i),
                self.source.q.eq(0 if zero_stuff else held_q),
                self.source.valid.eq(1),
                If(phase == (self.factor - 1), phase.eq(0)).Else(phase.eq(phase + 1)),
            )
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._factor = CSRStorage(self.factor.nbits, reset=1, name="factor",
            description="Interpolation factor (emit N samples per input).")
        self.comb += self.factor.eq(self._factor.storage)
