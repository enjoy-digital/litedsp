#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Free-running test-pattern source for chain bring-up and loopback/BER tests.

Emits one of four CSR-selectable patterns on an I/Q stream: a constant, an incrementing ramp
(counter), a maximal-length LFSR (PRBS), or a single impulse followed by zeros. The PRBS is the
useful one for loopback error counting — it is deterministic and reproducible from the seed.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout

PATTERN_CONST   = 0  # Fixed I/Q value (CSR-set).
PATTERN_COUNTER = 1  # Incrementing ramp (I = cnt, Q = ~cnt).
PATTERN_PRBS    = 2  # Maximal-length LFSR.
PATTERN_IMPULSE = 3  # Single full-scale sample, then zeros.

# Pattern Source -----------------------------------------------------------------------------------

class LiteDSPPatternSource(LiteXModule):
    """I/Q test-pattern generator (constant / counter ramp / PRBS / impulse)."""
    def __init__(self, data_width=16, seed=0x1, with_csr=True):
        self.data_width = data_width
        self.source  = stream.Endpoint(iq_layout(data_width))
        self.mode    = Signal(2, reset=PATTERN_COUNTER)  # Pattern select (PATTERN_*).
        self.const_i = Signal((data_width, True))        # Constant I (PATTERN_CONST).
        self.const_q = Signal((data_width, True))        # Constant Q (PATTERN_CONST).

        # # #

        # Signals.
        # --------
        adv   = Signal()                         # Output register can accept a new sample.
        cnt   = Signal(data_width)               # Ramp counter (counter pattern).
        lfsr  = Signal(data_width, reset=seed & ((1 << data_width) - 1) or 1)  # Seed forced non-zero (all-zero locks the LFSR).
        first = Signal(reset=1)                  # Distinguishes the impulse's first sample.
        self.comb += adv.eq(self.source.ready | ~self.source.valid)

        # LFSR.
        # -----
        # Maximal-length Fibonacci LFSR: shift left, XOR the tap mask back in when the MSB is set.
        fb        = lfsr[-1]
        taps      = {16: 0xB400, 12: 0xE08, 8: 0xB8}.get(data_width, 0xB400)
        lfsr_next = (lfsr << 1) ^ Mux(fb, Constant(taps, data_width), 0)

        # Pattern Select.
        # ---------------
        i_pat = Signal((data_width, True))
        q_pat = Signal((data_width, True))
        self.comb += Case(self.mode, {
            PATTERN_CONST:   [i_pat.eq(self.const_i),     q_pat.eq(self.const_q)],
            PATTERN_COUNTER: [i_pat.eq(cnt),              q_pat.eq(~cnt)],
            PATTERN_PRBS:    [i_pat.eq(lfsr),             q_pat.eq(~lfsr)],
            PATTERN_IMPULSE: [i_pat.eq(Mux(first, (1 << (data_width - 1)) - 1, 0)), q_pat.eq(0)],
        })

        # Output.
        # -------
        self.sync += If(adv,
            self.source.valid.eq(1),
            self.source.i.eq(i_pat),
            self.source.q.eq(q_pat),
            cnt.eq(cnt + 1),
            lfsr.eq(lfsr_next),
            first.eq(0),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("mode", size=2, reset=PATTERN_COUNTER, values=[
                ("0", "const"), ("1", "counter"), ("2", "prbs"), ("3", "impulse")],
                description="Pattern select."),
        ])
        self._const = CSRStorage(fields=[
            CSRField("i", size=self.data_width, description="Constant I."),
            CSRField("q", size=self.data_width, offset=16, description="Constant Q."),
        ])
        self.comb += [
            self.mode.eq(self._control.fields.mode),
            self.const_i.eq(self._const.fields.i),
            self.const_q.eq(self._const.fields.q),
        ]
