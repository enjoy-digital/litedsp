#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Proportional-integral regulators for motor control (current / speed loops).

:class:`LiteDSPPIController` is a stream PI with multiplier gains (runtime Q4.12 ``kp``/``ki``),
a symmetric output limit and integrator anti-windup; :class:`LiteDSPDQController` runs two of
them in lockstep on a d/q current vector with an optional cross-coupling decoupling
feed-forward. Unlike :class:`~litedsp.control.LiteDSPPILoop` (shift gains, no ports, used inside
the RF tracking loops) these are complete, CSR-controlled stream blocks whose state advances
once per accepted sample, so the trajectory is handshake-invariant and bit-exact against the
golden models under backpressure.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, real_layout, iq_layout, rounded, saturated, scaled

# Constants ----------------------------------------------------------------------------------------

ANTI_WINDUP = ("conditional", "clamp", "none")

# PI Controller ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPIController(LiteXModule):
    """PI regulator on a real stream: ``u = clamp(kp*e + integral + feedforward, +/-limit)``.

    Per accepted measurement ``y``: ``e = setpoint - y``; the output uses the current
    integrator (``integral += ki*e`` afterwards, as synchronous hardware does), is rounded
    once from the ``gain_frac`` domain and clamped to ``+/-limit``. Gains are signed
    Q(gain_width-gain_frac).gain_frac (Q4.12 by default: 1.0 = 4096); ``limit`` is a positive
    magnitude (reset: full scale). Anti-windup: ``"conditional"`` stops integrating while the
    output is clamped in the direction of the error (integrator never winds up, immediate
    recovery), ``"clamp"`` only bounds the integrator to ``+/-limit``, ``"none"`` lets it
    wrap (for reference only). ``open_loop`` forwards ``feedforward`` (clamped) and holds the
    integrator at zero (bring-up); ``clear`` zeroes the integrator; ``saturated`` is a
    sticky clamp flag. With ``setpoint_stream=True`` the setpoint arrives on ``sink_ref``
    (joined with ``sink``) instead of the ``setpoint`` control. Fixed 1-cycle latency.

    Parameters
    ----------
    gain_width : int
        Width of the signed ``kp``/``ki`` gains.
    gain_frac : int
        Fractional bits of the gains (1.0 = 2**gain_frac); must be < gain_width.
    anti_windup : str
        ``"conditional"`` (default), ``"clamp"`` or ``"none"``.
    setpoint_stream : bool
        Take the setpoint from a ``sink_ref`` stream (sample-aligned join) instead of a control.
    """
    def __init__(self, data_width=16, gain_width=16, gain_frac=12, anti_windup="conditional",
        setpoint_stream=False, with_csr=True):
        check(data_width >= 4, "expected data_width >= 4")
        check(0 < gain_frac < gain_width, "expected 0 < gain_frac < gain_width")
        check(anti_windup in ANTI_WINDUP, f"expected anti_windup in {ANTI_WINDUP}")
        check(isinstance(setpoint_stream, bool), "expected setpoint_stream to be a bool")
        self.data_width      = data_width
        self.gain_width      = gain_width
        self.gain_frac       = gain_frac
        self.anti_windup     = anti_windup
        self.setpoint_stream = setpoint_stream
        self.latency         = 1
        acc_width            = data_width + gain_frac + 2
        self.acc_width       = acc_width
        self.sink   = stream.Endpoint(real_layout(data_width))               # Measurement y.
        self.source = stream.Endpoint(real_layout(data_width))               # Command u.
        if setpoint_stream:
            self.sink_ref = stream.Endpoint(real_layout(data_width))         # Setpoint stream.
        self.setpoint    = Signal((data_width, True))                        # Setpoint (control).
        self.kp          = Signal((gain_width, True), reset=1 << gain_frac)  # Proportional gain.
        self.ki          = Signal((gain_width, True))                        # Integral gain/sample.
        self.limit       = Signal((data_width, True), reset=(1 << (data_width - 1)) - 1)  # |u| max.
        self.feedforward = Signal((data_width, True))                        # Added to the output.
        self.open_loop   = Signal()                                          # u = feedforward.
        self.clear       = Signal()                                          # Zero the integrator.
        self.clear_sat   = Signal()                                          # Clear sticky flag.
        self.integral    = Signal((acc_width, True))                         # Integrator (Q.gain_frac).
        self.saturated   = Signal()                                          # Sticky clamp flag.

        # # #

        # Handshake (join with the setpoint stream when present).
        # -------------------------------------------------------
        adv  = Signal()  # Output slot free or being consumed.
        xfer = Signal()  # A measurement (and setpoint) is consumed this beat.
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        if setpoint_stream:
            self.comb += [
                self.sink.ready.eq(adv & self.sink_ref.valid),
                self.sink_ref.ready.eq(adv & self.sink.valid),
                xfer.eq(self.sink.valid & self.sink_ref.valid & adv),
            ]
            setpoint = self.sink_ref.data
        else:
            self.comb += [self.sink.ready.eq(adv), xfer.eq(self.sink.valid & adv)]
            setpoint = self.setpoint

        # Error, products (explicitly sized: see litedsp/level/gain.py).
        # ---------------------------------------------------------------
        PW      = data_width + 1 + gain_width
        e       = Signal((data_width + 1, True))
        p_full  = Signal((PW, True))
        i_step  = Signal((PW, True))
        self.comb += [
            e.eq(setpoint - self.sink.data),
            p_full.eq(e*self.kp),
            i_step.eq(e*self.ki),
        ]

        # Output: P + I(old) + feedforward, rounded from the gain_frac domain, clamped.
        # ---------------------------------------------------------------------------
        UW     = PW + 3
        u_full = Signal((UW, True))
        u_r    = Signal((UW - gain_frac, True))
        u_sel  = Signal((UW - gain_frac, True))
        sat_hi = Signal()
        sat_lo = Signal()
        u      = Signal((data_width, True))
        self.comb += [
            u_full.eq(p_full + self.integral + (self.feedforward << gain_frac)),
            u_r.eq(rounded(u_full, gain_frac)),
            u_sel.eq(Mux(self.open_loop, self.feedforward, u_r)),
            sat_hi.eq(u_sel > self.limit),
            sat_lo.eq(u_sel < -self.limit),
            u.eq(Mux(sat_hi, self.limit, Mux(sat_lo, -self.limit, u_sel))),
        ]

        # Integrator with anti-windup (advances only on accepted samples).
        # ----------------------------------------------------------------
        SW      = max(acc_width, PW) + 1
        acc_sum = Signal((SW, True))
        lim_acc = Signal((SW, True))
        acc_nxt = Signal((acc_width, True))
        self.comb += [
            acc_sum.eq(self.integral + i_step),
            lim_acc.eq(self.limit << gain_frac),
        ]
        if anti_windup == "none":
            self.comb += acc_nxt.eq(acc_sum)                         # Wraps (reference only).
        else:
            self.comb += acc_nxt.eq(Mux(acc_sum > lim_acc, lim_acc,
                                    Mux(acc_sum < -lim_acc, -lim_acc, acc_sum)))
        hold = Signal()                                              # Skip this integration step.
        if anti_windup == "conditional":
            self.comb += hold.eq((sat_hi & (e > 0)) | (sat_lo & (e < 0)))
        self.sync += [
            If(self.clear | self.open_loop,
                self.integral.eq(0),
            ).Elif(xfer & ~hold,
                self.integral.eq(acc_nxt),
            ),
            If(self.clear_sat,
                self.saturated.eq(0),
            ).Elif(xfer & (sat_hi | sat_lo),
                self.saturated.eq(1),
            ),
        ]

        # Output register.
        # ----------------
        self.sync += If(adv,
            self.source.data.eq(u),
            self.source.valid.eq(xfer),
            self.source.first.eq(self.sink.first),
            self.source.last.eq(self.sink.last),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        dw, gw = self.data_width, self.gain_width
        if not self.setpoint_stream:
            self._setpoint = CSRStorage(dw, name="setpoint", description="Setpoint (signed, per-unit).")
            self.comb += self.setpoint.eq(self._setpoint.storage)
        self._kp          = CSRStorage(gw, reset=1 << self.gain_frac, name="kp",
            description=f"Proportional gain (signed Q{gw - self.gain_frac}.{self.gain_frac}).")
        self._ki          = CSRStorage(gw, name="ki",
            description=f"Integral gain per sample (signed Q{gw - self.gain_frac}.{self.gain_frac}).")
        self._limit       = CSRStorage(dw, reset=(1 << (dw - 1)) - 1, name="limit",
            description="Output magnitude limit (positive, per-unit).")
        self._feedforward = CSRStorage(dw, name="feedforward",
            description="Feed-forward term added to the output (the open-loop command).")
        self._control = CSRStorage(fields=[
            CSRField("open_loop", size=1, offset=0, description="Output = feedforward; integrator held at 0."),
            CSRField("clear",     size=1, offset=1, pulse=True, description="Zero the integrator."),
            CSRField("clear_sat", size=1, offset=2, pulse=True, description="Clear the saturation flag."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturated", size=1, description="Output clamped since the last clear."),
        ])
        self._integral = CSRStatus(self.acc_width, name="integral",
            description="Integrator state (Q.gain_frac).")
        self.comb += [
            self.kp.eq(self._kp.storage),
            self.ki.eq(self._ki.storage),
            self.limit.eq(self._limit.storage),
            self.feedforward.eq(self._feedforward.storage),
            self.open_loop.eq(self._control.fields.open_loop),
            self.clear.eq(self._control.fields.clear),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.saturated.eq(self.saturated),
            self._integral.status.eq(self.integral),
        ]

# DQ Current Controller ----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDQController(LiteXModule):
    """Two lock-stepped PI regulators on a d/q current vector -> d/q voltage command.

    ``sink`` carries the measured ``(i_d, i_q)`` on ``iq_layout`` (i = d, q = q), ``source``
    the voltage command ``(v_d, v_q)``. Each axis is a :class:`LiteDSPPIController` with its
    own setpoint and gains and a shared ``limit``. ``open_loop`` forwards ``voltage_d/q``
    (the bring-up vector). With ``decoupling=True`` the PMSM cross-coupling terms are added as
    feed-forward from the per-unit ``speed`` input (electrical, 1.0 = base speed) and the
    ``l_pu``/``psi_pu`` constants: ``ff_d = -w*L*i_q`` and ``ff_q = w*(L*i_d + psi)`` with
    ``L_pu = w_b*L*I_b/V_b`` and ``psi_pu = w_b*psi/V_b`` (one extra registered stage).
    Latency 1 (2 with decoupling).

    Parameters
    ----------
    gain_width : int
        Width of the signed gains.
    gain_frac : int
        Fractional bits of the gains (1.0 = 2**gain_frac).
    anti_windup : str
        Integrator anti-windup of both regulators: ``"conditional"``, ``"clamp"`` or ``"none"``.
    decoupling : bool
        Add the speed-dependent cross-coupling feed-forward (needs ``speed``, ``l_pu``, ``psi_pu``).
    """
    def __init__(self, data_width=16, gain_width=16, gain_frac=12, anti_windup="conditional",
        decoupling=False, with_csr=True):
        check(isinstance(decoupling, bool), "expected decoupling to be a bool")
        self.data_width = data_width
        self.gain_width = gain_width
        self.gain_frac  = gain_frac
        self.decoupling = decoupling
        self.latency    = 2 if decoupling else 1
        self.sink   = stream.Endpoint(iq_layout(data_width))      # Measured (i_d, i_q).
        self.source = stream.Endpoint(iq_layout(data_width))      # Command (v_d, v_q).
        self.setpoint_d = Signal((data_width, True))
        self.setpoint_q = Signal((data_width, True))
        self.kp_d = Signal((gain_width, True), reset=1 << gain_frac)
        self.ki_d = Signal((gain_width, True))
        self.kp_q = Signal((gain_width, True), reset=1 << gain_frac)
        self.ki_q = Signal((gain_width, True))
        self.limit     = Signal((data_width, True), reset=(1 << (data_width - 1)) - 1)
        self.voltage_d = Signal((data_width, True))               # Open-loop / bring-up vector.
        self.voltage_q = Signal((data_width, True))
        self.open_loop = Signal()
        self.clear     = Signal()
        self.clear_sat = Signal()
        self.saturated = Signal(2)                                # Sticky clamp flags (d, q).
        self.speed     = Signal((data_width, True))               # Per-unit electrical speed.
        self.l_pu      = Signal((data_width, True))               # Per-unit inductance (w_b*L*I_b/V_b).
        self.psi_pu    = Signal((data_width, True))               # Per-unit flux linkage (w_b*psi/V_b).

        # # #

        # Submodules.
        # -----------
        self.pi_d = LiteDSPPIController(data_width=data_width, gain_width=gain_width,
            gain_frac=gain_frac, anti_windup=anti_windup, with_csr=False)
        self.pi_q = LiteDSPPIController(data_width=data_width, gain_width=gain_width,
            gain_frac=gain_frac, anti_windup=anti_windup, with_csr=False)
        for pi, sp, kp, ki in ((self.pi_d, self.setpoint_d, self.kp_d, self.ki_d),
                               (self.pi_q, self.setpoint_q, self.kp_q, self.ki_q)):
            self.comb += [
                pi.setpoint.eq(sp), pi.kp.eq(kp), pi.ki.eq(ki), pi.limit.eq(self.limit),
                pi.open_loop.eq(self.open_loop), pi.clear.eq(self.clear),
                pi.clear_sat.eq(self.clear_sat),
            ]
        self.comb += self.saturated.eq(Cat(self.pi_d.saturated, self.pi_q.saturated))

        # Input stage: direct, or one registered stage computing the decoupling terms.
        # ---------------------------------------------------------------------------
        ff_d = Signal((data_width, True))
        ff_q = Signal((data_width, True))
        if not decoupling:
            in_valid, in_first, in_last, in_d, in_q = (self.sink.valid, self.sink.first,
                self.sink.last, self.sink.i, self.sink.q)
            self.comb += self.sink.ready.eq(self.pi_d.sink.ready & self.pi_q.sink.ready)
        else:
            adv0     = Signal()
            in_valid = Signal()
            in_first = Signal()
            in_last  = Signal()
            in_d     = Signal((data_width, True))
            in_q     = Signal((data_width, True))
            shift    = data_width - 1
            t_d_full = Signal((2*data_width, True))            # L * i_d.
            t_q_full = Signal((2*data_width, True))            # L * i_q.
            self.comb += [
                t_d_full.eq(self.l_pu*self.sink.i),
                t_q_full.eq(self.l_pu*self.sink.q),
            ]
            t_d, _ = scaled(t_d_full, shift, data_width)
            t_q, _ = scaled(t_q_full, shift, data_width)
            flux   = Signal((data_width + 1, True))
            self.comb += flux.eq(t_d + self.psi_pu)
            flux_s = saturated(flux, data_width)
            w_q_full = Signal((2*data_width, True))            # w * (L * i_q).
            w_d_full = Signal((2*data_width, True))            # w * (L * i_d + psi).
            self.comb += [
                w_q_full.eq(self.speed*t_q),
                w_d_full.eq(self.speed*flux_s),
            ]
            wq, _ = scaled(w_q_full, shift, data_width)
            wd, _ = scaled(w_d_full, shift, data_width)
            self.comb += [
                adv0.eq(~in_valid | (self.pi_d.sink.ready & self.pi_q.sink.ready)),
                self.sink.ready.eq(adv0),
            ]
            self.sync += If(adv0,
                in_valid.eq(self.sink.valid),
                in_first.eq(self.sink.first),
                in_last.eq(self.sink.last),
                in_d.eq(self.sink.i),
                in_q.eq(self.sink.q),
                ff_d.eq(-wq),
                ff_q.eq(wd),
            )

        # Datapath: lockstep regulators, joined source.
        # ---------------------------------------------
        self.comb += [
            self.pi_d.feedforward.eq(Mux(self.open_loop, self.voltage_d, ff_d)),
            self.pi_q.feedforward.eq(Mux(self.open_loop, self.voltage_q, ff_q)),
        ]
        for pi, data in ((self.pi_d, in_d), (self.pi_q, in_q)):
            self.comb += [
                pi.sink.valid.eq(in_valid),
                pi.sink.first.eq(in_first),
                pi.sink.last.eq(in_last),
                pi.sink.data.eq(data),
                pi.source.ready.eq(self.source.ready),
            ]
        self.comb += [
            self.source.valid.eq(self.pi_d.source.valid & self.pi_q.source.valid),
            self.source.first.eq(self.pi_d.source.first),
            self.source.last.eq(self.pi_d.source.last),
            self.source.i.eq(self.pi_d.source.data),
            self.source.q.eq(self.pi_q.source.data),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        dw, gw, gf = self.data_width, self.gain_width, self.gain_frac
        qfmt = f"signed Q{gw - gf}.{gf}"
        self._setpoint_d = CSRStorage(dw, name="setpoint_d", description="d-axis current setpoint (per-unit).")
        self._setpoint_q = CSRStorage(dw, name="setpoint_q", description="q-axis current setpoint (per-unit).")
        self._kp_d = CSRStorage(gw, reset=1 << gf, name="kp_d", description=f"d-axis proportional gain ({qfmt}).")
        self._ki_d = CSRStorage(gw, name="ki_d", description=f"d-axis integral gain per sample ({qfmt}).")
        self._kp_q = CSRStorage(gw, reset=1 << gf, name="kp_q", description=f"q-axis proportional gain ({qfmt}).")
        self._ki_q = CSRStorage(gw, name="ki_q", description=f"q-axis integral gain per sample ({qfmt}).")
        self._limit     = CSRStorage(dw, reset=(1 << (dw - 1)) - 1, name="limit",
            description="Voltage magnitude limit per axis (positive, per-unit).")
        self._voltage_d = CSRStorage(dw, name="voltage_d", description="Open-loop d voltage (bring-up).")
        self._voltage_q = CSRStorage(dw, name="voltage_q", description="Open-loop q voltage (bring-up).")
        self._control = CSRStorage(fields=[
            CSRField("open_loop", size=1, offset=0, description="Output = voltage_d/q; integrators held at 0."),
            CSRField("clear",     size=1, offset=1, pulse=True, description="Zero both integrators."),
            CSRField("clear_sat", size=1, offset=2, pulse=True, description="Clear the saturation flags."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("saturated_d", size=1, offset=0, description="d output clamped since the last clear."),
            CSRField("saturated_q", size=1, offset=1, description="q output clamped since the last clear."),
        ])
        self._integral_d = CSRStatus(self.pi_d.acc_width, name="integral_d", description="d integrator (Q.gain_frac).")
        self._integral_q = CSRStatus(self.pi_q.acc_width, name="integral_q", description="q integrator (Q.gain_frac).")
        self.comb += [
            self.setpoint_d.eq(self._setpoint_d.storage), self.setpoint_q.eq(self._setpoint_q.storage),
            self.kp_d.eq(self._kp_d.storage), self.ki_d.eq(self._ki_d.storage),
            self.kp_q.eq(self._kp_q.storage), self.ki_q.eq(self._ki_q.storage),
            self.limit.eq(self._limit.storage),
            self.voltage_d.eq(self._voltage_d.storage), self.voltage_q.eq(self._voltage_q.storage),
            self.open_loop.eq(self._control.fields.open_loop),
            self.clear.eq(self._control.fields.clear),
            self.clear_sat.eq(self._control.fields.clear_sat),
            self._status.fields.saturated_d.eq(self.saturated[0]),
            self._status.fields.saturated_q.eq(self.saturated[1]),
            self._integral_d.status.eq(self.pi_d.integral),
            self._integral_q.status.eq(self.pi_q.integral),
        ]
        if self.decoupling:
            self._l_pu   = CSRStorage(dw, name="l_pu",   description="Per-unit inductance w_b*L*I_b/V_b (Q1.(N-1)).")
            self._psi_pu = CSRStorage(dw, name="psi_pu", description="Per-unit flux linkage w_b*psi/V_b (Q1.(N-1)).")
            self.comb += [self.l_pu.eq(self._l_pu.storage), self.psi_pu.eq(self._psi_pu.storage)]
