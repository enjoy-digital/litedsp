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

# Gain ---------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPGain(LiteXModule):
    """Runtime-configurable gain for a complex I/Q stream, with bypass and saturation.

    The output is ``sample * gain / 2**(gain_frac + shift)`` with round-half-up + saturation.
    ``gain`` is a signed Q2.(N-2) mantissa (default 1.0); ``shift`` (0..3) divides by an extra
    1/2/4/8. ``saturation`` is a sticky status flag (cleared via ``clear_sat``).

    Parameters
    ----------
    gain_frac : int
        Fractional bits of the signed gain mantissa (1.0 = 2**gain_frac, reset value). Defaults
        to data_width - 2, i.e. a Q2.(N-2) mantissa spanning gains up to just under 2.0.
    """
    def __init__(self, data_width=16, gain_frac=None, with_csr=True):
        if gain_frac is None:
            gain_frac = data_width - 2          # Q2.(N-2) mantissa.
        self.data_width = data_width
        self.gain_frac  = gain_frac
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.gain      = Signal((data_width, True), reset=(1 << gain_frac))  # Q2.(N-2), 1.0.
        self.shift     = Signal(2)                                           # Extra /1, /2, /4, /8.
        self.bypass    = Signal()                                            # Passthrough (no gain).
        self.clear_sat = Signal()                                            # Clear sticky sat flag.
        self.sat       = Signal()                                            # Sticky overflow.

        # # #

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
        ]

        # Products and per-shift round+saturate results.
        # ----------------------------------------------
        prod_i = self.sink.i * self.gain
        prod_q = self.sink.q * self.gain
        res_i, res_q = Signal((data_width, True)), Signal((data_width, True))
        ovf          = Signal()
        cases = {}
        # One pre-scaled result per shift setting (0..3); Case muxes the selected one.
        for s in range(4):
            ri, oi = scaled(prod_i, gain_frac + s, data_width)
            rq, oq = scaled(prod_q, gain_frac + s, data_width)
            cases[s] = [res_i.eq(ri), res_q.eq(rq), ovf.eq(oi | oq)]
        self.comb += Case(self.shift, cases)

        # Output register + sticky saturation flag.
        # -----------------------------------------
        self.sync += If(adv,
            If(self.bypass,
                self.source.i.eq(self.sink.i),
                self.source.q.eq(self.sink.q),
            ).Else(
                self.source.i.eq(res_i),
                self.source.q.eq(res_q),
            ),
            self.source.valid.eq(self.sink.valid),
        )
        self.sync += [
            If(self.clear_sat,
                self.sat.eq(0),
            ).Elif(self.sink.valid & adv & ~self.bypass & ovf,  # Bypass path cannot saturate.
                self.sat.eq(1),
            )
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._gain   = CSRStorage(self.data_width, reset=(1 << self.gain_frac), name="gain",
            description="Gain mantissa (signed Q2.(N-2), 1.0 = 2**(N-2)).")
        self._control = CSRStorage(fields=[
            CSRField("shift",     size=2, offset=0, description="Extra right shift (/1, /2, /4, /8)."),
            CSRField("bypass",    size=1, offset=2, description="Bypass gain (passthrough)."),
            CSRField("clear_sat", size=1, offset=3, pulse=True, description="Clear saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturation", size=1, description="Output saturated since last clear."),
        ])
        self.comb += [
            self.gain.eq(     self._gain.storage),
            self.shift.eq(    self._control.fields.shift),
            self.bypass.eq(   self._control.fields.bypass),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.saturation.eq(self.sat),
        ]
