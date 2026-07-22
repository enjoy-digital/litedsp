#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common   import check, iq_layout, scaled
from litedsp.control  import LiteDSPPILoop

# Carrier Recovery Loop ----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCarrierLoop(LiteXModule):
    """Carrier recovery: derotate the input with an internal NCO driven by a PI loop.

    Each sample is derotated by ``exp(-j*phase)``; the phase error feeds a :class:`LiteDSPPILoop` whose
    output advances the NCO phase (a 2nd-order loop that locks frequency and phase). The
    derotated (baseband) signal is the output. ``decision_directed=False`` (PLL) uses the
    derotated imaginary part as the error (residual-carrier / tone). ``detector="bpsk"`` uses
    ``sign(I)*Q`` and ``detector="qpsk"`` uses ``sign(I)*Q - sign(Q)*I``. The latter is the
    multiplier-free decision-directed QPSK detector with four stable phase ambiguities.

    Parameters
    ----------
    lut_depth : int
        Depth of the NCO cos/sin LUTs (power of 2); addressed by the top log2(lut_depth)
        phase bits, so deeper LUTs trade memory for lower phase quantization.
    kp_shift : int
        Proportional gain of the PI loop: Kp = 2**-kp_shift. Larger shift = smaller gain
        (slower, tighter loop).
    ki_shift : int
        Integral (frequency) gain of the PI loop: Ki = 2**-ki_shift per sample. Larger
        shift = smaller gain (slower frequency acquisition, less jitter).
    decision_directed : bool
        Backward-compatible BPSK selector. When ``detector`` is omitted, False selects PLL and
        True selects BPSK Costas behavior.
    detector : str or None
        ``"pll"`` for a residual carrier, ``"bpsk"`` for suppressed-carrier BPSK, or
        ``"qpsk"`` for decision-directed QPSK. Explicit ``detector`` takes precedence over
        ``decision_directed``.
    architecture : str
        ``"classic"`` applies the current sample's detector error to the next accepted sample.
        ``"pipelined"`` registers the NCO operands, mixer products and detector error, applying
        each error four accepted samples later. The latter retains one sample/clock throughput
        and is intended for high-clock-rate receiver chains; its additional loop delay changes
        acquisition and jitter and is therefore explicit rather than a transparent retiming.
    """
    def __init__(self, data_width=16, phase_bits=32, lut_depth=1024,
        kp_shift=6, ki_shift=14, decision_directed=False, detector=None,
        architecture="classic", with_csr=True):
        if detector is None:
            detector = "bpsk" if decision_directed else "pll"
        check(detector in ("pll", "bpsk", "qpsk"),
            "detector must be 'pll', 'bpsk', or 'qpsk'.")
        check(architecture in ("classic", "pipelined"),
            "architecture must be 'classic' or 'pipelined'.")
        self.detector = detector
        self.decision_directed = detector != "pll"
        self.architecture = architecture
        self.loop_delay = 1 if architecture == "classic" else 4
        self.sink    = stream.Endpoint(iq_layout(data_width))
        self.source  = stream.Endpoint(iq_layout(data_width))
        self.latency = 1 if architecture == "classic" else 3

        # # #

        # Handshake.
        # ----------
        adv  = Signal()  # Output slot free or being consumed.
        xfer = Signal()  # Input sample accepted this cycle (loop runs per sample).
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # NCO phase accumulator + cos/sin LUT (async read).
        # -------------------------------------------------
        addr_bits = int(math.log2(lut_depth))
        scale     = (1 << (data_width - 1)) - 1  # Full-scale Q1.(N-1).
        cos_init  = [int(round(math.cos(2*math.pi*n/lut_depth)*scale)) & ((1 << data_width) - 1)
                     for n in range(lut_depth)]
        sin_init  = [int(round(math.sin(2*math.pi*n/lut_depth)*scale)) & ((1 << data_width) - 1)
                     for n in range(lut_depth)]
        cos_rom, sin_rom = Memory(data_width, lut_depth, init=cos_init), Memory(data_width, lut_depth, init=sin_init)
        cos_rp, sin_rp   = cos_rom.get_port(async_read=True), sin_rom.get_port(async_read=True)
        self.specials += cos_rom, sin_rom, cos_rp, sin_rp

        phase = Signal(phase_bits)          # NCO phase accumulator (full circle = 2**phase_bits).
        cos   = Signal((data_width, True))
        sin   = Signal((data_width, True))
        self.comb += [
            cos_rp.adr.eq(phase[phase_bits - addr_bits:]),  # Top phase bits address the LUTs.
            sin_rp.adr.eq(phase[phase_bits - addr_bits:]),
            cos.eq(cos_rp.dat_r), sin.eq(sin_rp.dat_r),
        ]

        # Loop error/enable selected by the architecture below.
        loop_error = Signal((phase_bits + 2, True))
        loop_ce    = Signal()

        if architecture == "classic":
            # Derotate: d = input * exp(-j*phase) = (i*cos + q*sin) + j(q*cos - i*sin).
            # Keep explicitly sized sums so Verilog expression context cannot narrow products.
            i, q = self.sink.i, self.sink.q
            d_i_full = Signal((2*data_width + 1, True))
            d_q_full = Signal((2*data_width + 1, True))
            self.comb += [
                d_i_full.eq(i*cos + q*sin),
                d_q_full.eq(q*cos - i*sin),
            ]
            d_i, _ = scaled(d_i_full, data_width - 1, data_width)
            d_q, _ = scaled(d_q_full, data_width - 1, data_width)

            err = Signal((data_width + 2, True))
            if detector == "bpsk":
                self.comb += err.eq(Mux(d_i >= 0, d_q, -d_q))
            elif detector == "qpsk":
                self.comb += err.eq(
                    Mux(d_i >= 0, d_q, -d_q) - Mux(d_q >= 0, d_i, -d_i))
            else:
                self.comb += err.eq(d_q)
            self.comb += [
                loop_error.eq(err << (phase_bits - data_width)),
                loop_ce.eq(xfer),
            ]

            self.sync += If(adv,
                self.source.i.eq(d_i),
                self.source.q.eq(d_q),
                self.source.first.eq(self.sink.first),
                self.source.last.eq(self.sink.last),
                self.source.valid.eq(self.sink.valid),
            )
        else:
            # Stage 1: put an explicit boundary after the asynchronous NCO memories.  The input
            # sample and its phase operands advance together under the pipeline's global elastic
            # enable, so a downstream stall freezes every stage and the phase state.
            s1_valid = Signal()
            s1_i, s1_q = Signal((data_width, True)), Signal((data_width, True))
            s1_cos, s1_sin = Signal((data_width, True)), Signal((data_width, True))
            s1_first, s1_last = Signal(), Signal()

            # Stage 2: one DSP multiplication per registered path. Summation and scaling are
            # deliberately deferred so Vivado cannot rebuild the original DSP cascade.
            product_width = 2*data_width
            s2_valid = Signal()
            s2_ic = Signal((product_width, True))
            s2_qs = Signal((product_width, True))
            s2_qc = Signal((product_width, True))
            s2_is = Signal((product_width, True))
            s2_first, s2_last = Signal(), Signal()

            d_i_full = Signal((product_width + 1, True))
            d_q_full = Signal((product_width + 1, True))
            self.comb += [
                d_i_full.eq(s2_ic + s2_qs),
                d_q_full.eq(s2_qc - s2_is),
            ]
            d_i, _ = scaled(d_i_full, data_width - 1, data_width)
            d_q, _ = scaled(d_q_full, data_width - 1, data_width)
            err = Signal((data_width + 2, True))
            if detector == "bpsk":
                self.comb += err.eq(Mux(d_i >= 0, d_q, -d_q))
            elif detector == "qpsk":
                self.comb += err.eq(
                    Mux(d_i >= 0, d_q, -d_q) - Mux(d_q >= 0, d_i, -d_i))
            else:
                self.comb += err.eq(d_q)
            next_error = Signal((phase_bits + 2, True))
            self.comb += next_error.eq(err << (phase_bits - data_width))

            # Stage 3/output: register the scaled sample and its detector error.  ``completed``
            # means that output/error pair leaves the globally stalled pipeline this cycle.
            completed_error = Signal((phase_bits + 2, True))
            completed = Signal()
            self.comb += completed.eq(adv & self.source.valid)
            self.sync += If(adv,
                s1_valid.eq(self.sink.valid),
                If(self.sink.valid,
                    s1_i.eq(self.sink.i), s1_q.eq(self.sink.q),
                    s1_cos.eq(cos), s1_sin.eq(sin),
                    s1_first.eq(self.sink.first), s1_last.eq(self.sink.last),
                ),
                s2_valid.eq(s1_valid),
                If(s1_valid,
                    s2_ic.eq(s1_i*s1_cos), s2_qs.eq(s1_q*s1_sin),
                    s2_qc.eq(s1_q*s1_cos), s2_is.eq(s1_i*s1_sin),
                    s2_first.eq(s1_first), s2_last.eq(s1_last),
                ),
                self.source.valid.eq(s2_valid),
                If(s2_valid,
                    self.source.i.eq(d_i), self.source.q.eq(d_q),
                    self.source.first.eq(s2_first), self.source.last.eq(s2_last),
                    completed_error.eq(next_error),
                ),
            )

            # Completed errors can drain during input bubbles. Queue them until three newer
            # samples have been accepted; applying the oldest error after the fourth sample then
            # changes the phase seen by sample n+4. This makes the feedback distance invariant to
            # arbitrary source gaps and output backpressure.
            queue_depth = self.loop_delay
            errors = [Signal((phase_bits + 2, True)) for _ in range(queue_depth)]
            queue_count = Signal(max=queue_depth + 1)
            accepted_count = Signal(max=self.loop_delay)
            due = Signal()
            consume = Signal()
            update_error = Signal((phase_bits + 2, True))
            self.comb += [
                due.eq(xfer & (accepted_count == self.loop_delay - 1)),
                consume.eq(due & ((queue_count != 0) | completed)),
                update_error.eq(Mux(queue_count != 0, errors[0], completed_error)),
                loop_error.eq(update_error),
                loop_ce.eq(consume),
            ]
            self.sync += If(xfer & (accepted_count != self.loop_delay - 1),
                accepted_count.eq(accepted_count + 1),
            )
            shift = [errors[n].eq(errors[n + 1]) for n in range(queue_depth - 1)]
            push_slot = Array(errors)
            self.sync += Case(Cat(consume, completed), {
                0b01: [
                    *shift,
                    queue_count.eq(queue_count - 1),
                ],
                0b10: [
                    If(queue_count != queue_depth,
                        push_slot[queue_count].eq(completed_error),
                        queue_count.eq(queue_count + 1),
                    ),
                ],
                0b11: [
                    If(queue_count != 0,
                        *shift,
                        push_slot[queue_count - 1].eq(completed_error),
                    ),
                ],
            })

        # PI Loop: in pipelined mode its registered input is an accepted-sample-delayed error.
        self.pi = LiteDSPPILoop(error_width=phase_bits + 2, out_width=phase_bits + 2,
            kp_shift=kp_shift, ki_shift=ki_shift)
        self.comb += [self.pi.error.eq(loop_error), self.pi.ce.eq(loop_ce)]
        self.sync += If(loop_ce, phase.eq(phase + self.pi.out))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._freq = CSRStatus(32, name="frequency",
            description="Recovered carrier frequency (PI integrator).")
        self.comb += self._freq.status.eq(self.pi.integral)

# Convenience aliases ------------------------------------------------------------------------------

class LiteDSPPLL(LiteDSPCarrierLoop):
    """Phase-locked loop for a residual carrier / tone (PLL phase detector)."""
    def __init__(self, **kwargs):
        kwargs.pop("decision_directed", None)
        LiteDSPCarrierLoop.__init__(self, decision_directed=False, **kwargs)

class LiteDSPCostas(LiteDSPCarrierLoop):
    """Costas loop for suppressed-carrier BPSK (decision-directed phase detector)."""
    def __init__(self, **kwargs):
        kwargs.pop("decision_directed", None)
        kwargs.pop("detector", None)
        LiteDSPCarrierLoop.__init__(self, detector="bpsk", **kwargs)

class LiteDSPQPSKCostas(LiteDSPCarrierLoop):
    """Decision-directed Costas loop for QPSK (four-fold phase ambiguity)."""
    def __init__(self, **kwargs):
        kwargs.pop("decision_directed", None)
        kwargs.pop("detector", None)
        LiteDSPCarrierLoop.__init__(self, detector="qpsk", **kwargs)
