#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled

# IQ Imbalance Correction --------------------------------------------------------------------------

@ResetInserter()
class LiteDSPIQBalance(LiteXModule):
    """Correct I/Q gain & phase imbalance with a 2x2 matrix, plus an estimator for calibration.

    Datapath: ``I' = I``, ``Q' = (c1*I + c2*Q) >> frac`` (round + saturate). The defaults
    (c1=0, c2=1.0) pass through. Estimator accumulators ``E[I^2], E[Q^2], E[I*Q]`` over a
    window are exposed (status) so firmware can compute c1, c2 (Gram-Schmidt) — keeping the
    divide/sqrt off the datapath (portable, cheap).
    """
    def __init__(self, data_width=16, coeff_frac=14, window_log2=14, with_csr=True):
        self.data_width = data_width
        self.coeff_frac = coeff_frac
        self.latency    = 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.c1 = Signal((data_width, True), reset=0)                 # Q?.frac.
        self.c2 = Signal((data_width, True), reset=1 << coeff_frac)   # 1.0.
        acc_w   = 2*data_width + window_log2                          # Product + window bit growth.
        self.acc_ii = Signal(acc_w)                                   # Latched sum I**2 (last window).
        self.acc_qq = Signal(acc_w)                                   # Latched sum Q**2 (last window).
        self.acc_iq = Signal((acc_w, True))                           # Latched sum I*Q (signed).

        # # #

        # Handshake.
        # ----------
        adv  = Signal()  # Pipeline drains (output slot free or being consumed).
        xfer = Signal()  # A sample is consumed this beat.
        i, q = self.sink.i, self.sink.q
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Correction datapath.
        # --------------------
        # Q' = (c1*I + c2*Q) >> coeff_frac with round-half-up + saturation; I passes through.
        qc, _ = scaled(self.c1*i + self.c2*q, coeff_frac, data_width)
        self.sync += If(adv,
            self.source.i.eq(i),
            self.source.q.eq(qc),
            self.source.valid.eq(self.sink.valid),
        )

        # Estimator over a window (latched for firmware).
        # -----------------------------------------------
        count = Signal(window_log2 + 1)
        ii    = Signal(acc_w)
        qq    = Signal(acc_w)
        iq    = Signal((acc_w, True))
        self.sync += If(xfer,  # Accumulate on accepted samples only.
            If(count == ((1 << window_log2) - 1),
                self.acc_ii.eq(ii + i*i),  # Latch with the final sample included.
                self.acc_qq.eq(qq + q*q),
                self.acc_iq.eq(iq + i*q),
                ii.eq(0), qq.eq(0), iq.eq(0), count.eq(0),
            ).Else(
                ii.eq(ii + i*i), qq.eq(qq + q*q), iq.eq(iq + i*q), count.eq(count + 1),
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._c1 = CSRStorage(self.data_width, reset=0, name="c1",
            description="Correction coeff c1 (Q?.frac).")
        self._c2 = CSRStorage(self.data_width, reset=1 << self.coeff_frac, name="c2",
            description="Correction coeff c2 (Q?.frac).")
        self._ii = CSRStatus(self.acc_ii.nbits, name="acc_ii", description="Sum I^2 (last window).")
        self._qq = CSRStatus(self.acc_qq.nbits, name="acc_qq", description="Sum Q^2 (last window).")
        self._iq = CSRStatus(self.acc_iq.nbits, name="acc_iq", description="Sum I*Q (last window).")
        self.comb += [
            self.c1.eq(self._c1.storage), self.c2.eq(self._c2.storage),
            self._ii.status.eq(self.acc_ii), self._qq.status.eq(self.acc_qq),
            self._iq.status.eq(self.acc_iq),
        ]
