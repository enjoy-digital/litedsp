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

from litedsp.common import check, iq_layout, scaled

# Automatic Gain Control ---------------------------------------------------------------------------

@ResetInserter()
class LiteDSPAGC(LiteXModule):
    """Automatic gain control: drives |output| toward ``target``.

    Estimates the input magnitude (alpha-max-beta-min), integrates the error into a gain
    (``gain += (target - |x|) >> mu``, clamped to ``[0, gain_max]``), and applies it
    (round + saturate). ``mu`` sets the loop time constant. Gain is Q?.``gain_frac``.
    ``railed`` is asserted while the loop sits at a gain clamp (overload/underrange); with
    ``with_irq=True`` its rising edge raises an interrupt (``ev.railed``).

    Parameters
    ----------
    gain_frac : int
        Fractional bits of the gain (gain register is data_width + gain_frac bits, reset to
        1.0 = 2**gain_frac). More bits = finer gain resolution but a wider multiplier.
    mu : int
        Loop-gain exponent; each accepted sample updates gain by (target - |x|) >> mu. Larger =
        slower, smoother AGC (longer time constant); smaller = faster but may pump.
    gain_max : int
        Upper clamp of the gain integrator, in 2**-gain_frac units. Defaults to the full gain
        register range (2**(data_width + gain_frac) - 1); lower it to bound the maximum gain.
    beta_shift : int
        Beta exponent of the alpha-max-beta-min magnitude estimate (|x| ~ max + min >>
        beta_shift). 2 is the usual multiplier-free compromise (~4% peak error).
    delayed_feedback : bool
        When true, apply each magnitude observation on the following accepted sample.  This
        inserts one sample of control-loop delay without making the trajectory depend on stalls.
    feedback_delay : int or None
        Explicit accepted-sample feedback delay (0, 1, or 2).  ``None`` preserves the
        ``delayed_feedback`` compatibility switch.  Delay 2 registers the output magnitude
        before the gain integrator, splitting the remaining feedback path at the cost of one
        additional control-loop sample; datapath latency and throughput are unchanged.
    """
    def __init__(self, data_width=16, gain_frac=8, mu=8, gain_max=None, beta_shift=2, with_csr=True,
        with_irq=False, delayed_feedback=False, feedback_delay=None):
        check(isinstance(delayed_feedback, bool), "expected delayed_feedback to be a bool")
        if feedback_delay is None:
            feedback_delay = int(delayed_feedback)
        else:
            check(not delayed_feedback,
                "select feedback_delay or delayed_feedback, not both")
            check(isinstance(feedback_delay, int) and feedback_delay in (0, 1, 2),
                "feedback_delay must be 0, 1, or 2")
        self.data_width = data_width
        self.gain_frac  = gain_frac
        self.mu         = mu
        self.delayed_feedback = feedback_delay != 0
        self.feedback_delay   = feedback_delay
        gain_width      = gain_frac + data_width
        if gain_max is None:
            gain_max = (1 << gain_width) - 1
        self.gain_max   = gain_max
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.target = Signal(data_width + 1, reset=1 << (data_width - 2))   # Default ~0.25 FS.
        self.gain   = Signal(gain_width, reset=1 << gain_frac)              # Start at 1.0.
        self.railed = Signal()                                              # Gain sits at a clamp.

        # # #

        # Handshake.
        # ----------
        adv  = Signal()  # Pipeline drains (output slot free or being consumed).
        xfer = Signal()  # A sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Apply current (registered) gain.
        # --------------------------------
        # (x * gain) >> gain_frac with round-half-up + saturation (gain is Q?.gain_frac).
        out_i, _ = scaled(self.sink.i*self.gain, gain_frac, data_width)
        out_q, _ = scaled(self.sink.q*self.gain, gain_frac, data_width)
        self.sync += If(adv,
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            self.source.valid.eq(self.sink.valid),
        )

        # Magnitude Measurement.
        # ----------------------
        # Measure the *output* magnitude (alpha-max-beta-min) to close the loop.
        measure_i = self.source.i if feedback_delay else out_i
        measure_q = self.source.q if feedback_delay else out_q
        ai, aq = Signal(data_width + 1), Signal(data_width + 1)
        self.comb += [
            ai.eq(Mux(measure_i[-1], -measure_i, measure_i)),  # |I|.
            aq.eq(Mux(measure_q[-1], -measure_q, measure_q)),  # |Q|.
        ]
        mag_hi = Signal(data_width + 1)
        mag_lo = Signal(data_width + 1)
        mag = Signal(data_width + 1)
        # max + min/2**beta_shift ~ sqrt(I**2 + Q**2) (no multiplier/sqrt needed).
        self.comb += [
            mag_hi.eq(Mux(ai > aq, ai, aq)),
            mag_lo.eq(Mux(ai > aq, aq, ai)),
            mag.eq(mag_hi + (mag_lo >> beta_shift)),
        ]

        # Gain loop (leaky integrator), clamped.
        # --------------------------------------
        loop_mag = Signal(data_width + 1)
        error    = Signal((data_width + 2, True))
        step     = Signal((data_width + 2, True))
        gain_nxt = Signal((gain_width + 2, True))  # Extra bits to detect clamp under/overflow.
        self.comb += [
            error.eq(self.target - loop_mag),
            step.eq(error >> self.mu),   # Loop gain 2**-mu (arithmetic shift keeps sign).
            gain_nxt.eq(self.gain + step),
        ]
        gain_update = [
            If(gain_nxt < 0, self.gain.eq(0)
            ).Elif(gain_nxt > gain_max, self.gain.eq(gain_max)
            ).Else(self.gain.eq(gain_nxt)),
            self.railed.eq((gain_nxt < 0) | (gain_nxt > gain_max)),
        ]
        # Gain integrates only on accepted samples, so both architectures pause with the stream.
        # The delayed option normally observes the registered output as it is replaced.  If the
        # consumer drains that output during an input gap, retain its magnitude until the next
        # accepted sample so wall-clock stalls cannot change the sample-domain trajectory.
        if feedback_delay == 1:
            feedback_mag       = Signal(data_width + 1)
            feedback_valid     = Signal()
            feedback_available = Signal()
            self.comb += [
                loop_mag.eq(Mux(feedback_valid, feedback_mag, mag)),
                feedback_available.eq(feedback_valid | self.source.valid),
            ]
            self.sync += [
                If(xfer,
                    If(feedback_available, *gain_update),
                    If(feedback_valid, feedback_valid.eq(0)),
                ),
                If(self.source.valid & self.source.ready & ~xfer,
                    feedback_mag.eq(mag),
                    feedback_valid.eq(1),
                ),
            ]
        elif feedback_delay == 2:
            # Register max/min components from each output, then form the magnitude on the gain
            # side of the boundary.  A two-entry queue retains observations across input gaps;
            # ``source_observed`` also captures a blocked output before its eventual transfer,
            # ensuring the due observation is registered before the corresponding input can be
            # accepted.  The warm-up counter keeps the delay exactly two accepted samples.
            observation_hi    = [Signal(data_width + 1) for _ in range(2)]
            observation_lo    = [Signal(data_width + 1) for _ in range(2)]
            observation_count = Signal(max=3)
            accepted_count    = Signal(max=3)
            source_observed   = Signal()
            observation_push  = Signal()
            observation_pop   = Signal()
            self.comb += [
                observation_push.eq(self.source.valid & ~source_observed),
                observation_pop.eq(xfer & (accepted_count == 2)),
                loop_mag.eq(observation_hi[0] + (observation_lo[0] >> beta_shift)),
            ]
            self.sync += [
                If(adv,
                    source_observed.eq(0),
                ).Elif(observation_push,
                    source_observed.eq(1),
                ),
                If(xfer & (accepted_count != 2),
                    accepted_count.eq(accepted_count + 1),
                ),
                If(observation_pop, *gain_update),
                Case(Cat(observation_pop, observation_push), {
                    0b01: [
                        If(observation_count == 2,
                            observation_hi[0].eq(observation_hi[1]),
                            observation_lo[0].eq(observation_lo[1]),
                        ),
                        observation_count.eq(observation_count - 1),
                    ],
                    0b10: [
                        If(observation_count == 0,
                            observation_hi[0].eq(mag_hi),
                            observation_lo[0].eq(mag_lo),
                            observation_count.eq(1),
                        ).Elif(observation_count == 1,
                            observation_hi[1].eq(mag_hi),
                            observation_lo[1].eq(mag_lo),
                            observation_count.eq(2),
                        ),
                    ],
                    0b11: [
                        If(observation_count == 1,
                            observation_hi[0].eq(mag_hi),
                            observation_lo[0].eq(mag_lo),
                        ).Elif(observation_count == 2,
                            observation_hi[0].eq(observation_hi[1]),
                            observation_lo[0].eq(observation_lo[1]),
                            observation_hi[1].eq(mag_hi),
                            observation_lo[1].eq(mag_lo),
                        ),
                    ],
                }),
            ]
        else:
            self.comb += loop_mag.eq(mag)
            self.sync += If(xfer, *gain_update)

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev        = EventManager()
        self.ev.railed = EventSourceProcess(edge="rising",
            description="AGC gain hit a clamp (overload/underrange).")
        self.ev.finalize()
        self.comb += self.ev.railed.trigger.eq(self.railed)

    def add_csr(self):
        self._target = CSRStorage(self.target.nbits, reset=1 << (self.data_width - 2),
            name="target", description="Target output magnitude.")
        self._gain   = CSRStatus(self.gain.nbits, name="gain", description="Current gain (Q?.frac).")
        self._config = CSRStatus(fields=[
            CSRField("feedback_delay", size=2,
                description="Accepted-sample delay in the gain feedback path."),
        ])
        self.comb += [
            self.target.eq(self._target.storage),
            self._gain.status.eq(self.gain),
            self._config.fields.feedback_delay.eq(self.feedback_delay),
        ]
