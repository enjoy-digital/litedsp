#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Angle modulators: frequency (FM) and phase (PM) modulation onto a complex baseband / IF."""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common         import check, real_layout, iq_layout, rounded
from litedsp.generation.nco import sincos_rom

# Angle Modulator ----------------------------------------------------------------------------------

class _LiteDSPAngleModulator(LiteXModule):
    """Shared FM / PM engine: ``prod = d * deviation`` (registered), ``inc = phase_inc +
    rounded(prod, data_width - 1)``; FM accumulates ``inc`` per accepted sample, PM adds the
    modulation to a free-running carrier phase; a quarter-wave cos/sin ROM gives I/Q."""
    def __init__(self, mode, data_width=16, phase_bits=32, lut_depth=1024, with_csr=True):
        check(mode in ("fm", "pm"), "expected mode in ('fm', 'pm')")
        check(lut_depth & (lut_depth - 1) == 0 and lut_depth >= 16,
              "expected lut_depth a power of two >= 16")
        self.mode       = mode
        self.data_width = data_width
        self.phase_bits = phase_bits
        self.lut_depth  = lut_depth
        self.latency    = 2
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.phase_inc = Signal(phase_bits)                            # Carrier / centre frequency.
        self.deviation = Signal(phase_bits)                             # Increment at full scale.

        # # #

        DW, PB = data_width, phase_bits
        addr_bits = int(math.log2(lut_depth))
        adv, xfer = Signal(), Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv),
                      xfer.eq(self.sink.valid & adv)]
        # S1: the product and the sample's tags.
        prod = Signal((DW + PB + 1, True))
        v1, f1, l1 = Signal(), Signal(), Signal()
        dev_s = Signal((PB + 1, True))
        self.comb += dev_s.eq(self.deviation)
        self.sync += If(adv, prod.eq(self.sink.data*dev_s), v1.eq(xfer), f1.eq(self.sink.first),
                        l1.eq(self.sink.last))
        # Modulation term in phase units, the phase for this sample, the ROM address.
        mod   = Signal((PB + 2, True))
        phase = Signal(PB)                               # Accumulator (FM: modulated; PM: carrier).
        phase_next = Signal(PB)
        addr_phase = Signal(PB)
        self.comb += mod.eq(rounded(prod, DW - 1))
        if mode == "fm":
            self.comb += [phase_next.eq(phase + self.phase_inc + mod), addr_phase.eq(phase_next)]
        else:
            self.comb += [phase_next.eq(phase + self.phase_inc), addr_phase.eq(phase_next + mod)]
        self.sync += If(adv & v1, phase.eq(phase_next))
        cos, sin = sincos_rom(self, addr_phase[PB - addr_bits:], adv, DW, lut_depth,
                              quarter_wave=True)
        self.sync += If(adv, self.source.valid.eq(v1), self.source.first.eq(f1),
                        self.source.last.eq(l1))
        self.comb += [self.source.i.eq(cos), self.source.q.eq(sin)]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        PB = self.phase_bits
        self._phase_inc = CSRStorage(PB, name="phase_inc",
                                     description="Carrier / centre phase increment per sample.")
        self._deviation = CSRStorage(PB, name="deviation",
            description="Phase increment (FM) / phase offset (PM) at full-scale input, in "
                        "phase-accumulator units.")
        self.comb += [self.phase_inc.eq(self._phase_inc.storage),
                      self.deviation.eq(self._deviation.storage)]

@ResetInserter()
class LiteDSPFrequencyModulator(_LiteDSPAngleModulator):
    """FM modulator: real samples to a complex exponential whose instantaneous frequency is
    ``(phase_inc + d / 2**(data_width-1) * deviation) * fs / 2**phase_bits``.

    The phase accumulates per accepted sample only (bubbles do not advance it); the cos/sin
    come from a quarter-wave ROM (``lut_depth`` entries equivalent). Latency 2. Loops back
    through :class:`~litedsp.comm.fm_demod.LiteDSPFMDemod`.
    """
    def __init__(self, data_width=16, phase_bits=32, lut_depth=1024, with_csr=True):
        _LiteDSPAngleModulator.__init__(self, "fm", data_width, phase_bits, lut_depth, with_csr)

@ResetInserter()
class LiteDSPPhaseModulator(_LiteDSPAngleModulator):
    """PM modulator: the carrier phase (``phase_inc`` per sample) plus ``d / 2**(data_width-1) *
    deviation`` (a phase offset in accumulator units, ``2**phase_bits`` = one turn). Latency 2."""
    def __init__(self, data_width=16, phase_bits=32, lut_depth=1024, with_csr=True):
        _LiteDSPAngleModulator.__init__(self, "pm", data_width, phase_bits, lut_depth, with_csr)
