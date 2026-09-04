#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceProcess
from litex.soc.interconnect                  import stream

from litedsp.common import check, abc_layout, rounded

# Three-Phase PWM Generator ------------------------------------------------------------------------

@ResetInserter()
class LiteDSPPWM(LiteXModule):
    """Center-aligned three-phase PWM with dead time, fault latch and ADC trigger (sink-only).

    A triangular carrier counts 0 -> ``period`` -> 0 (``2*period`` cycles per PWM period,
    counting up from reset). ``sink`` (three signed duties, ``-1.0..+1.0`` = 0..100 %) is
    accepted once per period, on the carrier valley (``count == 0`` at the end of the
    down-count) -- so a control loop feeding this block runs at exactly the PWM rate, paced by
    backpressure. Accepted duties are converted to compare values ``cmp = round(period*(duty
    + 1)/2)`` by one time-shared multiplier and applied at the *next* valley (double
    buffering: glitch-free, one period of latency); if no sample is offered in a window the
    previous duties are held and the sticky ``missed`` flag is set.

    ``pwm_h[k]`` is high while ``count < cmp[k]`` (``2*cmp - 1`` cycles centered on the
    valley), ``pwm_l[k]`` is its complement; on every edge both outputs stay low for
    ``dead_time`` cycles. ``enable`` gates the outputs; a ``fault``
    input (over-current comparator, driver
    fault) switches all six outputs off within one cycle and latches ``fault_latched`` until
    ``fault_clear`` (with ``with_irq=True``: ``ev.fault``; ``ev.period`` fires every valley
    for a CPU-driven loop). ``trigger`` pulses when the carrier passes ``trigger_count`` on the
    ``trigger_direction`` slope (0: at/after the valley while counting down, 1: while counting
    up) -- the sample point for shunt current measurement in the zero vector.

    Parameters
    ----------
    period_width : int
        Width of the carrier counter / ``period`` control (period >= 4 cycles).
    dead_time_width : int
        Width of the ``dead_time`` control (cycles, up to 2**width - 1).
    """
    def __init__(self, data_width=16, period_width=16, dead_time_width=8, with_csr=True,
        with_irq=False):
        check(data_width >= 4, "expected data_width >= 4")
        check(period_width >= 4, "expected period_width >= 4")
        check(dead_time_width >= 1, "expected dead_time_width >= 1")
        self.data_width      = data_width
        self.period_width    = period_width
        self.dead_time_width = dead_time_width
        self.latency         = None                                  # Sink-only.
        self.sink  = stream.Endpoint(abc_layout(data_width))         # Duties, one per period.
        self.pwm_h = Signal(3)                                       # High-side gate signals.
        self.pwm_l = Signal(3)                                       # Low-side gate signals.
        self.trigger = Signal()                                      # ADC sample-point pulse.
        self.fault   = Signal()                                      # Fault input (level).
        self.period            = Signal(period_width, reset=1000)    # Half PWM period (cycles).
        self.dead_time         = Signal(dead_time_width)             # Dead time (cycles).
        self.enable            = Signal()                            # Outputs enabled.
        self.fault_clear       = Signal()                            # Clear the fault latch.
        self.missed_clear      = Signal()                            # Clear the missed flag.
        self.trigger_count     = Signal(period_width)                # Trigger carrier value.
        self.trigger_direction = Signal()                            # 0: counting down, 1: up.
        self.fault_latched     = Signal()                            # Outputs forced off.
        self.missed            = Signal()                            # A window had no sample.
        self.count             = Signal(period_width)                # Carrier (status).

        # # #

        # Carrier: 0 -> period -> 0 (peak and valley each last one cycle; counts up from reset
        # so the first acceptance window opens after one full period).
        # -------------------------------------------------------------------------------------
        up     = Signal(reset=1)
        valley = Signal()
        self.comb += valley.eq((self.count == 0) & ~up)
        self.sync += If(up,
            If(self.count >= self.period,
                up.eq(0),
                self.count.eq(self.count - 1),
            ).Else(
                self.count.eq(self.count + 1),
            ),
        ).Else(
            If(valley,
                up.eq(1),
                self.count.eq(1),
            ).Else(
                self.count.eq(self.count - 1),
            ),
        )

        # Duty acceptance (one window per period) and compare double buffer.
        # ------------------------------------------------------------------
        accept  = Signal()
        duty_u  = Array(Signal(data_width + 1) for _ in range(3))   # duty + 1.0 (unsigned).
        offset  = 1 << (data_width - 1)
        self.comb += [
            self.sink.ready.eq(valley),
            accept.eq(valley & self.sink.valid),
        ]
        self.sync += [
            If(accept,
                duty_u[0].eq(self.sink.a + offset),
                duty_u[1].eq(self.sink.b + offset),
                duty_u[2].eq(self.sink.c + offset),
            ),
            If(self.missed_clear,
                self.missed.eq(0),
            ).Elif(valley & ~self.sink.valid & self.enable,
                self.missed.eq(1),
            ),
        ]
        # One multiplier, three products over the cycles following the acceptance.
        mul_busy   = Signal()
        mul_idx    = Signal(2)
        prod       = Signal(period_width + data_width + 1)
        prod_valid = Signal()
        prod_idx   = Signal(2)
        cmp_val    = Signal(period_width)                           # round(prod / 2**dw).
        cmp_shadow = [Signal(period_width) for _ in range(3)]
        cmp        = [Signal(period_width) for _ in range(3)]
        # Per-index writes (a variable-index Array write in a clocked process makes Migen emit
        # a blocking temporary that Verilator rejects); the Array read above lowers to a mux.
        self.comb += cmp_val.eq(rounded(prod, data_width))
        self.sync += [
            If(accept,
                mul_busy.eq(1),
                mul_idx.eq(0),
            ).Elif(mul_busy,
                If(mul_idx == 2, mul_busy.eq(0)).Else(mul_idx.eq(mul_idx + 1)),
            ),
            prod.eq(self.period*duty_u[mul_idx]),
            prod_valid.eq(mul_busy),
            prod_idx.eq(mul_idx),
            *[If(prod_valid & (prod_idx == k), cmp_shadow[k].eq(cmp_val)) for k in range(3)],
            If(valley, *[cmp[k].eq(cmp_shadow[k]) for k in range(3)]),
        ]

        # Gate signals: raw compare, dead time, enable/fault gating.
        # ---------------------------------------------------------
        active = Signal()
        self.comb += active.eq(self.enable & ~self.fault_latched)
        for k in range(3):
            raw, raw_r, raw_prev = Signal(), Signal(), Signal()
            edge, dt_cnt, dt_next = Signal(), Signal(dead_time_width), Signal(dead_time_width)
            self.comb += [
                raw.eq(self.count < cmp[k]),
                edge.eq(raw_r != raw_prev),
                dt_next.eq(Mux(edge, self.dead_time, Mux(dt_cnt != 0, dt_cnt - 1, 0))),
            ]
            self.sync += [
                raw_r.eq(raw),
                raw_prev.eq(raw_r),
                dt_cnt.eq(dt_next),
                self.pwm_h[k].eq( raw_r & active & (dt_next == 0)),
                self.pwm_l[k].eq(~raw_r & active & (dt_next == 0)),
            ]

        # Fault latch and trigger.
        # ------------------------
        self.sync += [
            If(self.fault,
                self.fault_latched.eq(1),
            ).Elif(self.fault_clear,
                self.fault_latched.eq(0),
            ),
            self.trigger.eq((self.count == self.trigger_count) & (up == self.trigger_direction)),
        ]

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev        = EventManager()
        self.ev.fault  = EventSourceProcess(edge="rising",
                                            description="Fault latched (outputs off).")
        self.ev.period = EventSourceProcess(edge="rising",
                                            description="Carrier valley (new PWM period).")
        self.ev.finalize()
        self.comb += [
            self.ev.fault.trigger.eq(self.fault_latched),
            self.ev.period.trigger.eq(self.count == 0),
        ]

    def add_csr(self):
        self._period    = CSRStorage(self.period_width, reset=1000, name="period",
            description="Half PWM period in cycles (carrier peak); PWM period = 2*period.")
        self._dead_time = CSRStorage(self.dead_time_width, name="dead_time",
            description="Dead time in cycles inserted at every gate-signal edge.")
        self._control = CSRStorage(fields=[
            CSRField("enable",       size=1, offset=0, description="Enable the gate outputs."),
            CSRField("fault_clear",  size=1, offset=1, pulse=True, description="Clear the fault latch."),
            CSRField("missed_clear", size=1, offset=2, pulse=True, description="Clear the missed flag."),
        ])
        self._trigger = CSRStorage(fields=[
            CSRField("count",     size=self.period_width, offset=0,
                description="Carrier value at which the ADC trigger pulses."),
            CSRField("direction", size=1, offset=self.period_width, description="Carrier counting direction.", values=[
                ("``0b0``", "Counting down / valley side."),
                ("``0b1``", "Counting up / peak side."),
            ]),
        ])
        self._status = CSRStatus(fields=[
            CSRField("fault_latched", size=1, offset=0, description="Outputs forced off by a fault."),
            CSRField("missed",        size=1, offset=1, description="A PWM window had no duty sample."),
        ])
        self._count = CSRStatus(self.period_width, name="count", description="Carrier counter.")
        self.comb += [
            self.period.eq(self._period.storage),
            self.dead_time.eq(self._dead_time.storage),
            self.enable.eq(self._control.fields.enable),
            self.fault_clear.eq(self._control.fields.fault_clear),
            self.missed_clear.eq(self._control.fields.missed_clear),
            self.trigger_count.eq(self._trigger.fields.count),
            self.trigger_direction.eq(self._trigger.fields.direction),
            self._status.fields.fault_latched.eq(self.fault_latched),
            self._status.fields.missed.eq(self.missed),
            self._count.status.eq(self.count),
        ]
