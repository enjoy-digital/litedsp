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

from litedsp.common import iq_layout

# NCO ----------------------------------------------------------------------------------------------

@ResetInserter()
class NCO(LiteXModule):
    """Numerically-Controlled Oscillator (a.k.a. DDS).

    Generates a complex exponential ``cos(2*pi*f*t) + j*sin(...)`` from a phase accumulator and
    a pair of cos/sin lookup ROMs. The output frequency is set by ``phase_inc`` (Hz =
    ``phase_inc * f_clk / 2**phase_bits``).

    The source is free-running: ``valid`` is asserted once the first sample is in the output
    register and stays asserted; the phase only advances when a sample is accepted
    (``valid & ready``), so downstream backpressure never drops or repeats samples.
    """
    def __init__(self, phase_bits=32, data_width=16, lut_depth=1024, with_csr=True):
        self.phase_bits = phase_bits
        self.data_width = data_width
        self.latency    = 1                              # Cos/Sin ROM output register.
        self.phase_inc  = Signal(phase_bits)             # Phase increment (control input).
        self.source     = stream.Endpoint(iq_layout(data_width))

        # # #

        addr_bits = int(math.log2(lut_depth))
        assert (1 << addr_bits) == lut_depth, "lut_depth must be a power of two."

        # Cos/Sin ROMs.
        # -------------
        cos_rom = Memory(data_width, lut_depth, init=self.build_lut(lut_depth, data_width, math.cos))
        sin_rom = Memory(data_width, lut_depth, init=self.build_lut(lut_depth, data_width, math.sin))
        cos_rp  = cos_rom.get_port(has_re=True)
        sin_rp  = sin_rom.get_port(has_re=True)
        self.specials += cos_rom, sin_rom, cos_rp, sin_rp

        # Phase Accumulator.
        # ------------------
        phase      = Signal(phase_bits)
        phase_next = Signal(phase_bits)
        ce         = Signal()  # Advance when output can accept a new sample.
        self.comb += [
            ce.eq(self.source.ready | ~self.source.valid),
            phase_next.eq(phase + self.phase_inc),
        ]
        self.sync += If(ce, phase.eq(phase_next))

        # ROM Lookup (top phase bits → address, registered output).
        # ---------------------------------------------------------
        self.comb += [
            cos_rp.re.eq(ce), cos_rp.adr.eq(phase_next[phase_bits-addr_bits:]),
            sin_rp.re.eq(ce), sin_rp.adr.eq(phase_next[phase_bits-addr_bits:]),
        ]

        # Output (valid asserts after the first lookup and stays asserted).
        # ----------------------------------------------------------------
        valid = Signal()
        self.sync += If(ce, valid.eq(1))
        self.comb += [
            self.source.valid.eq(valid),
            self.source.i.eq(cos_rp.dat_r),
            self.source.q.eq(sin_rp.dat_r),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    @staticmethod
    def build_lut(depth, data_width, func):
        """Return a signed two's-complement LUT for *func* (cos/sin) over one full period."""
        scale = (1 << (data_width - 1)) - 1  # Full-scale Q1.(N-1).
        mask  = (1 << data_width) - 1
        return [int(round(func(2*math.pi*i/depth)*scale)) & mask for i in range(depth)]

    def add_csr(self):
        self._phase_inc = CSRStorage(self.phase_bits, description="Phase increment (sets output frequency).")
        self.comb += self.phase_inc.eq(self._phase_inc.storage)
