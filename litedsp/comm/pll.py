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
    """
    def __init__(self, data_width=16, phase_bits=32, lut_depth=1024,
        kp_shift=6, ki_shift=14, decision_directed=False, detector=None, with_csr=True):
        if detector is None:
            detector = "bpsk" if decision_directed else "pll"
        check(detector in ("pll", "bpsk", "qpsk"),
            "detector must be 'pll', 'bpsk', or 'qpsk'.")
        self.detector = detector
        self.decision_directed = detector != "pll"
        self.sink    = stream.Endpoint(iq_layout(data_width))
        self.source  = stream.Endpoint(iq_layout(data_width))
        self.latency = 1

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

        # Derotate: d = input * exp(-j*phase) = (i*cos + q*sin) + j(q*cos - i*sin).
        # -------------------------------------------------------------------------
        i, q = self.sink.i, self.sink.q
        d_i, _ = scaled(i*cos + q*sin, data_width - 1, data_width)
        d_q, _ = scaled(q*cos - i*sin, data_width - 1, data_width)

        # Phase error, scaled up into phase-rate units so the PI loop spans the full range.
        # ---------------------------------------------------------------------------------
        err = Signal((data_width + 2, True))  # Headroom for negate and QPSK's two terms.
        if detector == "bpsk":
            self.comb += err.eq(Mux(d_i >= 0, d_q, -d_q))     # Costas (BPSK).
        elif detector == "qpsk":
            self.comb += err.eq(
                Mux(d_i >= 0, d_q, -d_q) - Mux(d_q >= 0, d_i, -d_i))  # QPSK DD.
        else:
            self.comb += err.eq(d_q)                          # PLL (tone / residual carrier).
        err_scaled = Signal((phase_bits + 2, True))
        self.comb += err_scaled.eq(err << (phase_bits - data_width))

        # PI Loop.
        # --------
        self.pi = LiteDSPPILoop(error_width=phase_bits + 2, out_width=phase_bits + 2,
            kp_shift=kp_shift, ki_shift=ki_shift)
        self.comb += [self.pi.error.eq(err_scaled), self.pi.ce.eq(xfer)]
        self.sync += If(xfer, phase.eq(phase + self.pi.out))  # PI output = instantaneous frequency word.

        # Output.
        # -------
        self.sync += If(adv,
            self.source.i.eq(d_i),
            self.source.q.eq(d_q),
            self.source.valid.eq(self.sink.valid),
        )

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
