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

    Parameters
    ----------
    attack : int
        Attack shift, applied while the magnitude rises (env += (|x| - env) >> attack).
        Smaller = faster tracking of level increases; time constant ~ 2**attack samples.
    release : int
        Release shift, applied while the magnitude falls; larger = slower decay (time constant
        ~ 2**release samples). A very large value approximates a peak-hold detector.
    """
    def __init__(self, data_width=16, attack=2, release=6, with_csr=True):
        self.attack  = attack
        self.release = release
        self.sink   = stream.Endpoint(iq_layout(data_width))

        # # #

        # Magnitude.
        # ----------
        self.mag = LiteDSPMagnitude(data_width=data_width, with_csr=False)
        W        = self.mag.out_width
        self.source = stream.Endpoint(real_layout(W))
        self.latency = self.mag.latency + 1
        self.comb += self.sink.connect(self.mag.sink)

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.mag.source.ready.eq(adv)]

        # Envelope Follower.
        # ------------------
        env   = Signal(W)              # Envelope state (unsigned).
        m     = Signal((W + 1, True))  # Magnitude, signed for the subtract below.
        delta = Signal((W + 1, True))
        step  = Signal((W + 1, True))
        self.comb += [
            m.eq(self.mag.source.data),
            delta.eq(m - env),
            step.eq(Mux(delta >= 0, delta >> attack, delta >> release)),  # Rising: fast; falling: slow.
        ]
        self.sync += If(adv,
            self.source.valid.eq(self.mag.source.valid),
            # Envelope time constants are expressed in accepted samples, not wall-clock cycles.
            # A bubble may advance the pipeline, but must not re-integrate stale magnitude data.
            If(self.mag.source.valid,
                env.eq(env + step),
                self.source.data.eq(env + step),  # Register the updated envelope (same value env takes).
            )
        )
