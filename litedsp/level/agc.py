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

# Automatic Gain Control ---------------------------------------------------------------------------

@ResetInserter()
class AGC(LiteXModule):
    """Automatic gain control: drives |output| toward ``target``.

    Estimates the input magnitude (alpha-max-beta-min), integrates the error into a gain
    (``gain += (target - |x|) >> mu``, clamped to ``[0, gain_max]``), and applies it
    (round + saturate). ``mu`` sets the loop time constant. Gain is Q?.``gain_frac``.
    """
    def __init__(self, data_width=16, gain_frac=8, mu=8, gain_max=None, beta_shift=2, with_csr=True):
        self.data_width = data_width
        self.gain_frac  = gain_frac
        self.mu         = mu
        gain_width      = gain_frac + data_width
        if gain_max is None:
            gain_max = (1 << gain_width) - 1
        self.gain_max   = gain_max
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.target = Signal(data_width + 1, reset=1 << (data_width - 2))   # Default ~0.25 FS.
        self.gain   = Signal(gain_width, reset=1 << gain_frac)              # Start at 1.0.

        # # #

        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Apply current (registered) gain.
        out_i, _ = scaled(self.sink.i*self.gain, gain_frac, data_width)
        out_q, _ = scaled(self.sink.q*self.gain, gain_frac, data_width)
        self.sync += If(adv,
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            self.source.valid.eq(self.sink.valid),
        )

        # Measure the *output* magnitude (alpha-max-beta-min) to close the loop.
        ai, aq = Signal(data_width + 1), Signal(data_width + 1)
        self.comb += [
            ai.eq(Mux(out_i[-1], -out_i, out_i)),
            aq.eq(Mux(out_q[-1], -out_q, out_q)),
        ]
        mag = Signal(data_width + 1)
        self.comb += mag.eq(Mux(ai > aq, ai + (aq >> beta_shift), aq + (ai >> beta_shift)))

        # Gain loop (leaky integrator), clamped.
        error    = Signal((data_width + 2, True))
        step     = Signal((data_width + 2, True))
        gain_nxt = Signal((gain_width + 2, True))
        self.comb += [
            error.eq(self.target - mag),
            step.eq(error >> self.mu),
            gain_nxt.eq(self.gain + step),
        ]
        self.sync += If(xfer,
            If(gain_nxt < 0, self.gain.eq(0)
            ).Elif(gain_nxt > gain_max, self.gain.eq(gain_max)
            ).Else(self.gain.eq(gain_nxt)),
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._target = CSRStorage(self.target.nbits, reset=1 << (self.data_width - 2),
            name="target", description="Target output magnitude.")
        self._gain   = CSRStatus(self.gain.nbits, name="gain", description="Current gain (Q?.frac).")
        self.comb += [self.target.eq(self._target.storage), self._gain.status.eq(self.gain)]
