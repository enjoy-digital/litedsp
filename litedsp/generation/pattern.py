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

from litedsp.common import check, iq_layout

PATTERN_CONST   = 0  # Fixed I/Q value (CSR-set).
PATTERN_COUNTER = 1  # Incrementing ramp (I = cnt, Q = ~cnt).
PATTERN_PRBS    = 2  # Maximal-length LFSR.
PATTERN_IMPULSE = 3  # Single full-scale sample, then zeros.

# Maximal-length LFSR feedback masks (shift left, XOR the mask in when the MSB shifts out): bit k
# set for each x**k term of a primitive polynomial of degree data_width (Xilinx XAPP052 taps),
# so the period is 2**data_width - 1.
PRBS_MASKS = {
     3: 0x5,         4: 0x9,         5: 0x9,         6: 0x21,        7: 0x41,
     8: 0x71,        9: 0x21,       10: 0x81,       11: 0x201,      12: 0x53,
    13: 0x1b,       14: 0x2b,       15: 0x4001,     16: 0xa011,     17: 0x4001,
    18: 0x801,      19: 0x47,       20: 0x20001,    21: 0x80001,    22: 0x200001,
    23: 0x40001,    24: 0xc20001,   25: 0x400001,   26: 0x47,       27: 0x27,
    28: 0x2000001,  29: 0x8000001,  30: 0x53,       31: 0x10000001, 32: 0x400007,
}

# Pattern Source -----------------------------------------------------------------------------------

class LiteDSPPatternSource(LiteXModule):
    """I/Q test-pattern generator (constant / counter ramp / PRBS / impulse).

    The impulse pattern emits its full-scale sample on the first output after reset, after
    each change of ``mode`` and after each ``rearm`` pulse (a write of the ``control`` register
    with the CSRs), then zeros.

    Parameters
    ----------
    seed : int
        Initial LFSR state for the PRBS pattern (truncated to data_width, forced non-zero —
        the all-zero state locks the LFSR); makes the sequence reproducible for BER tests.
    """
    def __init__(self, data_width=16, seed=0x1, with_csr=True):
        check(data_width in PRBS_MASKS, "expected 3 <= data_width <= 32")
        self.data_width = data_width
        self.source  = stream.Endpoint(iq_layout(data_width))
        self.mode    = Signal(2, reset=PATTERN_COUNTER)  # Pattern select (PATTERN_*).
        self.const_i = Signal((data_width, True))        # Constant I (PATTERN_CONST).
        self.const_q = Signal((data_width, True))        # Constant Q (PATTERN_CONST).
        self.rearm   = Signal()                          # Re-arm the impulse (pulse).

        # # #

        # Signals.
        # --------
        adv   = Signal()                         # Output register can accept a new sample.
        cnt   = Signal(data_width)               # Ramp counter (counter pattern).
        # Seed forced non-zero (all-zero locks the LFSR).
        lfsr  = Signal(data_width, reset=seed & ((1 << data_width) - 1) or 1)
        last_mode = Signal(3, reset=4)           # Mode of the last output (4: none since reset).
        armed     = Signal()                     # Impulse re-armed by a rearm pulse.
        first     = Signal()                     # Next output is the impulse's first sample.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            first.eq(armed | (last_mode != self.mode)),
        ]

        # LFSR.
        # -----
        # Maximal-length Galois LFSR: shift left, XOR the tap mask back in when the MSB is set.
        fb        = lfsr[-1]
        taps      = PRBS_MASKS[data_width]
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
            last_mode.eq(self.mode),
            armed.eq(0),
        )
        self.sync += If(self.rearm, armed.eq(1))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._control = CSRStorage(fields=[
            CSRField("mode", size=2, reset=PATTERN_COUNTER, values=[
                ("0", "const"), ("1", "counter"), ("2", "prbs"), ("3", "impulse")],
                description="Pattern select (a write re-arms the impulse)."),
        ])
        self._const = CSRStorage(fields=[
            CSRField("i", size=self.data_width, description="Constant I."),
            CSRField("q", size=self.data_width, offset=max(16, self.data_width),
                description="Constant Q."),
        ])
        self.comb += [
            self.mode.eq(self._control.fields.mode),
            self.rearm.eq(self._control.re),
            self.const_i.eq(self._const.fields.i),
            self.const_q.eq(self._const.fields.q),
        ]
