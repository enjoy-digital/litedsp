#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Parallel (multi-sample-per-cycle) CIC decimator.

The gigasample rate-change: ``n_samples`` I/Q samples enter per beat, the integrator cascade
is unrolled ``n_samples`` serial steps per clock (wrap-around Hogenauer arithmetic, exactly the
serial recurrence), and with ``R`` a multiple of ``n_samples`` the decimation snapshot always
lands on a beat's last lane — so the output is a standard *serial* I/Q stream at ``1/R`` of the
sample rate, bit-identical to :class:`~litedsp.filter.cic.LiteDSPCICDecimator` on the flattened lanes.
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common     import check, iq_layout, iq_lanes, scaled
from litedsp.filter.cic import _growth_bits

# Parallel CIC Decimator ---------------------------------------------------------------------------

@ResetInserter()
class LiteDSPParallelCICDecimator(LiteXModule):
    """CIC decimator by ``R`` over ``n_samples``-lane beats; serial output stream."""
    def __init__(self, n_samples=4, data_width=16, decimation=8, n_stages=3, diff_delay=1, with_csr=True):
        R, N, M = decimation, n_stages, diff_delay  # Literature names.
        check(R >= 2 and N >= 1 and M >= 1, "expected decimation >= 2, n_stages >= 1, diff_delay >= 1")
        check(R >= n_samples and R % n_samples == 0,
            "decimation must be a multiple of n_samples (output rate <= 1 sample/cycle)")
        growth = _growth_bits(R, N, M)
        W      = data_width + growth
        self.n_samples  = n_samples
        self.data_width = data_width
        self.decimation, self.n_stages, self.diff_delay = R, N, M
        self.growth  = growth
        self.latency = 1
        self.sink   = stream.Endpoint(iq_layout(data_width, n_samples))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Handshake.
        # ----------
        beats_per_out = R // n_samples  # R samples = R/n_samples input beats per output.

        adv    = Signal()  # Output slot free or being consumed.
        is_out = Signal()  # This beat completes a decimation window.
        xfer   = Signal()  # An input beat (n_samples samples) is consumed this cycle.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(Mux(is_out, adv, 1)),  # Drop freely; stall only on output beats.
            xfer.eq(self.sink.valid & self.sink.ready),
        ]
        if beats_per_out == 1:
            self.comb += is_out.eq(1)
        else:
            decim = Signal(max=beats_per_out)  # Beat position within the decimation window.
            self.comb += is_out.eq(decim == (beats_per_out - 1))
            self.sync += If(xfer, If(is_out, decim.eq(0)).Else(decim.eq(decim + 1)))

        # Datapath.
        # ---------
        for field in ["i", "q"]:
            lanes = [l[0] if field == "i" else l[1]
                     for l in iq_lanes(self.sink, data_width, n_samples)]

            # Integrators: the serial cascade unrolled n_samples steps per beat (wrap-around).
            integ = [Signal((W, True)) for _ in range(N)]
            state = list(integ)
            for j in range(n_samples):                          # Serial sample steps, unrolled.
                x = Signal((data_width, True))
                self.comb += x.eq(lanes[j])                     # Reinterpret lane bits as signed.
                prev, step = x, []
                for k in range(N):
                    sk = Signal((W, True))
                    self.comb += sk.eq(state[k] + prev)
                    step.append(sk)
                    prev = sk
                state = step
            self.sync += If(xfer, *[integ[k].eq(state[k]) for k in range(N)])

            # Comb stages at the decimated rate (identical to the serial CIC; input = the
            # integrator value at the beat's last lane, which is the sample where the serial
            # version takes its snapshot).
            combq = [[Signal((W, True)) for _ in range(M)] for _ in range(N)]
            c     = state[N - 1]
            ins   = []
            for k in range(N):
                d = Signal((W, True))
                self.comb += d.eq(c - combq[k][M - 1])
                ins.append(c)
                c = d
            self.sync += If(xfer & is_out, *[
                combq[k][0].eq(ins[k]) for k in range(N)
            ], *[
                combq[k][m].eq(combq[k][m - 1]) for k in range(N) for m in range(1, M)
            ])

            out, _ = scaled(c, growth, data_width)  # Remove the 2**growth CIC gain (round + saturate).
            self.sync += If(xfer & is_out, getattr(self.source, field).eq(out))

        # Output.
        # -------
        # Hold valid until accepted; clear on drain unless a new sample lands.
        self.sync += [
            If(xfer & is_out, self.source.valid.eq(1)).Elif(adv, self.source.valid.eq(0)),
        ]

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("rate",   size=16, description="Decimation factor R."),
            CSRField("stages", size=8,  description="CIC stages N."),
            CSRField("lanes",  size=8,  description="Input samples per beat."),
        ])
        self.comb += [
            self._config.fields.rate.eq(self.decimation),
            self._config.fields.stages.eq(self.n_stages),
            self._config.fields.lanes.eq(self.n_samples),
        ]
