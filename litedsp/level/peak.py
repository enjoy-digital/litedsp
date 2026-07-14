#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common             import iq_layout, real_layout
from litedsp.analysis.magnitude import LiteDSPMagnitude

# Envelope / Peak Detector -------------------------------------------------------------------------

@ResetInserter()
class LiteDSPEnvelopeDetector(LiteXModule):
    """Envelope follower on |I+jQ| with separate attack/release time constants.

    ``env += (|x| - env) >> attack`` when rising, ``>> release`` when falling (single-pole
    smoothing; larger shift = slower). With ``release`` very large it approximates peak-hold.
    Magnitude uses the alpha-max-beta-min approximation.
    """
    def __init__(self, data_width=16, attack=2, release=6, with_csr=True):
        self.attack  = attack
        self.release = release
        self.sink   = stream.Endpoint(iq_layout(data_width))

        # # #

        self.mag = LiteDSPMagnitude(data_width=data_width, with_csr=False)
        W        = self.mag.out_width
        self.source = stream.Endpoint(real_layout(W))
        self.latency = self.mag.latency + 1
        self.comb += self.sink.connect(self.mag.sink)

        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.mag.source.ready.eq(adv)]

        env   = Signal(W)
        m     = Signal((W + 1, True))
        delta = Signal((W + 1, True))
        step  = Signal((W + 1, True))
        self.comb += [
            m.eq(self.mag.source.data),
            delta.eq(m - env),
            step.eq(Mux(delta >= 0, delta >> attack, delta >> release)),
        ]
        self.sync += If(adv,
            env.eq(env + step),
            self.source.data.eq(env + step),
            self.source.valid.eq(self.mag.source.valid),
        )
