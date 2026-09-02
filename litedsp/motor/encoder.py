#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Position sensor interfaces: incremental quadrature encoder and 120-degree Hall sensors.

Both decode synchronized, glitch-filtered pins into an electrical angle stream
(``angle_layout``, emitted on a ``sample`` strobe -- typically the PWM ADC trigger -- as a
latest-wins sample) plus direction/speed information for the outer loops.
"""

from functools import reduce
from operator  import or_

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceProcess
from litex.soc.interconnect                  import stream

from litedsp.common import check, angle_layout

# Helpers ------------------------------------------------------------------------------------------

def _synchronized(module, pin, filter_length=1):
    """Two-flop synchronizer + glitch filter: a new level is accepted after ``filter_length``
    identical samples. Returns the filtered signal (``filter_length + 2`` cycles after the pin)."""
    s1, s2, out = Signal(), Signal(), Signal()
    module.sync += [s1.eq(pin), s2.eq(s1)]
    if filter_length == 1:
        module.sync += out.eq(s2)
        return out
    cnt = Signal(max=filter_length)
    module.sync += If(s2 != out,
        If(cnt == filter_length - 1,
            out.eq(s2),
            cnt.eq(0),
        ).Else(
            cnt.eq(cnt + 1),
        ),
    ).Else(
        cnt.eq(0),
    )
    return out

def _angle_source(module, source, angle, sample, overrun, clear):
    """Latest-wins angle stream: ``angle`` is emitted on ``sample``; an unconsumed pending
    sample is overwritten and latches ``overrun``."""
    pending = Signal()
    module.comb += source.valid.eq(pending)
    module.sync += [
        If(sample,
            source.angle.eq(angle),
            pending.eq(1),
        ).Elif(source.ready,
            pending.eq(0),
        ),
        If(clear, overrun.eq(0)).Elif(sample & pending & ~source.ready, overrun.eq(1)),
    ]

# Quadrature Decoder -------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPQuadratureDecoder(LiteXModule):
    """Incremental encoder (A/B/Z) interface: position, direction, speed and electrical angle.

    The A/B pins are synchronized, glitch-filtered (``filter_length`` identical samples) and
    decoded at 4x resolution (every edge is a count); an illegal transition (both bits
    changing) sets the sticky ``error``. ``position`` counts modulo ``counts_per_rev``; the
    electrical position ``epos`` advances by ``pole_pairs`` per count (modulo
    ``counts_per_rev``) so ``angle = epos*angle_scale >> scale_frac + angle_offset`` with
    ``angle_scale = round(2**(angle_width + scale_frac) / counts_per_rev)`` -- a reciprocal
    multiply, exact for power-of-two counts and within one LSB otherwise. The index pulse Z
    (rising edge, when ``index_enable``) zeroes the position and sets ``index_seen``
    (``ev.index`` with ``with_irq=True``; ``ev.error`` for illegal transitions). ``speed`` is
    the signed count over the last ``window`` cycles (M-method). The angle stream is emitted
    on ``sample`` (latest-wins, sticky ``overrun``).

    Parameters
    ----------
    angle_width : int
        Electrical angle width (full turn = 2**angle_width).
    position_width : int
        Position counter width (must hold ``counts_per_rev - 1``).
    speed_width : int
        Width of the signed per-window count.
    filter_length : int
        Glitch filter length in cycles (>= 1).
    scale_frac : int
        Fractional bits of ``angle_scale``.
    """
    def __init__(self, angle_width=16, position_width=16, speed_width=16, filter_length=2,
        scale_frac=16, with_csr=True, with_irq=False):
        check(angle_width >= 2, "expected angle_width >= 2")
        check(position_width >= 2 and speed_width >= 2, "expected position_width, speed_width >= 2")
        check(filter_length >= 1, "expected filter_length >= 1")
        check(scale_frac >= 1, "expected scale_frac >= 1")
        self.angle_width    = angle_width
        self.position_width = position_width
        self.speed_width    = speed_width
        self.filter_length  = filter_length
        self.scale_frac     = scale_frac
        self.latency        = None                                    # Source-only.
        scale_width         = angle_width + scale_frac
        self.a, self.b, self.z = Signal(), Signal(), Signal()         # Encoder pins.
        self.sample          = Signal()                               # Emit the angle now.
        self.source          = stream.Endpoint(angle_layout(angle_width))
        self.counts_per_rev  = Signal(position_width, reset=4096)     # Counts per turn (4x).
        self.pole_pairs      = Signal(8, reset=1)
        self.angle_scale     = Signal(scale_width, reset=(1 << scale_width)//4096)
        self.angle_offset    = Signal(angle_width)                    # Electrical offset.
        self.window          = Signal(24, reset=1 << 16)              # Speed window (cycles).
        self.invert          = Signal()                               # Swap direction.
        self.index_enable    = Signal()                               # Z zeroes the position.
        self.clear           = Signal()                               # Clear sticky flags.
        self.position        = Signal(position_width)                 # Mechanical count.
        self.epos            = Signal(position_width)                 # Electrical count.
        self.direction       = Signal()                               # 1: negative last step.
        self.speed           = Signal((speed_width, True))            # Counts per window.
        self.index_seen      = Signal()
        self.error           = Signal()
        self.overrun         = Signal()

        # # #

        # Pins: synchronize + filter, 4x decode.
        # --------------------------------------
        a_f = _synchronized(self, self.a, filter_length)
        b_f = _synchronized(self, self.b, filter_length)
        z_f = _synchronized(self, self.z, filter_length)
        a_p, b_p, z_p = Signal(), Signal(), Signal()
        self.sync += [a_p.eq(a_f), b_p.eq(b_f), z_p.eq(z_f)]
        step_up   = Signal()   # +1 count.
        step_down = Signal()   # -1 count.
        illegal   = Signal()   # Both bits changed at once.
        fwd_match = Signal()   # Transition along the positive Gray sequence.
        step      = Signal()
        prev, cur = Cat(a_p, b_p), Cat(a_f, b_f)
        # Gray sequence 00 -> 01 -> 11 -> 10 -> 00 is the positive direction.
        fwd = [(0b00, 0b01), (0b01, 0b11), (0b11, 0b10), (0b10, 0b00)]
        self.comb += [
            illegal.eq((prev ^ cur) == 0b11),
            step.eq((prev != cur) & ~illegal),
            fwd_match.eq(reduce(or_, [(prev == p) & (cur == c) for p, c in fwd]) ^ self.invert),
            step_up.eq(step & fwd_match),
            step_down.eq(step & ~fwd_match),
        ]
        index = Signal()
        self.comb += index.eq(z_f & ~z_p & self.index_enable)

        # Position and electrical position (modular counters).
        # ---------------------------------------------------
        cpr_m1 = Signal(position_width)
        self.comb += cpr_m1.eq(self.counts_per_rev - 1)
        epos_up   = Signal(position_width + 1)
        epos_down = Signal((position_width + 1, True))
        self.comb += [
            epos_up.eq(self.epos + self.pole_pairs),
            epos_down.eq(self.epos - self.pole_pairs),
        ]
        self.sync += [
            If(index,
                self.position.eq(0),
                self.epos.eq(0),
            ).Elif(step_up,
                self.position.eq(Mux(self.position == cpr_m1, 0, self.position + 1)),
                self.epos.eq(Mux(epos_up >= self.counts_per_rev, epos_up - self.counts_per_rev, epos_up)),
                self.direction.eq(0),
            ).Elif(step_down,
                self.position.eq(Mux(self.position == 0, cpr_m1, self.position - 1)),
                self.epos.eq(Mux(epos_down < 0, epos_down + self.counts_per_rev, epos_down)),
                self.direction.eq(1),
            ),
            If(self.clear,
                self.error.eq(0),
                self.index_seen.eq(0),
            ).Else(
                If(illegal, self.error.eq(1)),
                If(index,   self.index_seen.eq(1)),
            ),
        ]

        # Angle: reciprocal multiply (registered product) + offset.
        # ---------------------------------------------------------
        angle_full = Signal(position_width + scale_width)
        angle      = Signal(angle_width)
        self.sync += angle_full.eq(self.epos*self.angle_scale)
        self.comb += angle.eq(angle_full[scale_frac:scale_frac + angle_width] + self.angle_offset)

        # Speed: signed count per window.
        # -------------------------------
        win_cnt = Signal(24)
        delta   = Signal((speed_width, True))
        self.sync += If(win_cnt >= self.window - 1,
            win_cnt.eq(0),
            self.speed.eq(delta + Mux(step_up, 1, Mux(step_down, -1, 0))),
            delta.eq(0),
        ).Else(
            win_cnt.eq(win_cnt + 1),
            delta.eq(delta + Mux(step_up, 1, Mux(step_down, -1, 0))),
        )

        # Angle stream.
        # -------------
        _angle_source(self, self.source, angle, self.sample, self.overrun, self.clear)

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev       = EventManager()
        self.ev.index = EventSourceProcess(edge="rising", description="Index (Z) pulse seen.")
        self.ev.error = EventSourceProcess(edge="rising", description="Illegal A/B transition.")
        self.ev.finalize()
        self.comb += [
            self.ev.index.trigger.eq(self.index_seen),
            self.ev.error.trigger.eq(self.error),
        ]

    def add_csr(self):
        self._counts_per_rev = CSRStorage(self.position_width, reset=4096, name="counts_per_rev",
            description="Encoder counts per mechanical turn (4x decoded).")
        self._pole_pairs   = CSRStorage(8, reset=1, name="pole_pairs", description="Motor pole pairs.")
        self._angle_scale  = CSRStorage(len(self.angle_scale), reset=self.angle_scale.reset.value,
            name="angle_scale",
            description=f"round(2**{self.angle_width + self.scale_frac} / counts_per_rev).")
        self._angle_offset = CSRStorage(self.angle_width, name="angle_offset",
            description="Electrical angle offset added to the output (encoder alignment).")
        self._window       = CSRStorage(24, reset=1 << 16, name="window",
            description="Speed measurement window in cycles.")
        self._control = CSRStorage(fields=[
            CSRField("invert",       size=1, offset=0, description="Swap the counting direction."),
            CSRField("index_enable", size=1, offset=1, description="Z pulse zeroes the position."),
            CSRField("clear",        size=1, offset=2, pulse=True, description="Clear error/index/overrun."),
        ])
        self._position = CSRStatus(self.position_width, name="position", description="Mechanical count.")
        self._speed    = CSRStatus(self.speed_width, name="speed", description="Signed counts per window.")
        self._status   = CSRStatus(fields=[
            CSRField("direction",  size=1, offset=0, description="Last step was negative."),
            CSRField("index_seen", size=1, offset=1, description="Index pulse seen since clear."),
            CSRField("error",      size=1, offset=2, description="Illegal transition since clear."),
            CSRField("overrun",    size=1, offset=3, description="An angle sample was not consumed."),
        ])
        self.comb += [
            self.counts_per_rev.eq(self._counts_per_rev.storage),
            self.pole_pairs.eq(self._pole_pairs.storage),
            self.angle_scale.eq(self._angle_scale.storage),
            self.angle_offset.eq(self._angle_offset.storage),
            self.window.eq(self._window.storage),
            self.invert.eq(self._control.fields.invert),
            self.index_enable.eq(self._control.fields.index_enable),
            self.clear.eq(self._control.fields.clear),
            self._position.status.eq(self.position),
            self._speed.status.eq(self.speed),
            self._status.fields.direction.eq(self.direction),
            self._status.fields.index_seen.eq(self.index_seen),
            self._status.fields.error.eq(self.error),
            self._status.fields.overrun.eq(self.overrun),
        ]

# Hall Decoder -------------------------------------------------------------------------------------

HALL_SECTORS = {0b001: 0, 0b011: 1, 0b010: 2, 0b110: 3, 0b100: 4, 0b101: 5}   # 120-degree placement.

@ResetInserter()
class LiteDSPHallDecoder(LiteXModule):
    """Three 120-degree Hall sensors -> sector, direction, speed and (interpolated) angle.

    The synchronized/filtered ``hall`` code selects one of six 60-degree sectors (codes 0
    and 7 set the sticky ``error`` once a valid code has been seen, so idle pins at power-up
    do not flag); ``angle`` is the sector center (``sector*60 + 30``
    degrees electrical, plus ``angle_offset``). With ``interpolate=True`` the time between
    the last two sector edges (``period``, cycles) sets a per-cycle increment ``inc =
    (2**angle_width/6 << 8)/period`` (serial divider, one per edge) and the angle ramps
    from the sector start (or end, when running backwards), clamped at the sector boundary
    until the next edge -- a 60-degree-resolution sensor becomes a smooth angle at constant
    speed. ``direction`` follows the sector sequence; ``speed`` is the signed increment
    (electrical angle units per cycle, Q.8); ``stall`` latches when the edge timer saturates.
    The angle stream is emitted on ``sample`` (latest-wins, sticky ``overrun``).

    Parameters
    ----------
    angle_width : int
        Electrical angle width (full turn = 2**angle_width).
    timer_width : int
        Width of the sector-period timer (cycles between Hall edges).
    interpolate : bool
        Ramp the angle between edges from the measured sector period.
    filter_length : int
        Glitch filter length in cycles (>= 1).
    """
    def __init__(self, angle_width=16, timer_width=24, interpolate=True, filter_length=2,
        with_csr=True, with_irq=False):
        check(angle_width >= 4, "expected angle_width >= 4")
        check(timer_width >= 8, "expected timer_width >= 8")
        check(isinstance(interpolate, bool), "expected interpolate to be a bool")
        check(filter_length >= 1, "expected filter_length >= 1")
        self.angle_width   = angle_width
        self.timer_width   = timer_width
        self.interpolate   = interpolate
        self.filter_length = filter_length
        self.latency       = None                                     # Source-only.
        SECTOR = (1 << angle_width)//6                                # 60 degrees.
        FRAC   = 8
        self.hall         = Signal(3)                                 # Hall pins (h1, h2, h3).
        self.sample       = Signal()
        self.source       = stream.Endpoint(angle_layout(angle_width))
        self.angle_offset = Signal(angle_width)
        self.invert       = Signal()
        self.clear        = Signal()
        self.sector       = Signal(3)                                 # 0..5.
        self.direction    = Signal()                                  # 1: backwards.
        self.period       = Signal(timer_width)                       # Cycles per sector.
        self.speed        = Signal((angle_width + FRAC, True))        # Angle units/cycle, Q.8.
        self.error        = Signal()
        self.stall        = Signal()
        self.overrun      = Signal()

        # # #

        # Pins: synchronize + filter, decode the sector.
        # ----------------------------------------------
        code = Cat(*[_synchronized(self, self.hall[k], filter_length) for k in range(3)])
        sector_new = Signal(3)
        invalid    = Signal()
        self.comb += [
            Case(code, {c: sector_new.eq(s) for c, s in HALL_SECTORS.items()} |
                       {"default": sector_new.eq(self.sector)}),
            invalid.eq((code == 0) | (code == 7)),
        ]
        sector_edge      = Signal()
        forward   = Signal()
        self.comb += [
            sector_edge.eq(~invalid & (sector_new != self.sector)),
            forward.eq((sector_new == Mux(self.sector == 5, 0, self.sector + 1)) ^ self.invert),
        ]

        # Sector period timer (saturating) and edge handling.
        # ---------------------------------------------------
        timer = Signal(timer_width)
        tmax  = (1 << timer_width) - 1
        armed = Signal()                                              # A valid code was seen.
        self.sync += [
            If(~invalid, armed.eq(1)),
            If(sector_edge,
                self.sector.eq(sector_new),
                self.direction.eq(~forward),
                self.period.eq(timer),
                timer.eq(1),
            ).Elif(timer != tmax,
                timer.eq(timer + 1),
            ),
            If(self.clear,
                self.error.eq(0),
                self.stall.eq(0),
            ).Else(
                If(invalid & armed, self.error.eq(1)),
                If(timer == tmax,   self.stall.eq(1)),
            ),
        ]

        # Angle: sector center, or interpolated ramp from the measured period.
        # --------------------------------------------------------------------
        base_lut = Array([Constant(k*SECTOR, angle_width) for k in range(6)])
        base     = Signal(angle_width)
        angle    = Signal(angle_width)
        self.comb += base.eq(base_lut[self.sector])
        if not interpolate:
            self.comb += angle.eq(base + SECTOR//2 + self.angle_offset)
        else:
            # Serial restoring divider: inc = (SECTOR << FRAC) / period, one per edge
            # (NUM_W cycles, far shorter than any sector period).
            NUM_W    = angle_width + FRAC
            NUM      = SECTOR << FRAC
            num_bits = Array([Constant((NUM >> i) & 1, 1) for i in range(NUM_W)])
            div_i    = Signal(max=NUM_W + 1)                          # Bits left (NUM_W .. 0).
            busy     = Signal()
            quot     = Signal(NUM_W)
            rem      = Signal(timer_width + 1)
            rem_sh   = Signal(timer_width + 1)
            num_bit  = Signal()
            inc      = Signal(NUM_W)                                  # Q.FRAC angle per cycle.
            self.comb += [
                num_bit.eq(num_bits[div_i - 1]),
                rem_sh.eq(Cat(num_bit, rem[:-1])),                    # (rem << 1) | bit.
            ]
            self.sync += If(sector_edge & (timer != 0),
                busy.eq(1), div_i.eq(NUM_W), quot.eq(0), rem.eq(0),
            ).Elif(busy,
                If(div_i == 0,
                    busy.eq(0),
                    inc.eq(quot),
                ).Else(
                    div_i.eq(div_i - 1),
                    If(rem_sh >= self.period,
                        rem.eq(rem_sh - self.period),
                        quot.eq(Cat(Constant(1, 1), quot[:-1])),
                    ).Else(
                        rem.eq(rem_sh),
                        quot.eq(Cat(Constant(0, 1), quot[:-1])),
                    ),
                ),
            )
            frac = Signal(NUM_W)                                      # Position inside the sector, Q.FRAC.
            lim  = Constant((SECTOR - 1) << FRAC, NUM_W)
            self.sync += If(sector_edge,
                frac.eq(0),
            ).Elif((frac + inc) < lim,
                frac.eq(frac + inc),
            ).Else(
                frac.eq(lim),
            )
            pos = Signal(angle_width)
            self.comb += [
                pos.eq(frac[FRAC:]),
                angle.eq(Mux(self.direction, base + SECTOR - 1 - pos, base + pos) + self.angle_offset),
                self.speed.eq(Mux(self.direction, -inc, inc)),
            ]

        # Angle stream.
        # -------------
        _angle_source(self, self.source, angle, self.sample, self.overrun, self.clear)

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev       = EventManager()
        self.ev.error = EventSourceProcess(edge="rising", description="Invalid Hall code (0 or 7).")
        self.ev.stall = EventSourceProcess(edge="rising", description="Sector timer saturated (rotor stalled).")
        self.ev.finalize()
        self.comb += [self.ev.error.trigger.eq(self.error), self.ev.stall.trigger.eq(self.stall)]

    def add_csr(self):
        self._angle_offset = CSRStorage(self.angle_width, name="angle_offset",
            description="Electrical angle offset added to the output (sensor alignment).")
        self._control = CSRStorage(fields=[
            CSRField("invert", size=1, offset=0, description="Swap the direction convention."),
            CSRField("clear",  size=1, offset=1, pulse=True, description="Clear error/stall/overrun."),
        ])
        self._period = CSRStatus(self.timer_width, name="period", description="Cycles per sector (last edge).")
        self._speed  = CSRStatus(len(self.speed), name="speed", description="Signed angle units per cycle (Q.8).")
        self._status = CSRStatus(fields=[
            CSRField("sector",    size=3, offset=0, description="Current sector (0..5)."),
            CSRField("direction", size=1, offset=3, description="Running backwards."),
            CSRField("error",     size=1, offset=4, description="Invalid Hall code since clear."),
            CSRField("stall",     size=1, offset=5, description="Sector timer saturated since clear."),
            CSRField("overrun",   size=1, offset=6, description="An angle sample was not consumed."),
        ])
        self.comb += [
            self.angle_offset.eq(self._angle_offset.storage),
            self.invert.eq(self._control.fields.invert),
            self.clear.eq(self._control.fields.clear),
            self._period.status.eq(self.period),
            self._speed.status.eq(self.speed),
            self._status.fields.sector.eq(self.sector),
            self._status.fields.direction.eq(self.direction),
            self._status.fields.error.eq(self.error),
            self._status.fields.stall.eq(self.stall),
            self._status.fields.overrun.eq(self.overrun),
        ]
