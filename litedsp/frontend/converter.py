#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""ADC/DAC boundary adapters: raw converter samples <-> Q1.(N-1) I/Q streams.

Formalizes the converter side of a chain: an ``adc_width``-bit converter word (two's-complement
or offset-binary) becomes a left-aligned (MSB-justified) ``data_width``-bit signed sample, so the
rest of the chain always sees full-scale Q1.(N-1) regardless of the converter resolution — and
symmetrically on the DAC side (round + saturate on the downsize, offset-binary re-encode).

For vendor-specific serdes/DDR capture, wrap the primitive into an ``iq_layout`` raw stream at
the sample clock and feed it through these adapters (e.g. via ``LiteDSPIQClockDomainCrossing``).
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import iq_layout, scaled

# ADC Interface ------------------------------------------------------------------------------------

class LiteDSPADCInterface(LiteXModule):
    """Raw ADC I/Q samples -> Q1.(N-1) stream (sign correction + MSB alignment)."""
    def __init__(self, adc_width=12, data_width=16, fmt="offset_binary"):
        assert fmt in ("offset_binary", "twos")
        assert adc_width <= data_width
        self.latency = 0
        self.sink    = stream.Endpoint([("i", adc_width), ("q", adc_width)])   # Raw.
        self.source  = stream.Endpoint(iq_layout(data_width))                  # Signed, left-aligned.

        # # #

        shift = data_width - adc_width   # MSB-justification (left shift) amount.
        msb   = 1 << (adc_width - 1)     # Offset-binary <-> two's complement: invert the MSB.

        # Handshake.
        # ----------
        self.comb += [
            self.source.valid.eq(self.sink.valid), self.sink.ready.eq(self.source.ready),
            self.source.first.eq(self.sink.first), self.source.last.eq(self.sink.last),
        ]

        # Datapath.
        # ---------
        for raw, out in [(self.sink.i, self.source.i), (self.sink.q, self.source.q)]:
            signed_raw = Signal((adc_width, True))
            self.comb += [
                signed_raw.eq(raw ^ msb if fmt == "offset_binary" else raw),
                out.eq(signed_raw << shift),
            ]

# DAC Interface ------------------------------------------------------------------------------------

class LiteDSPDACInterface(LiteXModule):
    """Q1.(N-1) stream -> raw DAC I/Q samples (round + saturate downsize, format re-encode)."""
    def __init__(self, dac_width=12, data_width=16, fmt="offset_binary"):
        assert fmt in ("offset_binary", "twos")
        assert dac_width <= data_width
        self.latency = 0
        self.sink    = stream.Endpoint(iq_layout(data_width))                  # Signed, left-aligned.
        self.source  = stream.Endpoint([("i", dac_width), ("q", dac_width)])   # Raw.

        # # #

        shift = data_width - dac_width   # Downsize (right shift) amount, rounded by `scaled`.
        msb   = 1 << (dac_width - 1)     # Offset-binary <-> two's complement: invert the MSB.

        # Handshake.
        # ----------
        self.comb += [
            self.source.valid.eq(self.sink.valid), self.sink.ready.eq(self.source.ready),
            self.source.first.eq(self.sink.first), self.source.last.eq(self.sink.last),
        ]

        # Rounding/Saturation.
        # --------------------
        for inp, out in [(self.sink.i, self.source.i), (self.sink.q, self.source.q)]:
            trunc, _ = scaled(inp, shift, dac_width)
            self.comb += out.eq(trunc ^ msb if fmt == "offset_binary" else trunc)
