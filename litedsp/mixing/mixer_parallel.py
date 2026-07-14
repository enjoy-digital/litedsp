#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common       import iq_layout, iq_lanes, scaled
from litedsp.mixing.mixer import MIXER_MODE_DOWN, MIXER_MODE_UP

# Parallel Mixer -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPParallelMixer(LiteXModule):
    """Complex mixer over ``n_samples`` lanes per beat (multi-sample-per-cycle datapaths).

    Per-lane arithmetic and rounding are identical to :class:`~litedsp.mixing.mixer.LiteDSPMixer`
    (runtime up/down ``mode``, round-half-up + saturate on the product rescale), so a parallel
    path produces the same samples as the serial one — with ``4*n_samples`` multipliers and the
    same fixed 2-cycle latency. Both sinks are consumed together.
    """
    def __init__(self, n_samples=2, data_width=16, shift=None, with_csr=True):
        assert n_samples >= 1
        if shift is None:
            shift = data_width - 1
        self.n_samples  = n_samples
        self.data_width = data_width
        self.latency    = 2
        self.sink_a = stream.Endpoint(iq_layout(data_width, n_samples))  # I/Q A input (signal).
        self.sink_b = stream.Endpoint(iq_layout(data_width, n_samples))  # I/Q B input (LO/other).
        self.source = stream.Endpoint(iq_layout(data_width, n_samples))  # I/Q output.
        self.mode   = Signal()                                           # 0: down, 1: up.

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

        # Per-lane datapath (same two pipeline stages as Mixer).
        # ------------------------------------------------------
        lanes = zip(iq_lanes(self.sink_a, data_width, n_samples),
                    iq_lanes(self.sink_b, data_width, n_samples),
                    iq_lanes(self.source, data_width, n_samples))
        for (a_i_bits, a_q_bits), (b_i_bits, b_q_bits), (o_i, o_q) in lanes:
            a_i, a_q = Signal((data_width, True)), Signal((data_width, True))
            b_i, b_q = Signal((data_width, True)), Signal((data_width, True))
            self.comb += [a_i.eq(a_i_bits), a_q.eq(a_q_bits),
                          b_i.eq(b_i_bits), b_q.eq(b_q_bits)]

            # Stage 1: products.
            p_ii = Signal((2*data_width, True))
            p_qq = Signal((2*data_width, True))
            p_qi = Signal((2*data_width, True))
            p_iq = Signal((2*data_width, True))
            self.sync += If(advance,
                p_ii.eq(a_i*b_i),
                p_qq.eq(a_q*b_q),
                p_qi.eq(a_q*b_i),
                p_iq.eq(a_i*b_q),
            )

            # Stage 2: combine per mode.
            i_full = Signal((2*data_width + 1, True))
            q_full = Signal((2*data_width + 1, True))
            self.sync += If(advance,
                If(self.mode == MIXER_MODE_DOWN,
                    i_full.eq(p_ii + p_qq),  # Re{a * conj(b)}.
                    q_full.eq(p_qi - p_iq),  # Im{a * conj(b)}.
                ).Else(
                    i_full.eq(p_ii - p_qq),  # Re{a * b}.
                    q_full.eq(p_qi + p_iq),  # Im{a * b}.
                ),
            )

            # Output: rescale product (round + saturate).
            mix_i, _ = scaled(i_full, shift, data_width)
            mix_q, _ = scaled(q_full, shift, data_width)
            self.comb += [o_i.eq(mix_i), o_q.eq(mix_q)]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("mode", size=1, offset=0, values=[
                ("``0b0``", "Down-conversion (a * conj(b))."),
                ("``0b1``", "Up-conversion (a * b)."),
            ]),
        ])
        self.comb += self.mode.eq(self._control.fields.mode)
