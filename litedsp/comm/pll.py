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

from litedsp.common   import iq_layout, scaled
from litedsp.control  import LiteDSPPILoop

# Carrier Recovery Loop ----------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCarrierLoop(LiteXModule):
    """Carrier recovery: derotate the input with an internal NCO driven by a PI loop.

    Each sample is derotated by ``exp(-j*phase)``; the phase error feeds a :class:`LiteDSPPILoop` whose
    output advances the NCO phase (a 2nd-order loop that locks frequency and phase). The
    derotated (baseband) signal is the output. ``decision_directed=False`` (PLL) uses the
    derotated imaginary part as the error (residual-carrier / tone); ``True`` (Costas) uses
    ``sign(I)*Q`` (suppressed-carrier BPSK).
    """
    def __init__(self, data_width=16, phase_bits=32, lut_depth=1024,
        kp_shift=6, ki_shift=14, decision_directed=False, with_csr=True):
        self.decision_directed = decision_directed
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.latency = 1

        # # #

        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # NCO phase accumulator + cos/sin LUT (async read).
        addr_bits = int(math.log2(lut_depth))
        scale     = (1 << (data_width - 1)) - 1
        cos_init  = [int(round(math.cos(2*math.pi*n/lut_depth)*scale)) & ((1 << data_width) - 1)
                     for n in range(lut_depth)]
        sin_init  = [int(round(math.sin(2*math.pi*n/lut_depth)*scale)) & ((1 << data_width) - 1)
                     for n in range(lut_depth)]
        cos_rom, sin_rom = Memory(data_width, lut_depth, init=cos_init), Memory(data_width, lut_depth, init=sin_init)
        cos_rp, sin_rp   = cos_rom.get_port(async_read=True), sin_rom.get_port(async_read=True)
        self.specials += cos_rom, sin_rom, cos_rp, sin_rp

        phase = Signal(phase_bits)
        cos   = Signal((data_width, True))
        sin   = Signal((data_width, True))
        self.comb += [
            cos_rp.adr.eq(phase[phase_bits - addr_bits:]),
            sin_rp.adr.eq(phase[phase_bits - addr_bits:]),
            cos.eq(cos_rp.dat_r), sin.eq(sin_rp.dat_r),
        ]

        # Derotate: d = input * exp(-j*phase) = (i*cos + q*sin) + j(q*cos - i*sin).
        i, q = self.sink.i, self.sink.q
        d_i, _ = scaled(i*cos + q*sin, data_width - 1, data_width)
        d_q, _ = scaled(q*cos - i*sin, data_width - 1, data_width)

        # Phase error, scaled up into phase-rate units so the PI loop spans the full range.
        err = Signal((data_width + 1, True))
        if decision_directed:
            self.comb += err.eq(Mux(d_i >= 0, d_q, -d_q))     # Costas (BPSK).
        else:
            self.comb += err.eq(d_q)                          # PLL (tone / residual carrier).
        err_scaled = Signal((phase_bits + 2, True))
        self.comb += err_scaled.eq(err << (phase_bits - data_width))

        self.pi = LiteDSPPILoop(error_width=phase_bits + 2, out_width=phase_bits + 2,
            kp_shift=kp_shift, ki_shift=ki_shift)
        self.comb += [self.pi.error.eq(err_scaled), self.pi.ce.eq(xfer)]
        self.sync += If(xfer, phase.eq(phase + self.pi.out))

        self.sync += If(adv,
            self.source.i.eq(d_i),
            self.source.q.eq(d_q),
            self.source.valid.eq(self.sink.valid),
        )

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
        LiteDSPCarrierLoop.__init__(self, decision_directed=True, **kwargs)
