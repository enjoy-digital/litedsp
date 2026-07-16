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
from litedsp.filter.cic import _growth_bits, _CICCombPipeline

# Staged helpers -----------------------------------------------------------------------------------

class _ParallelCICIntegratorPipeline(LiteXModule):
    """Elastic vector integrators with a logarithmic-depth lane-prefix network per stage."""
    def __init__(self, width, n_samples, n_stages):
        layout = iq_layout(width, n_samples) + [("emit", 1)]
        self.sink   = stream.Endpoint(layout)
        self.source = stream.Endpoint(layout)

        valid = [Signal(name=f"pint_valid{k}") for k in range(n_stages)]
        ready = [Signal(name=f"pint_ready{k}") for k in range(n_stages)]
        data_i = [Signal(width*n_samples, name=f"pint_i{k}") for k in range(n_stages)]
        data_q = [Signal(width*n_samples, name=f"pint_q{k}") for k in range(n_stages)]
        emit   = [Signal(name=f"pint_emit{k}") for k in range(n_stages)]
        acc_i  = [Signal((width, True), name=f"pint_i{k}_state") for k in range(n_stages)]
        acc_q  = [Signal((width, True), name=f"pint_q{k}_state") for k in range(n_stages)]

        self.comb += [
            self.sink.ready.eq(ready[0]),
            self.source.valid.eq(valid[-1]),
            self.source.i.eq(data_i[-1]),
            self.source.q.eq(data_q[-1]),
            self.source.emit.eq(emit[-1]),
        ]

        def prefix(values, name):
            """Inclusive Kogge-Stone scan: log2(P) add levels rather than a P-lane chain."""
            level, stride, depth = values, 1, 0
            while stride < n_samples:
                nxt = []
                for lane in range(n_samples):
                    value = Signal((width, True), name=f"{name}_l{depth}_{lane}")
                    if lane < stride:
                        self.comb += value.eq(level[lane])
                    else:
                        self.comb += value.eq(level[lane] + level[lane - stride])
                    nxt.append(value)
                level, stride, depth = nxt, stride << 1, depth + 1
            return level

        for k in range(n_stages - 1, -1, -1):
            downstream_ready = self.source.ready if k == n_stages - 1 else ready[k + 1]
            input_valid = self.sink.valid if k == 0 else valid[k - 1]
            input_i = self.sink.i if k == 0 else data_i[k - 1]
            input_q = self.sink.q if k == 0 else data_q[k - 1]
            input_emit = self.sink.emit if k == 0 else emit[k - 1]
            self.comb += ready[k].eq(~valid[k] | downstream_ready)

            outs = {}
            for field, packed, acc in (("i", input_i, acc_i[k]), ("q", input_q, acc_q[k])):
                lanes = []
                for lane in range(n_samples):
                    value = Signal((width, True), name=f"pint_{field}{k}_in{lane}")
                    self.comb += value.eq(packed[lane*width:(lane + 1)*width])
                    lanes.append(value)
                sums = prefix(lanes, f"pint_{field}{k}")
                outputs = []
                for lane, value in enumerate(sums):
                    output = Signal((width, True), name=f"pint_{field}{k}_out{lane}")
                    self.comb += output.eq(acc + value)
                    outputs.append(output)
                outs[field] = outputs

            self.sync += If(ready[k],
                valid[k].eq(input_valid),
                If(input_valid,
                    data_i[k].eq(Cat(*outs["i"])),
                    data_q[k].eq(Cat(*outs["q"])),
                    emit[k].eq(input_emit),
                    acc_i[k].eq(outs["i"][-1]),
                    acc_q[k].eq(outs["q"][-1]),
                ),
            )


def _build_staged_parallel_decimator(dut, width, n_samples, rate, n_stages,
                                     diff_delay, growth, data_width):
    """Build vector-prefix integrators -> beat-rate change -> scalar comb pipeline."""
    dut.submodules.integrator_pipeline = integrators = _ParallelCICIntegratorPipeline(
        width, n_samples, n_stages)
    dut.submodules.comb_pipeline = combs = _CICCombPipeline(width, n_stages, diff_delay)

    beats_per_out = rate // n_samples
    phase = Signal(max=max(2, beats_per_out))
    is_out = Signal()
    xfer = Signal()
    if beats_per_out == 1:
        dut.comb += is_out.eq(1)
    else:
        dut.comb += is_out.eq(phase == beats_per_out - 1)

    wide_i, wide_q = [], []
    for lane, (src_i, src_q) in enumerate(iq_lanes(dut.sink, data_width, n_samples)):
        signed_i = Signal((data_width, True), name=f"pcic_i_signed{lane}")
        signed_q = Signal((data_width, True), name=f"pcic_q_signed{lane}")
        dst_i = Signal((width, True), name=f"pcic_i_wide{lane}")
        dst_q = Signal((width, True), name=f"pcic_q_wide{lane}")
        dut.comb += [
            signed_i.eq(src_i), signed_q.eq(src_q),
            dst_i.eq(signed_i), dst_q.eq(signed_q),
        ]
        wide_i.append(dst_i)
        wide_q.append(dst_q)

    last_i, last_q = iq_lanes(integrators.source, width, n_samples)[-1]
    dut.comb += [
        integrators.sink.valid.eq(dut.sink.valid),
        dut.sink.ready.eq(integrators.sink.ready),
        integrators.sink.i.eq(Cat(*wide_i)),
        integrators.sink.q.eq(Cat(*wide_q)),
        integrators.sink.emit.eq(is_out),
        xfer.eq(dut.sink.valid & dut.sink.ready),

        # Unmarked beats drain; marked beats wait for the output-rate comb pipeline.
        integrators.source.ready.eq(~integrators.source.emit | combs.sink.ready),
        combs.sink.valid.eq(integrators.source.valid & integrators.source.emit),
        combs.sink.i.eq(last_i),
        combs.sink.q.eq(last_q),

        dut.source.valid.eq(combs.source.valid),
        combs.source.ready.eq(dut.source.ready),
    ]
    if beats_per_out > 1:
        dut.sync += If(xfer, If(is_out, phase.eq(0)).Else(phase.eq(phase + 1)))

    out_i, _ = scaled(combs.source.i, growth, data_width)
    out_q, _ = scaled(combs.source.q, growth, data_width)
    dut.comb += [dut.source.i.eq(out_i), dut.source.q.eq(out_q)]

# Parallel CIC Decimator ---------------------------------------------------------------------------

@ResetInserter()
class LiteDSPParallelCICDecimator(LiteXModule):
    """CIC decimator by ``R`` over ``n_samples``-lane beats; serial output stream.

    ``staged=False`` keeps the one-cycle fully unrolled compatibility datapath. ``staged=True``
    registers each CIC stage and uses a logarithmic-depth lane-prefix scan, sustaining one input
    beat per clock with ``2*n_stages`` clocks of no-stall latency.
    """
    def __init__(self, n_samples=4, data_width=16, decimation=8, n_stages=3, diff_delay=1,
        with_csr=True, staged=False):
        R, N, M = decimation, n_stages, diff_delay  # Literature names.
        check(R >= 2 and N >= 1 and M >= 1, "expected decimation >= 2, n_stages >= 1, diff_delay >= 1")
        check(R >= n_samples and R % n_samples == 0,
            "decimation must be a multiple of n_samples (output rate <= 1 sample/cycle)")
        check(isinstance(staged, bool), "expected staged to be a bool")
        growth = _growth_bits(R, N, M)
        W      = data_width + growth
        self.n_samples  = n_samples
        self.data_width = data_width
        self.decimation, self.n_stages, self.diff_delay = R, N, M
        self.staged = staged
        self.growth  = growth
        self.latency = 2*N if staged else 1
        self.sink   = stream.Endpoint(iq_layout(data_width, n_samples))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        if staged:
            _build_staged_parallel_decimator(self, W, n_samples, R, N, M, growth, data_width)
            if with_csr:
                self.add_csr()
            return

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
            CSRField("staged", size=1,  description="One for registered vector-prefix stages."),
        ])
        self.comb += [
            self._config.fields.rate.eq(self.decimation),
            self._config.fields.stages.eq(self.n_stages),
            self._config.fields.lanes.eq(self.n_samples),
            self._config.fields.staged.eq(self.staged),
        ]
