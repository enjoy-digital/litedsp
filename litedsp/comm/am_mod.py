#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Amplitude modulator (DSB full carrier) onto a complex baseband or an embedded carrier."""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common         import check, real_layout, iq_layout, rounded, saturated
from litedsp.generation.nco import sincos_rom

# AM Modulator -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPAMModulator(LiteXModule):
    """AM modulator: ``envelope = 2**(dw-2) * (1 + m * x)`` with the modulation index ``m``
    (unsigned Q1.(dw-1), reset 1.0), a half-scale carrier so ``m <= 1`` never overflows.

    ``carrier="baseband"``: I = envelope, Q = 0 (feed a DUC), latency 2; ``carrier="nco"``: the
    envelope multiplies an internal carrier (``phase_inc`` per sample, quarter-wave ROM), I / Q =
    envelope x cos / sin rounded to ``data_width``, latency 4. Loops back through
    :class:`~litedsp.comm.am_demod.LiteDSPAMDemod`.
    """
    def __init__(self, data_width=16, carrier="baseband", phase_bits=32, lut_depth=1024,
                 with_csr=True):
        check(carrier in ("baseband", "nco"), "expected carrier in ('baseband', 'nco')")
        check(lut_depth & (lut_depth - 1) == 0 and lut_depth >= 16,
              "expected lut_depth a power of two >= 16")
        self.data_width = data_width
        self.carrier    = carrier
        self.phase_bits = phase_bits
        self.latency    = 2 if carrier == "baseband" else 4
        self.sink   = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.index     = Signal(data_width, reset=(1 << (data_width - 1)))   # Q1.(dw-1): 1.0.
        self.phase_inc = Signal(phase_bits)

        # # #

        DW = data_width
        adv, xfer = Signal(), Signal()
        self.comb += [adv.eq(self.source.ready | ~self.source.valid), self.sink.ready.eq(adv),
                      xfer.eq(self.sink.valid & adv)]
        # S1: m * x (registered), tags.
        idx_s = Signal((DW + 1, True))
        prod  = Signal((2*DW + 1, True))
        v1, f1, l1 = Signal(), Signal(), Signal()
        self.comb += idx_s.eq(self.index)
        self.sync += If(adv, prod.eq(self.sink.data*idx_s), v1.eq(xfer), f1.eq(self.sink.first),
                        l1.eq(self.sink.last))
        env = Signal((DW + 1, True))
        self.comb += env.eq((1 << (DW - 2)) + rounded(prod, DW))     # 0 .. 2^(dw-1) - 1 for m <= 1.
        envc = Signal((DW, True))
        self.comb += envc.eq(saturated(env, DW))
        if carrier == "baseband":
            self.sync += If(adv,
                self.source.valid.eq(v1), self.source.first.eq(f1), self.source.last.eq(l1),
                self.source.i.eq(envc), self.source.q.eq(0),
            )
        else:
            addr_bits = int(math.log2(lut_depth))
            phase = Signal(phase_bits)
            phase_next = Signal(phase_bits)
            self.comb += phase_next.eq(phase + self.phase_inc)
            # ROM read at S0 -> S1 aligned with prod.
            self.sync += If(adv & xfer, phase.eq(phase_next))
            cos, sin = sincos_rom(self, phase_next[phase_bits - addr_bits:], adv, DW, lut_depth,
                                  quarter_wave=True)
            # S2: envelope x carrier (registered); S3: rounded output.
            pi, pq = Signal((2*DW, True)), Signal((2*DW, True))
            e2 = Signal((DW, True))
            v2, f2, l2 = Signal(), Signal(), Signal()
            self.sync += If(adv, pi.eq(envc*cos), pq.eq(envc*sin), v2.eq(v1), f2.eq(f1), l2.eq(l1))
            self.sync += If(adv,
                self.source.valid.eq(v2), self.source.first.eq(f2), self.source.last.eq(l2),
                self.source.i.eq(saturated(rounded(pi, DW - 1), DW)),
                self.source.q.eq(saturated(rounded(pq, DW - 1), DW)),
            )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._index = CSRStorage(self.data_width, reset=self.index.reset.value, name="index",
            description=f"Modulation index (unsigned Q1.{self.data_width - 1}, 1.0 = "
                        f"{1 << (self.data_width - 1)}).")
        self.comb += self.index.eq(self._index.storage)
        if self.carrier == "nco":
            self._phase_inc = CSRStorage(self.phase_bits, name="phase_inc",
                                         description="Carrier phase increment per sample.")
            self.comb += self.phase_inc.eq(self._phase_inc.storage)
