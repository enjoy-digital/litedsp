#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Angle observers: a type-II tracking loop (angle PLL) and a sensorless sliding-mode
back-EMF observer for PMSM."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common            import check, angle_layout, iq_layout, rounded, saturated
from litedsp.control           import LiteDSPPILoop
from litedsp.generation.cordic import LiteDSPCORDIC

# Angle Tracker ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPAngleTracker(LiteXModule):
    """Type-II tracking loop on an angle stream: filtered angle + speed (angle PLL).

    Per accepted sample the wrapped error ``e = angle_in - theta`` drives a
    :class:`~litedsp.control.LiteDSPPILoop` (shift gains ``kp_shift``/``ki_shift``, runtime
    controls) whose output advances the internal angle ``theta`` (``angle_width + frac_bits``
    bits): ``theta += (e >> kp_shift) + integral`` and ``integral += e >> ki_shift`` (error in the
    ``frac_bits`` domain). The emitted angle is the estimate *for the accepted sample*
    (``theta`` before its update, like the carrier loop's NCO phase) plus ``angle_offset``
    (sensor alignment / observer lag compensation): a constant-speed input is
    tracked with zero steady-state error; the integrator is the ``speed`` (angle units per
    sample, Q.``frac_bits``), so the raw noisy angle from an encoder, Hall decoder or observer
    becomes a smooth estimate (``theta + speed`` predicts the next sample). Latency 1.

    Parameters
    ----------
    angle_width : int
        Angle width (full turn = 2**angle_width).
    frac_bits : int
        Fractional bits of the internal angle / speed accumulators.
    kp_shift : int
        Reset proportional shift (larger = slower).
    ki_shift : int
        Reset integral shift (larger = slower); lock time ~ 6 * 2**(ki_shift - kp_shift) samples.
    """
    def __init__(self, angle_width=16, frac_bits=14, kp_shift=4, ki_shift=10, with_csr=True):
        check(angle_width >= 4, "expected angle_width >= 4")
        check(frac_bits >= 0, "expected frac_bits >= 0")
        check(0 <= kp_shift <= 31 and 0 <= ki_shift <= 31, "expected shifts in 0..31")
        self.angle_width = angle_width
        self.frac_bits   = frac_bits
        self.latency     = 1
        W = angle_width + frac_bits + 2
        self.loop_width  = W
        self.sink   = stream.Endpoint(angle_layout(angle_width))      # Raw angle.
        self.source = stream.Endpoint(angle_layout(angle_width))      # Tracked angle.
        self.kp_shift = Signal(5, reset=kp_shift)
        self.ki_shift = Signal(5, reset=ki_shift)
        self.angle_offset = Signal(angle_width)                       # Added to the output.
        self.speed    = Signal((W, True))                             # Integrator (Q.frac_bits).
        self.error    = Signal((angle_width, True))                   # Last phase error.

        # # #

        # Handshake.
        # ----------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Loop: wrapped error -> PI -> angle accumulator.
        # -----------------------------------------------
        theta      = Signal(angle_width + frac_bits)                  # Wrapping accumulator.
        theta_next = Signal(angle_width + frac_bits)
        err        = Signal((angle_width, True))
        self.pi    = LiteDSPPILoop(error_width=W, out_width=W, kp_shift=self.kp_shift,
            ki_shift=self.ki_shift)
        self.comb += [
            err.eq(self.sink.angle - theta[frac_bits:]),              # Modular difference.
            self.pi.error.eq(err << frac_bits),
            self.pi.ce.eq(xfer),
            theta_next.eq(theta + self.pi.out),
            self.speed.eq(self.pi.integral),
        ]
        self.sync += If(xfer, theta.eq(theta_next), self.error.eq(err))

        # Output.
        # -------
        self.sync += If(adv,
            self.source.angle.eq(theta[frac_bits:] + self.angle_offset),
            self.source.valid.eq(self.sink.valid),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._gains = CSRStorage(fields=[
            CSRField("kp_shift", size=5, offset=0, reset=self.kp_shift.reset.value,
                description="Proportional shift (larger = slower)."),
            CSRField("ki_shift", size=5, offset=8, reset=self.ki_shift.reset.value,
                description="Integral shift (larger = slower)."),
        ])
        self._angle_offset = CSRStorage(self.angle_width, name="angle_offset",
            description="Offset added to the tracked angle (alignment / lag compensation).")
        self._speed = CSRStatus(self.loop_width, name="speed",
            description="Tracked speed: angle units per sample, Q.frac_bits.")
        self._error = CSRStatus(self.angle_width, name="error", description="Last phase error.")
        self.comb += [
            self.kp_shift.eq(self._gains.fields.kp_shift),
            self.ki_shift.eq(self._gains.fields.ki_shift),
            self.angle_offset.eq(self._angle_offset.storage),
            self._speed.status.eq(self.speed),
            self._error.status.eq(self.error),
        ]

# Sliding-Mode Observer ----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPSMObserver(LiteXModule):
    """Sensorless sliding-mode back-EMF observer (PMSM, stationary alpha/beta frame).

    From the measured currents (``sink_i``) and applied voltages (``sink_v``), both per-unit
    on ``iq_layout`` and consumed together, a current model per axis
    ``ih += g_v*(v - emf - z) - g_r*ih`` with the sliding term ``z = k_sm*sign(ih - i)`` and
    the low-pass filtered back-EMF ``emf += (z - emf) >> lpf_shift`` reconstructs the back-EMF
    vector; ``source`` is its angle ``atan2(-emf_alpha, emf_beta)`` (CORDIC vectoring), i.e.
    the rotor electrical angle for positive speed (opposite sign at negative speed: resolve
    with the tracker's speed sign). Gains are per-unit: ``g_v = w_b*Ts/L_pu``, ``g_r = R_pu *
    w_b*Ts/L_pu`` (signed Q4.12); ``k_sm`` is the sliding gain magnitude, to be set with the
    operating point at roughly half the back-EMF magnitude (``~0.35*w_pu`` for ``psi_pu =
    0.6``): too small loses the sliding regime, too large adds chatter at low speed. The
    estimate lags the rotor by a constant bounded by the filter phase ``atan2(a*sin(d), 1 -
    a*cos(d))`` (``a = 1 - 2**-lpf_shift``, ``d`` = angle step per sample). Feed the angle to
    :class:`LiteDSPAngleTracker` for a smooth estimate and speed. Latency ``stages + 3``
    (CORDIC).

    Parameters
    ----------
    angle_width : int
        Output angle width (full turn = 2**angle_width).
    gain_width : int
        Width of the signed observer gains.
    gain_frac : int
        Fractional bits of the gains (1.0 = 2**gain_frac).
    stages : int
        CORDIC iterations (defaults to ``data_width``).
    """
    def __init__(self, data_width=16, angle_width=16, gain_width=16, gain_frac=12, stages=None,
        with_csr=True):
        check(data_width >= 4, "expected data_width >= 4")
        check(0 < gain_frac < gain_width, "expected 0 < gain_frac < gain_width")
        if stages is None:
            stages = data_width
        check(stages >= 1, "expected stages >= 1")
        self.data_width  = data_width
        self.angle_width = angle_width
        self.gain_width  = gain_width
        self.gain_frac   = gain_frac
        self.stages      = stages
        EW = data_width + 1                                           # Back-EMF width.
        self.sink_i = stream.Endpoint(iq_layout(data_width))          # (i_alpha, i_beta).
        self.sink_v = stream.Endpoint(iq_layout(data_width))          # (v_alpha, v_beta).
        self.source = stream.Endpoint(angle_layout(angle_width))      # Raw back-EMF angle.
        self.g_v       = Signal((gain_width, True), reset=1 << (gain_frac - 2))   # 0.25.
        self.g_r       = Signal((gain_width, True))
        self.k_sm      = Signal(data_width, reset=1 << (data_width - 3))          # 0.125 pu.
        self.lpf_shift = Signal(4, reset=3)
        self.clear     = Signal()
        self.emf_alpha = Signal((EW, True))
        self.emf_beta  = Signal((EW, True))

        # # #

        # CORDIC (vectoring) on the back-EMF vector, fed with the updated estimate.
        # ------------------------------------------------------------------------
        self.cordic = cordic = LiteDSPCORDIC(data_width=EW, angle_width=angle_width,
            stages=stages, mode="vectoring", with_csr=False)
        self.latency = cordic.latency

        # Handshake: join of the two sinks, paced by the CORDIC.
        # -----------------------------------------------------
        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(cordic.sink.ready),
            self.sink_i.ready.eq(adv & self.sink_v.valid),
            self.sink_v.ready.eq(adv & self.sink_i.valid),
            xfer.eq(self.sink_i.valid & self.sink_v.valid & adv),
            cordic.sink.valid.eq(xfer),
            cordic.sink.first.eq(self.sink_i.first),
            cordic.sink.last.eq(self.sink_i.last),
        ]

        # Observer per axis.
        # ------------------
        emf_next = []
        for i_in, v_in, emf in ((self.sink_i.i, self.sink_v.i, self.emf_alpha),
                                (self.sink_i.q, self.sink_v.q, self.emf_beta)):
            IW = data_width + 2
            ih     = Signal((IW, True))                               # Estimated current.
            err    = Signal((IW + 1, True))
            z      = Signal((data_width + 1, True))
            emf_n  = Signal((EW, True))
            d      = Signal((IW + 2, True))
            pv     = Signal((IW + 2 + gain_width, True))
            pr     = Signal((IW + gain_width, True))
            upd    = Signal((IW + 3 + gain_width, True))
            self.comb += [
                err.eq(ih - i_in),
                z.eq(Mux(err[-1], -self.k_sm, self.k_sm)),
                emf_n.eq(emf + ((z - emf) >> self.lpf_shift)),
                d.eq(v_in - emf - z),
                pv.eq(d*self.g_v),
                pr.eq(ih*self.g_r),
                upd.eq(pv - pr),
            ]
            ih_next = saturated(ih + rounded(upd, gain_frac), IW)
            self.sync += If(self.clear,
                ih.eq(0), emf.eq(0),
            ).Elif(xfer,
                ih.eq(ih_next), emf.eq(emf_n),
            )
            emf_next.append(emf_n)
        self.comb += [
            cordic.sink.x.eq(emf_next[1]),                            # theta = atan2(-e_a, e_b).
            cordic.sink.y.eq(-emf_next[0]),
        ]

        # Output.
        # -------
        self.comb += [
            self.source.valid.eq(cordic.source.valid),
            self.source.first.eq(cordic.source.first),
            self.source.last.eq(cordic.source.last),
            self.source.angle.eq(cordic.source.angle),
            cordic.source.ready.eq(self.source.ready),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        gw, gf = self.gain_width, self.gain_frac
        self._g_v  = CSRStorage(gw, reset=self.g_v.reset.value, name="g_v",
            description=f"Voltage gain w_b*Ts/L_pu (signed Q{gw - gf}.{gf}).")
        self._g_r  = CSRStorage(gw, name="g_r",
            description=f"Resistive gain R_pu*w_b*Ts/L_pu (signed Q{gw - gf}.{gf}).")
        self._k_sm = CSRStorage(self.data_width, reset=self.k_sm.reset.value, name="k_sm",
            description="Sliding gain magnitude (per-unit).")
        self._control = CSRStorage(fields=[
            CSRField("lpf_shift", size=4, offset=0, reset=3, description="Back-EMF low-pass shift."),
            CSRField("clear",     size=1, offset=8, pulse=True, description="Reset the observer state."),
        ])
        self._emf_alpha = CSRStatus(len(self.emf_alpha), name="emf_alpha",
                                    description="Back-EMF alpha.")
        self._emf_beta  = CSRStatus(len(self.emf_beta),  name="emf_beta",
                                    description="Back-EMF beta.")
        self.comb += [
            self.g_v.eq(self._g_v.storage),
            self.g_r.eq(self._g_r.storage),
            self.k_sm.eq(self._k_sm.storage),
            self.lpf_shift.eq(self._control.fields.lpf_shift),
            self.clear.eq(self._control.fields.clear),
            self._emf_alpha.status.eq(self.emf_alpha),
            self._emf_beta.status.eq(self.emf_beta),
        ]
