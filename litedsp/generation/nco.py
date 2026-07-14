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

from litedsp.common import check, iq_layout

# NCO ----------------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPNCO(LiteXModule):
    """Numerically-Controlled Oscillator (a.k.a. DDS).

    Generates a complex exponential ``cos(2*pi*f*t) + j*sin(...)`` from a phase accumulator and
    a pair of cos/sin lookup ROMs. The output frequency is set by ``phase_inc`` (Hz =
    ``phase_inc * f_clk / 2**phase_bits``).

    The source is free-running: ``valid`` is asserted once the first sample is in the output
    register and stays asserted; the phase only advances when a sample is accepted
    (``valid & ready``), so downstream backpressure never drops or repeats samples.
    """
    def __init__(self, phase_bits=32, data_width=16, lut_depth=1024, quarter_wave=False, with_csr=True):
        self.phase_bits   = phase_bits
        self.data_width   = data_width
        self.quarter_wave = quarter_wave
        self.latency      = 1                            # Cos/Sin ROM output register.
        self.phase_inc    = Signal(phase_bits)           # Phase increment (control input).
        self.source       = stream.Endpoint(iq_layout(data_width))

        # # #

        addr_bits = int(math.log2(lut_depth))
        check((1 << addr_bits) == lut_depth, "lut_depth must be a power of two.")

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
        addr = phase_next[phase_bits-addr_bits:]         # Top phase bits.

        valid = Signal()
        self.sync += If(ce, valid.eq(1))
        self.comb += self.source.valid.eq(valid)

        if not quarter_wave:
            # Full-period cos/sin ROMs.
            cos_rom = Memory(data_width, lut_depth, init=self.build_lut(lut_depth, data_width, math.cos))
            sin_rom = Memory(data_width, lut_depth, init=self.build_lut(lut_depth, data_width, math.sin))
            cos_rp  = cos_rom.get_port(has_re=True)
            sin_rp  = sin_rom.get_port(has_re=True)
            self.specials += cos_rom, sin_rom, cos_rp, sin_rp
            self.comb += [
                cos_rp.re.eq(ce), cos_rp.adr.eq(addr),
                sin_rp.re.eq(ce), sin_rp.adr.eq(addr),
                self.source.i.eq(cos_rp.dat_r),
                self.source.q.eq(sin_rp.dat_r),
            ]
        else:
            # Quarter-wave: one sine table (depth N/4+1) reconstructs cos and sin (4x ROM saving).
            quarter = lut_depth//4
            scale   = (1 << (data_width - 1)) - 1
            qt = Memory(data_width, quarter + 1,
                init=[int(round(math.sin(2*math.pi*j/lut_depth)*scale)) & ((1 << data_width)-1)
                      for j in range(quarter + 1)])
            sp, cp = qt.get_port(has_re=True), qt.get_port(has_re=True)
            self.specials += qt, sp, cp
            idx  = addr[:addr_bits-2]                    # Within-quadrant index.
            q_s  = addr[addr_bits-2:]                    # Sine quadrant (2 bits).
            q_c  = Signal(2)
            self.comb += q_c.eq(q_s + 1)                 # cos(x) = sin(x + pi/2).
            neg_s, neg_c = Signal(), Signal()
            self.comb += [
                sp.re.eq(ce), sp.adr.eq(Mux(q_s[0], quarter - idx, idx)), neg_s.eq(q_s[1]),
                cp.re.eq(ce), cp.adr.eq(Mux(q_c[0], quarter - idx, idx)), neg_c.eq(q_c[1]),
            ]
            neg_s_d, neg_c_d = Signal(), Signal()
            self.sync += If(ce, neg_s_d.eq(neg_s), neg_c_d.eq(neg_c))
            self.comb += [
                self.source.i.eq(Mux(neg_c_d, -cp.dat_r, cp.dat_r)),   # cos.
                self.source.q.eq(Mux(neg_s_d, -sp.dat_r, sp.dat_r)),   # sin.
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
