#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Naive integer rate changers (no filtering).

``LiteDSPDownsampler`` keeps one of every ``factor`` samples; ``LiteDSPUpsampler`` emits ``factor`` output
samples per input (sample-and-hold or zero-stuff). They do **no** anti-alias / anti-image
filtering — pair them with a FIR/CIC (e.g. filter then ``LiteDSPDownsampler``, or ``LiteDSPUpsampler`` then
filter), or use the polyphase rate blocks when those land.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

# Downsampler --------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDownsampler(LiteXModule):
    """Keep one of every ``factor`` I/Q samples (naive decimation, no anti-alias filter).

    Parameters
    ----------
    factor_bits : int
        Width in bits of the runtime ``factor`` control/CSR; the maximum decimation factor is
        2**factor_bits - 1 (factor itself is set at runtime, reset value 1).
    """
    def __init__(self, data_width=16, factor_bits=16, with_csr=True):
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.factor = Signal(factor_bits, reset=1)  # Decimation factor (>= 1).

        # # #

        # Handshake.
        # ----------
        advance = Signal()             # Output slot free or being consumed.
        keep    = Signal()             # Current sample is the kept one (start of group).
        count   = Signal(factor_bits)  # Position within the decimation group.
        consume = Signal()             # Input transfer this cycle.
        self.comb += [
            advance.eq(self.source.ready | ~self.source.valid),
            keep.eq(count == 0),
            # Dropped samples are consumed freely; kept samples wait for an output slot.
            self.sink.ready.eq(Mux(keep, advance, 1)),
            consume.eq(self.sink.valid & self.sink.ready),
        ]

        # Sample Counter.
        # ---------------
        self.sync += If(consume,
            If(count == (self.factor - 1), count.eq(0)).Else(count.eq(count + 1))
        )

        # Output.
        # -------
        self.sync += [
            If(consume & keep,
                self.source.i.eq(self.sink.i),
                self.source.q.eq(self.sink.q),
                self.source.valid.eq(1),
            ).Elif(advance,
                self.source.valid.eq(0),  # Output drained without a new kept sample.
            )
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._factor = CSRStorage(self.factor.nbits, reset=1, name="factor",
            description="Decimation factor (keep 1 of every N samples).")
        self.comb += self.factor.eq(self._factor.storage)

# Upsampler ----------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPUpsampler(LiteXModule):
    """Emit ``factor`` I/Q samples per input: sample-and-hold (default) or zero-stuff.

    Parameters
    ----------
    factor_bits : int
        Width in bits of the runtime ``factor`` control/CSR; the maximum interpolation factor
        is 2**factor_bits - 1 (factor itself is set at runtime, reset value 1).
    zero_stuff : bool
        Insert zeros between input samples instead of repeating the held value (build-time
        choice); pair with an anti-image filter sized for the zero-stuff spectral images.
    """
    def __init__(self, data_width=16, factor_bits=16, zero_stuff=False, with_csr=True):
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.factor = Signal(factor_bits, reset=1)  # Interpolation factor (>= 1).

        # # #

        # Handshake.
        # ----------
        advance = Signal()                    # Output slot free or being consumed.
        first   = Signal()                    # Start of an output group (needs a fresh input).
        phase   = Signal(factor_bits)         # Position within the output group.
        held_i  = Signal((data_width, True))  # Sample-and-hold copy for the repeats.
        held_q  = Signal((data_width, True))  # Sample-and-hold copy for the repeats.
        self.comb += [
            advance.eq(self.source.ready | ~self.source.valid),
            first.eq(phase == 0),
            self.sink.ready.eq(first & advance),  # Consume one input per output group.
        ]

        # Output.
        # -------
        self.sync += If(advance,
            If(first,
                If(self.sink.valid,
                    self.source.i.eq(self.sink.i),
                    self.source.q.eq(self.sink.q),
                    self.source.valid.eq(1),
                    held_i.eq(self.sink.i),
                    held_q.eq(self.sink.q),
                    phase.eq(Mux(self.factor == 1, 0, 1)),  # factor == 1: stay in passthrough.
                ).Else(
                    self.source.valid.eq(0),  # No input available yet.
                )
            ).Else(
                self.source.i.eq(0 if zero_stuff else held_i),  # Repeat (S/H) or zero-stuff (build-time).
                self.source.q.eq(0 if zero_stuff else held_q),
                self.source.valid.eq(1),
                If(phase == (self.factor - 1), phase.eq(0)).Else(phase.eq(phase + 1)),
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._factor = CSRStorage(self.factor.nbits, reset=1, name="factor",
            description="Interpolation factor (emit N samples per input).")
        self.comb += self.factor.eq(self._factor.storage)
