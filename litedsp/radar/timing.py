#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Pulse timing: the PRI/CPI timer that gates the receiver into framed range-bin pulses."""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourcePulse
from litex.soc.interconnect                  import stream

from litedsp.common import check, iq_layout

# Range Gate ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPRangeGate(LiteXModule):
    """PRI / CPI timer and receive gate: turns a continuous I/Q stream into framed pulses.

    A sample-domain counter ``t`` (it advances on every accepted input sample, so the timing is
    exact under any valid/ready pattern) runs from 0 to ``pri - 1`` per pulse repetition
    interval; ``n_pulses_cpi`` intervals make a coherent processing interval. Samples with
    ``gate_start <= t < gate_start + gate_len`` pass, framed (``first`` at the gate start,
    ``last`` at its end); the others are consumed and dropped. ``tx`` is high for
    ``pulse_width`` samples at the start of each interval (the transmit strobe), ``rx_gate``
    mirrors the receive window and ``cpi_start`` pulses on the first sample of a CPI (IRQ
    ``ev.cpi``). Continuous operation with ``enable``; ``single`` runs exactly one CPI per
    ``trigger``. Latency 1 cycle; the output rate is ``gate_len / pri``.

    Parameters
    ----------
    n_range_bins : int
        Maximum gate length in samples (sizes the runtime ``gate_len``, reset to it).
    pri, gate_start, pulse_width, n_pulses : int
        Reset values of the runtime timing registers; ``pri_width`` sizes them.
    """
    def __init__(self, data_width=16, n_range_bins=64, n_pulses=16, pri=128, gate_start=0,
        pulse_width=16, pri_width=24, with_csr=True, with_irq=False):
        check(n_range_bins >= 1, "expected n_range_bins >= 1")
        check(n_pulses >= 1, "expected n_pulses >= 1")
        check(2 <= pri < (1 << pri_width), "expected 2 <= pri < 2**pri_width")
        check(gate_start >= 0 and gate_start + n_range_bins <= pri,
              "expected gate_start + n_range_bins <= pri")
        check(0 <= pulse_width <= pri, "expected 0 <= pulse_width <= pri")
        self.data_width   = data_width
        self.n_range_bins = n_range_bins
        self.n_pulses     = n_pulses
        self.latency      = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.pri          = Signal(pri_width, reset=pri)
        self.gate_start   = Signal(pri_width, reset=gate_start)
        self.gate_len     = Signal(max=n_range_bins + 1, reset=n_range_bins)
        self.pulse_width  = Signal(pri_width, reset=pulse_width)
        self.n_pulses_cpi = Signal(max=n_pulses + 1, reset=n_pulses)
        self.enable       = Signal()
        self.single       = Signal()
        self.trigger      = Signal()
        self.tx           = Signal()                                    # Pins / status.
        self.rx_gate      = Signal()
        self.cpi_start    = Signal()
        self.running      = Signal()
        self.pulse_index  = Signal(max=n_pulses)
        self.pulse_count  = Signal(32)

        # # #

        # Timer (advances on accepted samples while running).
        # ----------------------------------------------------
        adv, xfer = Signal(), Signal()
        armed     = Signal()
        t         = Signal(pri_width)
        pri_end   = Signal()
        cpi_end   = Signal()
        gate_end  = Signal(pri_width + 1)
        in_gate   = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
            self.running.eq(self.enable | armed),
            pri_end.eq(t == self.pri - 1),
            cpi_end.eq(pri_end & (self.pulse_index == self.n_pulses_cpi - 1)),
            gate_end.eq(self.gate_start + self.gate_len),
            in_gate.eq(self.running & (t >= self.gate_start) & (t < gate_end)),
            self.rx_gate.eq(in_gate),
            self.tx.eq(self.running & (t < self.pulse_width)),
            self.cpi_start.eq(xfer & self.running & (t == 0) & (self.pulse_index == 0)),
        ]
        self.sync += [
            If(self.trigger & self.single, armed.eq(1)),
            If(~self.running,
                t.eq(0), self.pulse_index.eq(0),
            ).Elif(xfer,
                If(pri_end,
                    t.eq(0),
                    If(self.pulse_index == self.n_pulses_cpi - 1,
                        self.pulse_index.eq(0),
                    ).Else(
                        self.pulse_index.eq(self.pulse_index + 1),
                    ),
                    self.pulse_count.eq(self.pulse_count + 1),
                    If(cpi_end & ~self.trigger, armed.eq(0)),
                ).Else(
                    t.eq(t + 1),
                ),
            ),
        ]

        # Gated, framed output register.
        # ------------------------------
        self.sync += If(adv,
            self.source.valid.eq(xfer & in_gate),
            self.source.i.eq(self.sink.i),
            self.source.q.eq(self.sink.q),
            self.source.first.eq(t == self.gate_start),
            self.source.last.eq(t == gate_end - 1),
        )

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev     = EventManager()
        self.ev.cpi = EventSourcePulse(description="A coherent processing interval started.")
        self.ev.finalize()
        self.comb += self.ev.cpi.trigger.eq(self.cpi_start)

    def add_csr(self):
        self._pri = CSRStorage(len(self.pri), reset=self.pri.reset.value, name="pri",
            description="Pulse repetition interval in samples.")
        self._gate = CSRStorage(fields=[
            CSRField("start", size=len(self.gate_start), offset=0, reset=self.gate_start.reset.value,
                description="First received range bin (sample index in the interval)."),
            CSRField("length", size=len(self.gate_len), offset=24, reset=self.gate_len.reset.value,
                description="Range bins per pulse (<= n_range_bins)."),
        ])
        self._pulse = CSRStorage(fields=[
            CSRField("width",    size=len(self.pulse_width), offset=0, reset=self.pulse_width.reset.value,
                description="Transmit strobe length in samples."),
            CSRField("n_pulses", size=len(self.n_pulses_cpi), offset=24, reset=self.n_pulses_cpi.reset.value,
                description="Pulses per CPI."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("enable",  size=1, offset=0, description="Run continuously."),
            CSRField("single",  size=1, offset=1, description="Run one CPI per trigger."),
            CSRField("trigger", size=1, offset=2, pulse=True, description="Start a CPI (single mode)."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("running",     size=1, offset=0, description="Timer running."),
            CSRField("pulse_index", size=len(self.pulse_index), offset=8, description="Pulse within the CPI."),
        ])
        self._pulse_count = CSRStatus(32, name="pulse_count", description="Pulses since reset.")
        self.comb += [
            self.pri.eq(self._pri.storage),
            self.gate_start.eq(self._gate.fields.start),
            self.gate_len.eq(self._gate.fields.length),
            self.pulse_width.eq(self._pulse.fields.width),
            self.n_pulses_cpi.eq(self._pulse.fields.n_pulses),
            self.enable.eq(self._control.fields.enable),
            self.single.eq(self._control.fields.single),
            self.trigger.eq(self._control.fields.trigger),
            self._status.fields.running.eq(self.running),
            self._status.fields.pulse_index.eq(self.pulse_index),
            self._pulse_count.status.eq(self.pulse_count),
        ]

# Pulse Generator ----------------------------------------------------------------------------------

from litedsp.generation.source import LiteDSPChirp
from litedsp.radar.waveform    import chirp_words

@ResetInserter()
class LiteDSPPulseGenerator(LiteXModule):
    """Transmit pulse train: a linear-FM chirp of ``pulse_len`` samples every ``pri`` samples.

    Source-only block: an internal :class:`LiteDSPChirp` (held in reset between pulses, so each
    pulse restarts from the ``start`` / ``rate`` words, see
    ``litedsp.radar.waveform.chirp_words``) is framed (``first`` on the first chirp sample,
    ``last`` on the last) and followed by zeros up to the PRI. ``enable`` runs CPIs of
    ``n_pulses`` back to back; ``single`` with a ``trigger`` pulse sends one pulse. Outputs:
    ``tx`` (during the pulse), ``pulse_start`` (one cycle at the first sample), ``running``
    and ``pulse_count``. ``pulse_len``, ``pri`` and ``n_pulses`` are runtime. One bubble per
    pulse start (the chirp's first sample follows its reset release).
    """
    def __init__(self, data_width=16, pulse_len=32, bandwidth=0.5, pri=128, n_pulses=16,
                 pri_width=24,
        phase_bits=32, lut_depth=1024, with_csr=True):
        check(2 <= pulse_len < pri, "expected 2 <= pulse_len < pri")
        check(pri < 2**pri_width, "expected pri < 2**pri_width")
        check(n_pulses >= 1, "expected n_pulses >= 1")
        start, rate = chirp_words(bandwidth, pulse_len, phase_bits)
        self.data_width = data_width
        self.phase_bits = phase_bits
        self.pri_width  = pri_width
        self.source = stream.Endpoint(iq_layout(data_width))
        self.start     = Signal(phase_bits, reset=start)
        self.rate      = Signal(phase_bits, reset=rate)
        self.pulse_len = Signal(pri_width, reset=pulse_len)
        self.pri       = Signal(pri_width, reset=pri)
        self.n_pulses  = Signal(16, reset=n_pulses)
        self.enable    = Signal()
        self.single    = Signal()
        self.trigger   = Signal()
        self.tx          = Signal()
        self.pulse_start = Signal()
        self.running     = Signal()
        self.pulse_count = Signal(32)

        # # #

        self.chirp = chirp = LiteDSPChirp(phase_bits=phase_bits, data_width=data_width,
                                          lut_depth=lut_depth,
            with_csr=False)                                             # Has its own reset control.
        self.comb += [chirp.start.eq(self.start), chirp.rate.eq(self.rate)]
        adv  = Signal()
        t    = Signal(pri_width)                                        # Sample index in the PRI.
        idx  = Signal(16)                                               # Pulse index in the CPI.
        beat = Signal()                                                # An output sample is formed.
        self.comb += adv.eq(self.source.ready | ~self.source.valid)
        self.fsm = fsm = FSM(reset_state="IDLE")
        fsm.act("IDLE",
            chirp.reset.eq(1),
            If(self.enable | (self.single & self.trigger),
                NextValue(t, 0), NextValue(idx, 0),
                NextState("PULSE"),
            ),
        )
        fsm.act("PULSE",
            self.running.eq(1),
            self.tx.eq(1),
            chirp.source.ready.eq(adv),
            beat.eq(chirp.source.valid),
            If(adv & beat,
                If(t == self.pulse_len - 1,
                    NextState("GAP"),
                ),
                NextValue(t, t + 1),
            ),
        )
        fsm.act("GAP",
            self.running.eq(1),
            chirp.reset.eq(1),
            beat.eq(1),
            If(adv,
                If(t == self.pri - 1,
                    NextValue(t, 0),
                    If(self.single & ~self.enable,
                        NextState("IDLE"),
                    ).Elif(idx == self.n_pulses - 1,
                        NextValue(idx, 0),
                        If(self.enable, NextState("PULSE")).Else(NextState("IDLE")),
                    ).Else(
                        NextValue(idx, idx + 1),
                        NextState("PULSE"),
                    ),
                ).Else(
                    NextValue(t, t + 1),
                ),
            ),
        )
        in_pulse = Signal()
        self.comb += in_pulse.eq(fsm.ongoing("PULSE"))
        self.sync += [
            self.pulse_start.eq(0),
            If(adv,
                self.source.valid.eq(beat),
                self.source.i.eq(Mux(in_pulse, chirp.source.i, 0)),
                self.source.q.eq(Mux(in_pulse, chirp.source.q, 0)),
                self.source.first.eq(in_pulse & (t == 0)),
                self.source.last.eq(in_pulse & (t == self.pulse_len - 1)),
                If(beat & in_pulse & (t == 0),
                    self.pulse_start.eq(1),
                    self.pulse_count.eq(self.pulse_count + 1),
                ),
            ),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._start = CSRStorage(self.phase_bits, reset=self.start.reset.value, name="start",
                                 description="Chirp start frequency word.")
        self._rate  = CSRStorage(self.phase_bits, reset=self.rate.reset.value, name="rate",
                                 description="Chirp frequency increment per sample.")
        self._timing = CSRStorage(fields=[
            CSRField("pulse_len", size=16, offset=0,  reset=self.pulse_len.reset.value, description="Pulse length (samples)."),
            CSRField("n_pulses",  size=16, offset=16, reset=self.n_pulses.reset.value,  description="Pulses per CPI."),
        ])
        self._pri = CSRStorage(self.pri_width, reset=self.pri.reset.value, name="pri",
                               description="Pulse repetition interval (samples).")
        self._control = CSRStorage(fields=[
            CSRField("enable",  size=1, offset=0, description="Run CPIs continuously."),
            CSRField("single",  size=1, offset=1, description="One pulse per trigger."),
            CSRField("trigger", size=1, offset=2, pulse=True, description="Start a single pulse."),
        ])
        self._status = CSRStatus(fields=[
            CSRField("running", size=1, offset=0, description="A pulse train is in progress."),
            CSRField("tx",      size=1, offset=1, description="Transmitting."),
        ])
        self._pulse_count = CSRStatus(32, name="pulse_count",
                                      description="Pulses sent since reset.")
        self.comb += [
            self.start.eq(self._start.storage), self.rate.eq(self._rate.storage),
            self.pulse_len.eq(self._timing.fields.pulse_len),
            self.n_pulses.eq(self._timing.fields.n_pulses),
            self.pri.eq(self._pri.storage),
            self.enable.eq(self._control.fields.enable),
            self.single.eq(self._control.fields.single),
            self.trigger.eq(self._control.fields.trigger),
            self._status.fields.running.eq(self.running), self._status.fields.tx.eq(self.tx),
            self._pulse_count.status.eq(self.pulse_count),
        ]
