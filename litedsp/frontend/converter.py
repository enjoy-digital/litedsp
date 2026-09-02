#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""ADC/DAC boundary adapters: raw converter samples <-> Q1.(N-1) I/Q streams, and the
1-bit modulator interface (sigma-delta ADC / PDM microphone clock + data pins).

Formalizes the converter side of a chain: an ``adc_width``-bit converter word (two's-complement
or offset-binary) becomes a left-aligned (MSB-justified) ``data_width``-bit signed sample, so the
rest of the chain always sees full-scale Q1.(N-1) regardless of the converter resolution — and
symmetrically on the DAC side (round + saturate on the downsize, offset-binary re-encode).

For vendor-specific serdes/DDR capture, wrap the primitive into an ``iq_layout`` raw stream at
the sample clock and feed it through these adapters (e.g. via ``LiteDSPIQClockDomainCrossing``).
"""

from functools import reduce
from operator  import or_

from migen import *

from litex.gen import *

from litex.soc.interconnect import stream

from litedsp.common import check, iq_layout, scaled

# ADC Interface ------------------------------------------------------------------------------------

class LiteDSPADCInterface(LiteXModule):
    """Raw ADC I/Q samples -> Q1.(N-1) stream (sign correction + MSB alignment)."""
    def __init__(self, adc_width=12, data_width=16, fmt="offset_binary"):
        check(fmt in ("offset_binary", "twos"), "expected fmt in ('offset_binary', 'twos')")
        check(adc_width <= data_width, "expected adc_width <= data_width")
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
        check(fmt in ("offset_binary", "twos"), "expected fmt in ('offset_binary', 'twos')")
        check(dac_width <= data_width, "expected dac_width <= data_width")
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

# Bitstream Interface ------------------------------------------------------------------------------

class LiteDSPBitstreamInterface(LiteXModule):
    """Modulator clock + 1-bit data pins -> 1-bit stream(s) (sigma-delta ADC / PDM microphone).

    Generates ``mclk`` (``sys_clk / clock_div``, even ``clock_div >= 4``) and samples the
    synchronized ``mdat`` line(s) after each falling edge of ``mclk`` (data is launched on the
    rising edge by the modulator); with ``dual_edge=True`` each line carries two channels
    (PDM stereo: left after the rising edge, right after the falling edge). ``sources[k]``
    emits one bit per ``mclk`` period as a latest-wins stream (a pending sample not consumed
    in time is overwritten and ``overrun`` latches), so the line is never stalled. The
    two-flop synchronizer places the sample point two cycles after the edge.

    Parameters
    ----------
    clock_div : int
        ``mclk`` period in system clocks (even, >= 4).
    n_channels : int
        Number of 1-bit output streams.
    dual_edge : bool
        Two channels per ``mdat`` line (rising / falling edge), ``n_channels`` even.
    """
    def __init__(self, clock_div=8, n_channels=1, dual_edge=False):
        check(clock_div >= 4 and clock_div % 2 == 0, "expected an even clock_div >= 4")
        check(n_channels >= 1, "expected n_channels >= 1")
        check(not dual_edge or n_channels % 2 == 0, "dual_edge needs an even n_channels")
        self.clock_div  = clock_div
        self.n_channels = n_channels
        self.dual_edge  = dual_edge
        n_lines         = n_channels//2 if dual_edge else n_channels
        self.latency = None
        self.mclk    = Signal()                                    # Modulator clock (output).
        self.mdat    = Signal(n_lines)                             # Modulator data (input).
        self.sources = [stream.Endpoint([("data", 1)]) for _ in range(n_channels)]
        self.overrun = Signal()                                    # A bit was not consumed.
        self.clear   = Signal()                                    # Clear overrun.

        # # #

        # Clock generation.
        # -----------------
        div     = Signal(max=clock_div)
        rise    = Signal()                                         # Cycle after the rising edge.
        fall    = Signal()
        armed   = Signal()                                         # Set at the first falling edge.
        self.sync += [
            If(div == clock_div - 1, div.eq(0)).Else(div.eq(div + 1)),
            If(fall, armed.eq(1)),
        ]
        # The rising-edge strobe (dual-edge second channel) is armed by the first falling edge so
        # a frame always starts with the falling-edge channel (no stray bit from reset).
        self.comb += [
            self.mclk.eq(div < clock_div//2),
            rise.eq((div == 0) & armed),
            fall.eq(div == clock_div//2),
        ]

        # Synchronizers and sample strobes (2 cycles after the edge).
        # -----------------------------------------------------------
        mdat_s1 = Signal(n_lines)
        mdat_s2 = Signal(n_lines)
        rise_d  = Signal(2)
        fall_d  = Signal(2)
        self.sync += [
            mdat_s1.eq(self.mdat), mdat_s2.eq(mdat_s1),
            rise_d.eq(Cat(rise, rise_d[0])), fall_d.eq(Cat(fall, fall_d[0])),
        ]
        strobes = []
        for line in range(n_lines):
            if dual_edge:
                strobes += [(fall_d[1], mdat_s2[line]), (rise_d[1], mdat_s2[line])]
            else:
                strobes += [(fall_d[1], mdat_s2[line])]

        # Latest-wins output streams.
        # ---------------------------
        overrun_any = []
        for source, (strobe, bit) in zip(self.sources, strobes):
            pending = Signal()
            self.comb += source.valid.eq(pending)
            self.sync += [
                If(strobe,
                    source.data.eq(bit),
                    pending.eq(1),
                ).Elif(source.ready,
                    pending.eq(0),
                ),
            ]
            overrun_any.append(strobe & pending & ~source.ready)
        self.sync += If(self.clear, self.overrun.eq(0)).Elif(reduce(or_, overrun_any),
            self.overrun.eq(1))
