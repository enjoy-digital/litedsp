#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common            import check, abc_layout, angle_layout, iq_layout
from litedsp.mixing.mixer      import LiteDSPMixer, MIXER_MODE_DOWN, MIXER_MODE_UP
from litedsp.stream.split      import LiteDSPSplit
from litedsp.stream.delay      import LiteDSPDelay
from litedsp.motor.transforms  import LiteDSPClarke, LiteDSPSinCos
from litedsp.motor.pi          import LiteDSPDQController
from litedsp.motor.svpwm       import LiteDSPSVPWM

# Field-Oriented Control ---------------------------------------------------------------------------

class LiteDSPFOC(LiteXModule):
    """Field-oriented current control: phase currents + rotor angle -> three-phase duties.

    ``sink`` (measured a/b/c currents) goes through the Clarke transform, the Park rotation
    (complex mixer, down) by the sin/cos of ``sink_angle``, the d/q PI current controller
    (:class:`~litedsp.motor.pi.LiteDSPDQController`: setpoints, gains, limit, open-loop
    bring-up vector and optional decoupling via ``speed``), the inverse Park rotation (mixer,
    up) by the *same* sin/cos sample (an atomic fan-out plus a delay matched to the Park +
    controller latency keeps the two rotations sample-aligned and deadlock-free) and the
    space-vector modulator; ``source`` carries the duties for :class:`~litedsp.motor.pwm.
    LiteDSPPWM`, whose one-sample-per-period acceptance paces the whole loop. Both sinks are
    consumed together. The controller's CSRs (``dq_*``) and the modulator's (``svpwm_*``) are
    the block's control surface; ``dq_control.open_loop`` is the bring-up mode. Fixed latency
    ``1 + 2 + (1|2) + 2 + 3`` cycles.

    Parameters
    ----------
    angle_width : int
        Rotor angle width (full turn = 2**angle_width).
    lut_depth : int
        Sin/cos ROM entries per turn.
    three_wire : bool
        Two measured currents (``c = -a - b``) in the Clarke transform.
    gain_width, gain_frac : int
        Controller gain format (signed Q(gain_width-gain_frac).gain_frac).
    anti_windup : str
        Controller integrator anti-windup: ``"conditional"``, ``"clamp"`` or ``"none"``.
    decoupling : bool
        Cross-coupling feed-forward from ``speed`` in the controller.
    """
    def __init__(self, data_width=16, angle_width=16, lut_depth=1024, three_wire=False,
        gain_width=16, gain_frac=12, anti_windup="conditional", decoupling=False, with_csr=True):
        self.data_width  = data_width
        self.angle_width = angle_width
        self.sink       = stream.Endpoint(abc_layout(data_width))      # Phase currents.
        self.sink_angle = stream.Endpoint(angle_layout(angle_width))   # Rotor electrical angle.
        self.source     = stream.Endpoint(abc_layout(data_width))      # Phase duties.
        self.speed      = Signal((data_width, True))                   # Per-unit speed (decoupling).

        # # #

        # Submodules.
        # -----------
        self.clarke = LiteDSPClarke(data_width=data_width, three_wire=three_wire, with_csr=False)
        self.sincos = LiteDSPSinCos(data_width=data_width, angle_width=angle_width,
            lut_depth=lut_depth, with_csr=False)
        self.park   = LiteDSPMixer(data_width=data_width, with_csr=False)
        self.dq     = LiteDSPDQController(data_width=data_width, gain_width=gain_width,
            gain_frac=gain_frac, anti_windup=anti_windup, decoupling=decoupling, with_csr=with_csr)
        self.inverse_park = LiteDSPMixer(data_width=data_width, with_csr=False)
        self.svpwm  = LiteDSPSVPWM(data_width=data_width, with_csr=with_csr)
        # Sin/cos fan-out: the inverse Park needs the same sample after park + dq.
        depth = self.park.latency + self.dq.latency
        self.split  = LiteDSPSplit(n=2, layout=iq_layout(data_width))
        self.delay  = LiteDSPDelay(depth=depth, layout=iq_layout(data_width))
        check(self.delay.depth >= self.park.latency + self.dq.latency,
            "sin/cos delay must cover the Park + controller latency")
        self.latency = (self.clarke.latency + self.park.latency + self.dq.latency
                        + self.inverse_park.latency + self.svpwm.latency)

        # Datapath.
        # ---------
        self.comb += [
            self.park.mode.eq(MIXER_MODE_DOWN),
            self.inverse_park.mode.eq(MIXER_MODE_UP),
            self.dq.speed.eq(self.speed),
            # Currents: abc -> alpha/beta -> d/q.
            self.sink.connect(self.clarke.sink),
            self.clarke.source.connect(self.park.sink_a),
            # Angle: sin/cos, fanned out to both rotations (delayed for the inverse one).
            self.sink_angle.connect(self.sincos.sink),
            self.sincos.source.connect(self.split.sink),
            self.split.sources[0].connect(self.park.sink_b),
            self.split.sources[1].connect(self.delay.sink),
            self.delay.source.connect(self.inverse_park.sink_b),
            # Controller and voltages: d/q -> alpha/beta -> duties.
            self.park.source.connect(self.dq.sink),
            self.dq.source.connect(self.inverse_park.sink_a),
            self.inverse_park.source.connect(self.svpwm.sink),
            self.svpwm.source.connect(self.source),
        ]
