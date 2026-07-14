#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled

# Mixer Constants ----------------------------------------------------------------------------------

MIXER_MODE_DOWN = 0  # Down-conversion: source = sink_a * conj(sink_b).
MIXER_MODE_UP   = 1  # Up-conversion:   source = sink_a * sink_b.

MIXER_BYPASS_DISABLED = 0
MIXER_BYPASS_SINK_A   = 1
MIXER_BYPASS_SINK_B   = 2

# Mixer --------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPMixer(LiteXModule):
    """Complex mixer with runtime up/down mode and bypass.

    Multiplies two complex I/Q streams ``sink_a`` and ``sink_b`` and outputs the rescaled
    result on ``source``. ``mode`` selects up- or down-conversion at runtime (not build time).
    The full-precision product is rescaled with round-half-up + saturation (no silent
    truncation/overflow). Both sinks are consumed together; ``source`` is produced after a
    fixed 2-cycle latency.
    """
    def __init__(self, data_width=16, shift=None, with_csr=True):
        if shift is None:
            shift = data_width - 1
        self.data_width = data_width
        self.latency    = 2
        self.sink_a = stream.Endpoint(iq_layout(data_width))  # I/Q A input (signal).
        self.sink_b = stream.Endpoint(iq_layout(data_width))  # I/Q B input (LO/other).
        self.source = stream.Endpoint(iq_layout(data_width))  # I/Q output.
        self.mode   = Signal()                                # 0: down, 1: up.
        self.bypass = Signal(2)                               # 0: off, 1: sink_a, 2: sink_b.

        # # #

        # Pipeline clock-enable / join handshake.
        # ---------------------------------------
        advance = Signal()
        self.comb += [
            advance.eq(self.source.ready | ~self.source.valid),
            self.sink_a.ready.eq(advance & self.sink_b.valid),
            self.sink_b.ready.eq(advance & self.sink_a.valid),
        ]
        push     = Signal()
        valid_sr = Signal(self.latency)
        self.comb += push.eq(self.sink_a.valid & self.sink_b.valid)
        self.sync += If(advance, valid_sr.eq(Cat(push, valid_sr[:-1])))
        self.comb += self.source.valid.eq(valid_sr[-1])

        # Stage 1: products + input delay (for bypass alignment).
        # -------------------------------------------------------
        p_ii = Signal((2*data_width, True))
        p_qq = Signal((2*data_width, True))
        p_qi = Signal((2*data_width, True))
        p_iq = Signal((2*data_width, True))
        a_i1, a_q1 = Signal((data_width, True)), Signal((data_width, True))
        b_i1, b_q1 = Signal((data_width, True)), Signal((data_width, True))
        self.sync += If(advance,
            p_ii.eq(self.sink_a.i * self.sink_b.i),
            p_qq.eq(self.sink_a.q * self.sink_b.q),
            p_qi.eq(self.sink_a.q * self.sink_b.i),
            p_iq.eq(self.sink_a.i * self.sink_b.q),
            a_i1.eq(self.sink_a.i), a_q1.eq(self.sink_a.q),
            b_i1.eq(self.sink_b.i), b_q1.eq(self.sink_b.q),
        )

        # Stage 2: combine per mode + input delay (2nd stage).
        # ----------------------------------------------------
        i_full = Signal((2*data_width + 1, True))
        q_full = Signal((2*data_width + 1, True))
        a_i2, a_q2 = Signal((data_width, True)), Signal((data_width, True))
        b_i2, b_q2 = Signal((data_width, True)), Signal((data_width, True))
        self.sync += If(advance,
            If(self.mode == MIXER_MODE_DOWN,
                i_full.eq(p_ii + p_qq),  # Re{a * conj(b)}.
                q_full.eq(p_qi - p_iq),  # Im{a * conj(b)}.
            ).Else(
                i_full.eq(p_ii - p_qq),  # Re{a * b}.
                q_full.eq(p_qi + p_iq),  # Im{a * b}.
            ),
            a_i2.eq(a_i1), a_q2.eq(a_q1),
            b_i2.eq(b_i1), b_q2.eq(b_q1),
        )

        # Output: rescale product (round + saturate) or bypass a delayed input.
        # ---------------------------------------------------------------------
        mix_i, _ = scaled(i_full, shift, data_width)
        mix_q, _ = scaled(q_full, shift, data_width)
        self.comb += Case(self.bypass, {
            MIXER_BYPASS_DISABLED : [self.source.i.eq(mix_i), self.source.q.eq(mix_q)],
            MIXER_BYPASS_SINK_A   : [self.source.i.eq(a_i2),  self.source.q.eq(a_q2)],
            MIXER_BYPASS_SINK_B   : [self.source.i.eq(b_i2),  self.source.q.eq(b_q2)],
        })

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("mode",   size=1, offset=0, values=[
                ("``0b0``", "Down-conversion (a * conj(b))."),
                ("``0b1``", "Up-conversion (a * b)."),
            ]),
            CSRField("bypass", size=2, offset=8, values=[
                ("``0b00``", "Bypass disabled (mix)."),
                ("``0b01``", "Pass Sink A to Source."),
                ("``0b10``", "Pass Sink B to Source."),
            ]),
        ])
        self.comb += [
            self.mode.eq(  self._control.fields.mode),
            self.bypass.eq(self._control.fields.bypass),
        ]
