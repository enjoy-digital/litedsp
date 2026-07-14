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

from litedsp.common            import check, iq_layout
from litedsp.generation.cordic import LiteDSPCORDIC

# Coarse CFO Estimator -------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCFOEstimator(LiteXModule):
    """Coarse CFO estimator: delay-conjugate-multiply autocorrelation + CORDIC angle.

    Schmidl-Cox / van de Beek style acquisition front-end. For a signal that repeats with
    period ``D = delay`` samples (a repeated preamble, or OFDM where the cyclic prefix sits
    ``D = fft_size`` samples from the symbol tail), each product ``r[n] = x[n]*conj(x[n-D])``
    has phase ``2*pi*f_cfo*D`` independent of the modulation, so a carrier frequency offset
    survives averaging while data and noise average out. The block free-runs in blocks:
    ``R = sum r[n]`` is accumulated over ``2**span_log2`` samples — kept exact, no rounding:
    the complex product grows to ``2*data_width + 1`` bits and the accumulation adds
    ``span_log2`` bits — then ``(Re R, Im R)`` is vectored through a CORDIC
    (:class:`litedsp.generation.cordic.LiteDSPCORDIC`, ``stages = angle_width``) to get
    ``angle(R)``, the result is latched with a one-cycle ``estimate_ready`` pulse (counted in
    a CSR, optional IRQ via ``with_irq=True``), and the next span starts. The unambiguous
    capture range is ``|f_cfo| < 1/(2*D)`` cycles/sample (``|angle| < pi``).

    The input stream passes through unchanged (combinational, ``latency = 0``): the estimator
    is a monitoring tap that drops into a chain directly in front of a
    :class:`litedsp.correction.cfo.LiteDSPDerotator`.

    Scaling (why ``delay`` must be a power of two): angles are signed with full circle =
    ``2**angle_width``, so the latched ``angle = f_cfo*D*2**angle_width``. The derotator
    down-mixes by its NCO frequency (``source = sink*exp(-j*2*pi*n*phase_inc/2**phase_bits)``
    — the minus sign lives in its conjugating mixer), so cancelling the offset needs
    ``phase_inc = +f_cfo*2**phase_bits = angle*2**(phase_bits - angle_width)/D``. With
    ``D = 2**delay_log2`` this is the exact left shift
    ``phase_inc_correction = angle << (phase_bits - angle_width - delay_log2)`` (enforced
    non-negative by ``check()``); a non-power-of-two ``D`` would need a hardware divider.
    ``phase_inc_correction`` can be written as-is to the derotator NCO ``phase_inc``.

    Parameters
    ----------
    delay : int
        Autocorrelation lag ``D`` in samples (power of two >= 2): the repetition period of
        the training signal (preamble repeat length / OFDM CP distance = FFT size). Sets the
        capture range ``|f_cfo| < 1/(2*delay)`` and the delay-line depth.
    span_log2 : int
        Accumulation span as a power of two: one estimate per ``2**span_log2`` samples.
        Longer spans average more noise (estimator variance ~ 1/span) but slow the update
        rate; the first span after reset includes ``delay`` zero products while the delay
        line fills.
    angle_width : int
        Angle resolution in bits (full circle = 2**angle_width); sets the CORDIC stage count.
    phase_bits : int
        Phase-accumulator width of the derotator NCO that ``phase_inc_correction`` is scaled
        for (requires ``phase_bits >= angle_width + log2(delay)``).
    """
    def __init__(self, data_width=16, delay=16, span_log2=8, angle_width=16, phase_bits=32,
        with_csr=True, with_irq=False):
        check(delay >= 2 and (delay & (delay - 1)) == 0, "expected power-of-two delay >= 2")
        check(span_log2 >= 1,                            "expected span_log2 >= 1")
        check(angle_width >= 4,                          "expected angle_width >= 4")
        delay_log2 = log2_int(delay)
        shift      = phase_bits - angle_width - delay_log2
        check(shift >= 0, "expected phase_bits >= angle_width + log2(delay) (exact shift scaling)")
        self.data_width  = data_width
        self.delay       = delay
        self.span_log2   = span_log2
        self.angle_width = angle_width
        self.phase_bits  = phase_bits
        acc_width        = 2*data_width + 1 + span_log2  # Exact: product + span growth.
        self.latency     = 0                             # Combinational passthrough.
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.angle                = Signal((angle_width, True))  # Latched angle(R).
        self.phase_inc_correction = Signal(phase_bits)           # Latched angle << shift.
        self.estimate_ready       = Signal()                     # 1-cycle pulse per new estimate.
        self.count                = Signal(32)                   # Estimates since reset/clear.
        self.clear_count          = Signal()                     # Clear the estimate counter.

        # # #

        # Passthrough (comb, latency 0): the estimator only taps accepted samples.
        # -------------------------------------------------------------------------
        self.comb += self.sink.connect(self.source)
        step = Signal()  # One sample flows through.
        self.comb += step.eq(self.sink.valid & self.sink.ready)

        # Delay Line (x[n-D], zero pre-fill).
        # -----------------------------------
        # Circular buffer: at step n the read side fetches mem[n % D] = x[n-D] while the
        # write side (address/data registered, so it trails by one step) stores x[n-1] at
        # (n-1) % D — read and write addresses never collide (D >= 2), and the power-of-two
        # depth makes the pointer wrap free.
        mem = Memory(2*data_width, delay, init=[0]*delay)
        wp  = mem.get_port(write_capable=True)
        rp  = mem.get_port(has_re=True)
        self.specials += mem, wp, rp
        ptr    = Signal(delay_log2)          # Read pointer (n % D).
        wr_adr = Signal(delay_log2)          # Write side, one step behind.
        wr_dat = Signal(2*data_width)
        wr_en  = Signal()
        self.comb += [
            rp.re.eq(step),  rp.adr.eq(ptr),
            wp.we.eq(step & wr_en), wp.adr.eq(wr_adr), wp.dat_w.eq(wr_dat),
        ]
        self.sync += If(step,
            ptr.eq(ptr + 1),
            wr_adr.eq(ptr),
            wr_dat.eq(Cat(self.sink.i, self.sink.q)),
            wr_en.eq(1),
        )

        # Product r[n] = x[n] * conj(x[n-D])  (exact, 2*data_width + 1 bits).
        # -------------------------------------------------------------------
        # Sample-domain pipeline (advances only on accepted samples): stage 0 pairs x[n]
        # with the delay-line read, stage 1 registers the complex product. v0/v1 track
        # which stages hold real samples so warm-up slots are never accumulated.
        x1_i = Signal((data_width, True))
        x1_q = Signal((data_width, True))
        xd_i = Signal((data_width, True))
        xd_q = Signal((data_width, True))
        r_i  = Signal((2*data_width + 1, True))
        r_q  = Signal((2*data_width + 1, True))
        v0   = Signal()
        v1   = Signal()
        self.comb += [xd_i.eq(rp.dat_r[:data_width]), xd_q.eq(rp.dat_r[data_width:])]
        self.sync += If(step,
            x1_i.eq(self.sink.i),
            x1_q.eq(self.sink.q),
            v0.eq(1),
            r_i.eq(x1_i*xd_i + x1_q*xd_q),
            r_q.eq(x1_q*xd_i - x1_i*xd_q),
            v1.eq(v0),
        )

        # Block Accumulation (exact) + span restart.
        # ------------------------------------------
        N        = 1 << span_log2
        acc_i    = Signal((acc_width, True))
        acc_q    = Signal((acc_width, True))
        cnt      = Signal(span_log2)         # Products accumulated in the current span.
        last     = Signal()                  # Current product completes the span.
        total_i  = Signal((acc_width, True)) # acc + r (combinational fold of the last product).
        total_q  = Signal((acc_width, True))
        span_end = Signal()
        self.comb += [
            last.eq(cnt == (N - 1)),
            total_i.eq(acc_i + r_i),
            total_q.eq(acc_q + r_q),
            span_end.eq(step & v1 & last),
        ]
        self.sync += If(step & v1,
            If(last,
                acc_i.eq(0), acc_q.eq(0), cnt.eq(0),  # Restart the span.
            ).Else(
                acc_i.eq(total_i), acc_q.eq(total_q), cnt.eq(cnt + 1),
            ),
        )

        # CORDIC Vectoring: angle(R).
        # ---------------------------
        # Fed at full accumulator width (vectoring angle is scale-invariant, so keeping R
        # exact costs only datapath width, not precision). The CORDIC source is always ready,
        # so its pipeline free-runs: feeds (>= N cycles apart) can never back up.
        feed_valid = Signal()
        feed_x     = Signal((acc_width, True))
        feed_y     = Signal((acc_width, True))
        self.sync += [
            feed_valid.eq(span_end),
            If(span_end, feed_x.eq(total_i), feed_y.eq(total_q)),
        ]
        self.cordic = LiteDSPCORDIC(data_width=acc_width, angle_width=angle_width,
            stages=angle_width, mode="vectoring", with_csr=False)
        self.comb += [
            self.cordic.sink.valid.eq(feed_valid),
            self.cordic.sink.x.eq(feed_x),
            self.cordic.sink.y.eq(feed_y),
            self.cordic.source.ready.eq(1),
        ]

        # Result Latch: angle, phase_inc correction, ready pulse + counter.
        # -----------------------------------------------------------------
        # phase_inc = angle * 2**(phase_bits - angle_width) / D, exact as a left shift for
        # power-of-two D (see class docstring: the cancelling minus sign is the derotator's
        # down-mixer); the truncation to phase_bits is the natural modular phase arithmetic
        # of the NCO accumulator.
        self.sync += [
            self.estimate_ready.eq(self.cordic.source.valid),
            If(self.cordic.source.valid,
                self.angle.eq(self.cordic.source.angle),
                self.phase_inc_correction.eq(self.cordic.source.angle << shift),
            ),
            If(self.clear_count,
                self.count.eq(0),
            ).Elif(self.cordic.source.valid,
                self.count.eq(self.count + 1),
            ),
        ]

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev          = EventManager()
        self.ev.estimate = EventSourceProcess(edge="rising",
            description="New CFO estimate latched (angle/phase_inc updated).")
        self.ev.finalize()
        self.comb += self.ev.estimate.trigger.eq(self.estimate_ready)

    def add_csr(self):
        self._angle = CSRStatus(self.angle_width, name="angle",
            description="Latched autocorrelation angle (signed two's complement, full circle "
                        "= 2**angle_width): CFO = angle / (2**angle_width * delay) "
                        "cycles/sample.")
        self._phase_inc = CSRStatus(self.phase_bits, name="phase_inc",
            description="Latched derotator correction (angle rescaled to NCO phase units): "
                        "write to the derotator NCO phase_inc to cancel the estimated CFO "
                        "(the derotator's down-mixer applies the minus sign).")
        self._count = CSRStatus(32, name="count", description="Estimates since reset/clear.")
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the estimate counter."),
        ])
        self.comb += [
            self._angle.status.eq(self.angle),
            self._phase_inc.status.eq(self.phase_inc_correction),
            self._count.status.eq(self.count),
            self.clear_count.eq(self._control.fields.clear),
        ]
