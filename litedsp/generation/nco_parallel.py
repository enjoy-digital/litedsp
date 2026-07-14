#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common         import iq_layout, iq_lanes
from litedsp.generation.nco import LiteDSPNCO

import math

# Parallel NCO ---------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPParallelNCO(LiteXModule):
    """NCO emitting ``n_samples`` consecutive samples per beat (multi-sample-per-cycle datapaths).

    Same phase/LUT scheme as :class:`~litedsp.generation.nco.LiteDSPNCO`: the accumulator steps
    ``n_samples * phase_inc`` per accepted beat and lane ``k`` addresses its own cos/sin ROM
    pair at ``phase + (k+1)*phase_inc``, so the flattened lane sequence is bit-identical to the
    serial NCO output at the same ``phase_inc`` (n ROM pairs traded for n samples/cycle).
    """
    def __init__(self, n_samples=2, phase_bits=32, data_width=16, lut_depth=1024, with_csr=True):
        assert n_samples >= 1
        self.n_samples  = n_samples
        self.phase_bits = phase_bits
        self.data_width = data_width
        self.latency    = 1                              # Cos/Sin ROM output register.
        self.phase_inc  = Signal(phase_bits)             # Phase increment (control input).
        self.source     = stream.Endpoint(iq_layout(data_width, n_samples))

        # # #

        addr_bits = int(math.log2(lut_depth))
        assert (1 << addr_bits) == lut_depth, "lut_depth must be a power of two."

        # Phase Accumulator (steps n_samples increments per beat).
        # --------------------------------------------------------
        phase = Signal(phase_bits)
        ce    = Signal()
        self.comb += ce.eq(self.source.ready | ~self.source.valid)
        self.sync += If(ce, phase.eq(phase + self.phase_inc*n_samples))

        valid = Signal()
        self.sync += If(ce, valid.eq(1))
        self.comb += self.source.valid.eq(valid)

        # Per-lane cos/sin ROMs at phase + (k+1)*phase_inc.
        # -------------------------------------------------
        cos_init = LiteDSPNCO.build_lut(lut_depth, data_width, math.cos)
        sin_init = LiteDSPNCO.build_lut(lut_depth, data_width, math.sin)
        for k, (i, q) in enumerate(iq_lanes(self.source, data_width, n_samples)):
            lane_phase = Signal(phase_bits)
            self.comb += lane_phase.eq(phase + self.phase_inc*(k + 1))
            cos_rom = Memory(data_width, lut_depth, init=cos_init)
            sin_rom = Memory(data_width, lut_depth, init=sin_init)
            cos_rp  = cos_rom.get_port(has_re=True)
            sin_rp  = sin_rom.get_port(has_re=True)
            self.specials += cos_rom, sin_rom, cos_rp, sin_rp
            self.comb += [
                cos_rp.re.eq(ce), cos_rp.adr.eq(lane_phase[phase_bits - addr_bits:]),
                sin_rp.re.eq(ce), sin_rp.adr.eq(lane_phase[phase_bits - addr_bits:]),
                i.eq(cos_rp.dat_r),
                q.eq(sin_rp.dat_r),
            ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._phase_inc = CSRStorage(self.phase_bits, description="Phase increment (sets output frequency).")
        self.comb += self.phase_inc.eq(self._phase_inc.storage)
