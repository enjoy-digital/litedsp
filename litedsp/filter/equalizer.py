#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from functools import reduce

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled, saturated

# Complex LMS Equalizer ----------------------------------------------------------------------------

@ResetInserter()
class LMSEqualizer(LiteXModule):
    """Adaptive complex FIR equalizer (LMS), trained or decision-directed.

    Filters ``x`` with ``n_taps`` complex weights and adapts them to minimize ``|d - y|``:
    ``w_k += mu * e * conj(x[n-k])`` with ``e = d - y``. The sink carries both the input
    (``i``,``q``) and the desired symbol (``d_i``,``d_q``); drive ``train`` low to freeze the
    weights (feed a slicer's decision back as ``d`` for decision-directed operation). ``mu_shift``
    sets the (inverse) step size; weights are Q.``wfrac`` with the center tap initialized to 1.0.
    """
    def __init__(self, n_taps=5, data_width=16, wfrac=14, wint=4, mu_shift=20, with_csr=True):
        assert n_taps >= 1
        self.n_taps = n_taps
        self.mu_shift = mu_shift
        # Weight = Q``wint``.``wfrac`` signed. ``wint`` integer bits bound the weight magnitude
        # (saturated below); keeping ww = wint + wfrac <= 18 makes each weight*sample a single
        # 18x18 DSP. Stable equalizers have O(1) weights, so a few integer bits suffice.
        ww = wint + wfrac                                # Weight register width.
        self.sink = stream.Endpoint([
            ("i", (data_width, True)), ("q", (data_width, True)),
            ("d_i", (data_width, True)), ("d_q", (data_width, True)),
        ])
        self.source = stream.Endpoint(iq_layout(data_width))
        self.train  = Signal(reset=1)
        self.latency = 1

        # # #

        adv  = Signal()
        xfer = Signal()
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Input shift register: tap 0 = current sample, taps 1.. = history.
        regs_r = [Signal((data_width, True)) for _ in range(n_taps - 1)]
        regs_i = [Signal((data_width, True)) for _ in range(n_taps - 1)]
        xr = [self.sink.i] + regs_r
        xi = [self.sink.q] + regs_i
        if n_taps > 1:
            self.sync += If(xfer,
                regs_r[0].eq(self.sink.i), regs_i[0].eq(self.sink.q),
                *[regs_r[k].eq(regs_r[k-1]) for k in range(1, n_taps - 1)],
                *[regs_i[k].eq(regs_i[k-1]) for k in range(1, n_taps - 1)],
            )

        wr = [Signal((ww, True)) for _ in range(n_taps)]
        wi = [Signal((ww, True)) for _ in range(n_taps)]
        wr[n_taps//2].reset = 1 << wfrac                 # Center tap = 1.0.

        # Complex FIR: y = sum w_k * x_k.
        acc_w = 2*ww
        yi_full = reduce(lambda a, b: a + b, [wr[k]*xr[k] - wi[k]*xi[k] for k in range(n_taps)])
        yq_full = reduce(lambda a, b: a + b, [wr[k]*xi[k] + wi[k]*xr[k] for k in range(n_taps)])
        yi = scaled(yi_full, wfrac, data_width)[0]
        yq = scaled(yq_full, wfrac, data_width)[0]

        # Error and LMS update: w_k += mu * e * conj(x_k).
        ei = Signal((data_width + 1, True))
        eq = Signal((data_width + 1, True))
        self.comb += [ei.eq(self.sink.d_i - yi), eq.eq(self.sink.d_q - yq)]
        for k in range(n_taps):
            self.sync += If(xfer & self.train,
                wr[k].eq(saturated(wr[k] + ((ei*xr[k] + eq*xi[k]) >> mu_shift), ww)),
                wi[k].eq(saturated(wi[k] + ((eq*xr[k] - ei*xi[k]) >> mu_shift), ww)),
            )

        self.sync += If(adv,
            self.source.i.eq(yi),
            self.source.q.eq(yq),
            self.source.valid.eq(self.sink.valid),
        )

        if with_csr:
            self._train = CSRStorage(1, reset=1, name="train", description="Enable LMS adaptation.")
            self.comb += self.train.eq(self._train.storage)
