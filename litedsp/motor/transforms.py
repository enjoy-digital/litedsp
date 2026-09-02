#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Reference-frame transforms for field-oriented motor control.

Three-phase quantities (``abc_layout``) map to the two-phase stationary frame (alpha/beta,
carried on ``iq_layout`` as i = alpha, q = beta) by the amplitude-invariant Clarke transform,
and to the rotor frame (d/q, again ``iq_layout``) by the Park rotation. Because ``alpha +
j*beta`` is the complex space vector, the Park transform is literally a complex mixer:
``d + jq = (alpha + j*beta) * exp(-j*theta)`` (mixer down-mode, ``a * conj(b)``) and the inverse
Park is the up-mode product -- so both reuse :class:`~litedsp.mixing.mixer.LiteDSPMixer` fed by
a sin/cos lookup. Angles follow the CORDIC/NCO convention (signed, full circle =
``2**angle_width``); samples are per-unit Q1.(N-1).
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common            import check, abc_layout, angle_layout, iq_layout, scaled
from litedsp.generation.nco    import sincos_rom
from litedsp.generation.cordic import LiteDSPCORDIC
from litedsp.mixing.mixer      import LiteDSPMixer, MIXER_MODE_DOWN, MIXER_MODE_UP

# Constants ----------------------------------------------------------------------------------------

CONST_FRAC = 15                                               # Transform constants are Q1.15.
C_1_3      = int(round((1/3)*(1 << CONST_FRAC)))              # 1/3       = 10923.
C_1_SQ3    = int(round((1/math.sqrt(3))*(1 << CONST_FRAC)))   # 1/sqrt(3) = 18919.
C_SQ3_2    = int(round((math.sqrt(3)/2)*(1 << CONST_FRAC)))   # sqrt(3)/2 = 28378.

# Clarke Transform ---------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPClarke(LiteXModule):
    """Clarke transform: three-phase a/b/c -> stationary alpha/beta (amplitude-invariant).

    ``alpha = (2a - b - c)/3`` and ``beta = (b - c)/sqrt(3)``: a balanced set of peak ``A``
    maps to a space vector of magnitude ``A``. With ``three_wire=True`` the block assumes
    ``a + b + c = 0`` (two measured phase currents, the third implied by Kirchhoff): ``alpha =
    a`` exactly and ``beta = (a + 2b)/sqrt(3)``, one multiplier fewer. Constants are Q1.15 and
    each output is rounded + saturated once. Output on ``iq_layout`` (i = alpha, q = beta),
    fixed 1-cycle latency.

    Parameters
    ----------
    three_wire : bool
        Use phases a and b only (``c = -a - b`` implied); ``alpha = a`` is then exact.
    """
    def __init__(self, data_width=16, three_wire=False, with_csr=True):
        check(data_width >= 4, "expected data_width >= 4")
        check(isinstance(three_wire, bool), "expected three_wire to be a bool")
        self.data_width = data_width
        self.three_wire = three_wire
        self.latency    = 1
        self.sink   = stream.Endpoint(abc_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        # Datapath.
        # ---------
        # Sums and products live in explicitly sized Signals (Verilog sizes an inline product
        # to its assignment context, see litedsp/level/gain.py).
        a, b, c = self.sink.a, self.sink.b, self.sink.c
        SW = data_width + 2                       # 2a - b - c / a + 2b.
        PW = SW + CONST_FRAC + 1                  # Times a Q1.15 constant.
        s_beta    = Signal((SW, True))
        beta_full = Signal((PW, True))
        if three_wire:
            self.comb += [s_beta.eq(a + 2*b), beta_full.eq(s_beta*C_1_SQ3)]
            alpha = a
        else:
            s_alpha    = Signal((SW, True))
            alpha_full = Signal((PW, True))
            self.comb += [
                s_alpha.eq(2*a - b - c), alpha_full.eq(s_alpha*C_1_3),
                s_beta.eq(b - c),        beta_full.eq(s_beta*C_1_SQ3),
            ]
            alpha, _ = scaled(alpha_full, CONST_FRAC, data_width)
        beta, _ = scaled(beta_full, CONST_FRAC, data_width)

        # Output.
        # -------
        self.sync += If(adv,
            self.source.i.eq(alpha),
            self.source.q.eq(beta),
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
        )

# Inverse Clarke Transform -------------------------------------------------------------------------

@ResetInserter()
class LiteDSPInverseClarke(LiteXModule):
    """Inverse Clarke transform: stationary alpha/beta -> three-phase a/b/c.

    ``a = alpha``, ``b = (-alpha + sqrt(3)*beta)/2``, ``c = (-alpha - sqrt(3)*beta)/2`` with
    one Q1.15 rounding + saturation per phase. A vector of magnitude above 1.0 pu saturates
    (phase voltages reach 1.1547 pu in the space-vector linear range), which is why
    :class:`~litedsp.motor.svpwm.LiteDSPSVPWM` keeps its own wider inverse Clarke. Fixed
    1-cycle latency.
    """
    def __init__(self, data_width=16, with_csr=True):
        check(data_width >= 4, "expected data_width >= 4")
        self.data_width = data_width
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(abc_layout(data_width))

        # # #

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        # Datapath.
        # ---------
        PW = data_width + CONST_FRAC + 2
        kb_full = Signal((PW, True))              # sqrt(3)/2 * beta   (Q.15 domain).
        half_a  = Signal((PW, True))              # alpha/2            (Q.15 domain).
        b_full  = Signal((PW + 1, True))
        c_full  = Signal((PW + 1, True))
        self.comb += [
            kb_full.eq(self.sink.q*C_SQ3_2),
            half_a.eq(self.sink.i << (CONST_FRAC - 1)),
            b_full.eq(kb_full - half_a),
            c_full.eq(-kb_full - half_a),
        ]
        b, _ = scaled(b_full, CONST_FRAC, data_width)
        c, _ = scaled(c_full, CONST_FRAC, data_width)

        # Output.
        # -------
        self.sync += If(adv,
            self.source.a.eq(self.sink.i),
            self.source.b.eq(b),
            self.source.c.eq(c),
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
        )

# Sin/Cos Lookup -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSinCos(LiteXModule):
    """Angle stream -> ``(cos, sin)`` unit vector on ``iq_layout`` (i = cos, q = sin).

    ``method="rom"``: quarter-wave sine ROM addressed by the top ``log2(lut_depth)`` angle
    bits (the NCO's table, bit-identical to the full-period tables), 1-cycle latency, no DSP.
    ``method="cordic"``: :class:`~litedsp.generation.cordic.LiteDSPCORDIC` rotation of the
    full-scale vector by the angle (``stages + 2`` cycles, no ROM, full angle resolution).
    Full scale is ``2**(data_width-1) - 1`` (0.99997 pu), as for the NCO.

    Parameters
    ----------
    angle_width : int
        Angle word width; the full circle spans ``2**angle_width`` (CORDIC/NCO convention).
    lut_depth : int
        ROM entries per turn (power of two >= 8, <= 2**angle_width); the angle is truncated
        to ``log2(lut_depth)`` bits (``method="rom"`` only).
    method : str
        ``"rom"`` (table lookup) or ``"cordic"`` (rotation pipeline).
    stages : int
        CORDIC iterations (``method="cordic"``; defaults to ``data_width``).
    """
    def __init__(self, data_width=16, angle_width=16, lut_depth=1024, method="rom", stages=None,
        with_csr=True):
        check(method in ("rom", "cordic"), "expected method in ('rom', 'cordic')")
        check(angle_width >= 2, "expected angle_width >= 2")
        addr_bits = int(math.log2(lut_depth)) if lut_depth > 0 else 0
        check(lut_depth >= 8 and (1 << addr_bits) == lut_depth, "lut_depth must be a power of two >= 8")
        check(addr_bits <= angle_width, "expected log2(lut_depth) <= angle_width")
        if stages is None:
            stages = data_width
        check(stages >= 1, "expected stages >= 1")
        self.data_width  = data_width
        self.angle_width = angle_width
        self.method      = method
        self.latency     = 1 if method == "rom" else stages + 2
        self.sink   = stream.Endpoint(angle_layout(angle_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        if method == "cordic":
            # CORDIC rotation of the full-scale vector (1, 0) by the angle.
            # ---------------------------------------------------------------
            self.cordic = cordic = LiteDSPCORDIC(data_width=data_width, angle_width=angle_width,
                stages=stages, mode="rotation", with_csr=False)
            self.comb += [
                cordic.sink.valid.eq(self.sink.valid),
                cordic.sink.first.eq(self.sink.first),
                cordic.sink.last.eq(self.sink.last),
                cordic.sink.x.eq((1 << (data_width - 1)) - 1),
                cordic.sink.y.eq(0),
                cordic.sink.z.eq(self.sink.angle),
                self.sink.ready.eq(cordic.sink.ready),
                self.source.valid.eq(cordic.source.valid),
                self.source.first.eq(cordic.source.first),
                self.source.last.eq(cordic.source.last),
                self.source.i.eq(cordic.source.x),
                self.source.q.eq(cordic.source.y),
                cordic.source.ready.eq(self.source.ready),
            ]
            return

        # Handshake.
        # ----------
        adv = Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv)]

        # ROM lookup (registered read; the port holds its output while stalled).
        # ----------------------------------------------------------------------
        addr     = self.sink.angle[angle_width - addr_bits:]       # Top angle bits, as a phase.
        cos, sin = sincos_rom(self, addr, adv, data_width, lut_depth, quarter_wave=True)
        self.comb += [self.source.i.eq(cos), self.source.q.eq(sin)]
        self.sync += If(adv,
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
        )

# Angle Ramp ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPAngleRamp(LiteXModule):
    """Free-running electrical-angle source: a phase accumulator emitting an angle stream.

    ``angle`` advances by ``phase_inc`` (top ``angle_width`` bits of a ``phase_bits``
    accumulator) per accepted sample, so backpressure never skips or repeats a step. Drives the
    open-loop / V/f bring-up of a drive (constant-frequency rotating voltage vector) and the
    transform tests; set ``phase_inc = f_e / f_ctrl * 2**phase_bits`` for an electrical
    frequency ``f_e`` at control rate ``f_ctrl``.
    """
    def __init__(self, angle_width=16, phase_bits=32, with_csr=True):
        check(angle_width >= 2, "expected angle_width >= 2")
        check(phase_bits >= angle_width, "expected phase_bits >= angle_width")
        self.angle_width = angle_width
        self.phase_bits  = phase_bits
        self.latency     = None                           # Source-only.
        self.phase_inc   = Signal(phase_bits)             # Angle increment per sample (control).
        self.source      = stream.Endpoint(angle_layout(angle_width))

        # # #

        # Phase Accumulator.
        # ------------------
        phase = Signal(phase_bits)
        ce    = Signal()                                  # Advance when the output can accept.
        self.comb += ce.eq(self.source.ready | ~self.source.valid)
        self.sync += If(ce,
            phase.eq(phase + self.phase_inc),
            self.source.valid.eq(1),
        )
        self.comb += self.source.angle.eq(phase[phase_bits - angle_width:])

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._phase_inc = CSRStorage(self.phase_bits, name="phase_inc",
            description="Angle increment per sample (2**phase_bits = one electrical turn).")
        self.comb += self.phase_inc.eq(self._phase_inc.storage)

# Park Transforms ----------------------------------------------------------------------------------

class _LiteDSPParkRotation(LiteXModule):
    """Shared Park / inverse-Park composite: sin/cos lookup + complex mixer (down or up)."""
    def __init__(self, mode, data_width=16, angle_width=16, lut_depth=1024, method="rom",
        stages=None, with_csr=True):
        self.data_width  = data_width
        self.angle_width = angle_width
        self.sink       = stream.Endpoint(iq_layout(data_width))      # alpha/beta (or d/q).
        self.sink_angle = stream.Endpoint(angle_layout(angle_width))  # Rotor electrical angle.
        self.source     = stream.Endpoint(iq_layout(data_width))      # d/q (or alpha/beta).

        # # #

        # Submodules.
        # -----------
        self.sincos = LiteDSPSinCos(data_width=data_width, angle_width=angle_width,
            lut_depth=lut_depth, method=method, stages=stages, with_csr=False)
        self.mixer  = LiteDSPMixer(data_width=data_width, with_csr=False)   # Mode hardwired.
        self.latency = self.mixer.latency          # Data path; the angle path adds sincos.latency.

        # Datapath.
        # ---------
        self.comb += [
            self.mixer.mode.eq(mode),
            self.sink.connect(self.mixer.sink_a),
            self.sink_angle.connect(self.sincos.sink),
            self.sincos.source.connect(self.mixer.sink_b),
            self.mixer.source.connect(self.source),
        ]

class LiteDSPPark(_LiteDSPParkRotation):
    """Park transform: stationary alpha/beta + rotor angle -> rotating d/q.

    ``d + jq = (alpha + j*beta) * exp(-j*theta)``, i.e. the complex mixer in down-mode
    (``a * conj(b)``) with ``b = (cos theta, sin theta)`` from :class:`LiteDSPSinCos`. Both
    sinks are consumed together (sample-aligned join); the result is rounded + saturated once.
    Data-path latency 2 cycles (the angle path adds the sin/cos latency, 1 for the ROM).

    Parameters
    ----------
    angle_width : int
        Angle word width; the full circle spans ``2**angle_width``.
    lut_depth : int
        Sin/cos ROM entries per turn (``method="rom"``).
    method : str
        Sin/cos generation: ``"rom"`` (table) or ``"cordic"``.
    stages : int
        CORDIC iterations (``method="cordic"``; defaults to ``data_width``).
    """
    def __init__(self, data_width=16, angle_width=16, lut_depth=1024, method="rom", stages=None,
        with_csr=True):
        _LiteDSPParkRotation.__init__(self, MIXER_MODE_DOWN, data_width=data_width,
            angle_width=angle_width, lut_depth=lut_depth, method=method, stages=stages,
            with_csr=with_csr)

class LiteDSPInversePark(_LiteDSPParkRotation):
    """Inverse Park transform: rotating d/q + rotor angle -> stationary alpha/beta.

    ``alpha + j*beta = (d + jq) * exp(+j*theta)``: the complex mixer in up-mode (``a * b``)
    with ``b = (cos theta, sin theta)``. Same interface, join and latency as
    :class:`LiteDSPPark`.

    Parameters
    ----------
    angle_width : int
        Angle word width; the full circle spans ``2**angle_width``.
    lut_depth : int
        Sin/cos ROM entries per turn (``method="rom"``).
    method : str
        Sin/cos generation: ``"rom"`` (table) or ``"cordic"``.
    stages : int
        CORDIC iterations (``method="cordic"``; defaults to ``data_width``).
    """
    def __init__(self, data_width=16, angle_width=16, lut_depth=1024, method="rom", stages=None,
        with_csr=True):
        _LiteDSPParkRotation.__init__(self, MIXER_MODE_UP, data_width=data_width,
            angle_width=angle_width, lut_depth=lut_depth, method=method, stages=stages,
            with_csr=with_csr)
