#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Portable CIC (Cascaded-Integrator-Comb) decimator and interpolator.

Hogenauer CIC: N integrator stages, an R rate change, and N comb stages (differential delay
M). Integrators and combs use full-width **wrap-around** two's-complement arithmetic — the
intentional Hogenauer property whereby integrator overflow is cancelled by the combs as long
as the registers are wide enough (``data_width + ceil(N*log2(R*M))``). The output is rescaled
(round + saturate) by the CIC processing gain. R, N, M are build-time constants for exact
gain normalization. These replace the Xilinx CIC IP from the tetra design.
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, real_layout, saturated, scaled

# Helpers ------------------------------------------------------------------------------------------

# Hogenauer register growth: integrator/comb registers need ceil(N*log2(R*M)) bits over data_width.
def _growth_bits(R, N, M):
    return int(math.ceil(N*math.log2(R*M)))

def cic_shift(R, N, M=1):
    """Output rescale shift for a CIC of rate ``R`` (N stages, comb delay M): ``ceil(N*log2(R*M))``."""
    return int(math.ceil(N*math.log2(R*M)))


class _CICIntegratorPipeline(LiteXModule):
    """Elastic one-adder-per-stage integrator cascade used by the staged architectures."""
    def __init__(self, width, n_stages, with_emit=False):
        layout = iq_layout(width) + ([("emit", 1)] if with_emit else [])
        self.sink   = stream.Endpoint(layout)
        self.source = stream.Endpoint(layout)

        valid = [Signal(name=f"int_valid{k}") for k in range(n_stages)]
        ready = [Signal(name=f"int_ready{k}") for k in range(n_stages)]
        acc_i = [Signal((width, True), name=f"int_i{k}") for k in range(n_stages)]
        acc_q = [Signal((width, True), name=f"int_q{k}") for k in range(n_stages)]
        emit  = [Signal(name=f"int_emit{k}") for k in range(n_stages)] if with_emit else []

        self.comb += [
            self.sink.ready.eq(ready[0]),
            self.source.valid.eq(valid[-1]),
            self.source.i.eq(acc_i[-1]),
            self.source.q.eq(acc_q[-1]),
        ]
        if with_emit:
            self.comb += self.source.emit.eq(emit[-1])

        for k in range(n_stages - 1, -1, -1):
            downstream_ready = self.source.ready if k == n_stages - 1 else ready[k + 1]
            input_valid = self.sink.valid if k == 0 else valid[k - 1]
            input_i     = self.sink.i     if k == 0 else acc_i[k - 1]
            input_q     = self.sink.q     if k == 0 else acc_q[k - 1]
            self.comb += ready[k].eq(~valid[k] | downstream_ready)
            updates = [
                acc_i[k].eq(acc_i[k] + input_i),
                acc_q[k].eq(acc_q[k] + input_q),
            ]
            if with_emit:
                input_emit = self.sink.emit if k == 0 else emit[k - 1]
                updates.append(emit[k].eq(input_emit))
            self.sync += If(ready[k],
                valid[k].eq(input_valid),
                If(input_valid, *updates),
            )


class _CICCombPipeline(LiteXModule):
    """Elastic one-subtractor-per-stage comb cascade used by the staged architectures."""
    def __init__(self, width, n_stages, diff_delay):
        self.sink   = stream.Endpoint(iq_layout(width))
        self.source = stream.Endpoint(iq_layout(width))

        valid = [Signal(name=f"comb_valid{k}") for k in range(n_stages)]
        ready = [Signal(name=f"comb_ready{k}") for k in range(n_stages)]
        out_i = [Signal((width, True), name=f"comb_i{k}") for k in range(n_stages)]
        out_q = [Signal((width, True), name=f"comb_q{k}") for k in range(n_stages)]
        delay_i = [[Signal((width, True), name=f"comb_i{k}_z{m}")
                    for m in range(diff_delay)] for k in range(n_stages)]
        delay_q = [[Signal((width, True), name=f"comb_q{k}_z{m}")
                    for m in range(diff_delay)] for k in range(n_stages)]

        self.comb += [
            self.sink.ready.eq(ready[0]),
            self.source.valid.eq(valid[-1]),
            self.source.i.eq(out_i[-1]),
            self.source.q.eq(out_q[-1]),
        ]
        for k in range(n_stages - 1, -1, -1):
            downstream_ready = self.source.ready if k == n_stages - 1 else ready[k + 1]
            input_valid = self.sink.valid if k == 0 else valid[k - 1]
            input_i     = self.sink.i     if k == 0 else out_i[k - 1]
            input_q     = self.sink.q     if k == 0 else out_q[k - 1]
            diff_i      = Signal((width, True), name=f"comb_i{k}_diff")
            diff_q      = Signal((width, True), name=f"comb_q{k}_diff")
            self.comb += [
                ready[k].eq(~valid[k] | downstream_ready),
                diff_i.eq(input_i - delay_i[k][-1]),
                diff_q.eq(input_q - delay_q[k][-1]),
            ]
            shifts = [
                delay_i[k][0].eq(input_i),
                delay_q[k][0].eq(input_q),
            ] + [
                delay_i[k][m].eq(delay_i[k][m - 1]) for m in range(1, diff_delay)
            ] + [
                delay_q[k][m].eq(delay_q[k][m - 1]) for m in range(1, diff_delay)
            ]
            self.sync += If(ready[k],
                valid[k].eq(input_valid),
                If(input_valid,
                    out_i[k].eq(diff_i),
                    out_q[k].eq(diff_q),
                    *shifts,
                ),
            )


def _build_staged_decimator(dut, width, rate, n_stages, diff_delay, growth, data_width):
    """Build the elastic integrator -> rate change -> comb architecture."""
    dut.submodules.integrator_pipeline = integrators = _CICIntegratorPipeline(
        width, n_stages, with_emit=True)
    dut.submodules.comb_pipeline = combs = _CICCombPipeline(width, n_stages, diff_delay)

    decim  = Signal(max=rate)
    is_out = Signal()
    xfer   = Signal()
    dut.comb += [
        is_out.eq(decim == (rate - 1)),
        integrators.sink.valid.eq(dut.sink.valid),
        dut.sink.ready.eq(integrators.sink.ready),
        integrators.sink.i.eq(dut.sink.i),
        integrators.sink.q.eq(dut.sink.q),
        integrators.sink.emit.eq(is_out),
        xfer.eq(dut.sink.valid & dut.sink.ready),

        # Non-output samples drain from the integrator pipeline immediately.  A marked sample
        # transfers only when the first comb stage can accept it.
        integrators.source.ready.eq(~integrators.source.emit | combs.sink.ready),
        combs.sink.valid.eq(integrators.source.valid & integrators.source.emit),
        combs.sink.i.eq(integrators.source.i),
        combs.sink.q.eq(integrators.source.q),

        dut.source.valid.eq(combs.source.valid),
        combs.source.ready.eq(dut.source.ready),
    ]
    dut.sync += If(xfer, If(is_out, decim.eq(0)).Else(decim.eq(decim + 1)))

    out_i, _ = scaled(combs.source.i, growth, data_width)
    out_q, _ = scaled(combs.source.q, growth, data_width)
    dut.comb += [dut.source.i.eq(out_i), dut.source.q.eq(out_q)]


def _build_staged_interpolator(dut, width, rate, n_stages, diff_delay, growth, data_width):
    """Build the elastic comb -> rate expansion -> integrator architecture."""
    dut.submodules.comb_pipeline = combs = _CICCombPipeline(width, n_stages, diff_delay)
    dut.submodules.integrator_pipeline = integrators = _CICIntegratorPipeline(
        width, n_stages)

    phase = Signal(max=rate)
    first = Signal()
    emit  = Signal()
    dut.comb += [
        combs.sink.valid.eq(dut.sink.valid),
        dut.sink.ready.eq(combs.sink.ready),
        combs.sink.i.eq(dut.sink.i),
        combs.sink.q.eq(dut.sink.q),

        first.eq(phase == 0),
        integrators.sink.valid.eq(~first | combs.source.valid),
        integrators.sink.i.eq(Mux(first, combs.source.i, 0)),
        integrators.sink.q.eq(Mux(first, combs.source.q, 0)),
        combs.source.ready.eq(first & integrators.sink.ready),
        emit.eq(integrators.sink.valid & integrators.sink.ready),

        dut.source.valid.eq(integrators.source.valid),
        integrators.source.ready.eq(dut.source.ready),
    ]
    dut.sync += If(emit,
        If(phase == (rate - 1), phase.eq(0)).Else(phase.eq(phase + 1)),
    )

    out_i, _ = scaled(integrators.source.i, growth, data_width)
    out_q, _ = scaled(integrators.source.q, growth, data_width)
    dut.comb += [dut.source.i.eq(out_i), dut.source.q.eq(out_q)]

# CIC Decimator ------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCICDecimator(LiteXModule):
    """CIC decimator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N``, rescaled to width.

    ``staged=False`` retains the one-cycle compatibility architecture.  ``staged=True`` uses
    elastic one-adder/subtractor stages, sustains one input sample per clock, and preserves the
    numerical sequence while increasing no-stall latency to ``2*n_stages`` clocks.
    """
    def __init__(self, data_width=16, decimation=8, n_stages=3, diff_delay=1,
                 with_csr=True, staged=False):
        R, N, M = decimation, n_stages, diff_delay  # Literature names.
        check(R >= 2 and N >= 1 and M >= 1, "expected decimation >= 2, n_stages >= 1, diff_delay >= 1")
        check(isinstance(staged, bool), "expected staged to be a bool")
        growth = _growth_bits(R, N, M)  # Hogenauer register growth.
        W      = data_width + growth    # Full internal width (wrap-around arithmetic).
        self.data_width = data_width
        self.decimation, self.n_stages, self.diff_delay = R, N, M
        self.staged = staged
        self.growth  = growth
        self.latency = 2*N if staged else 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        if staged:
            _build_staged_decimator(self, W, R, N, M, growth, data_width)
            if with_csr:
                self.add_csr()
            return

        # Handshake.
        # ----------
        adv    = Signal()       # Output slot free or being consumed.
        is_out = Signal()       # This input completes a decimation window.
        xfer   = Signal()       # An input sample is consumed this beat.
        decim  = Signal(max=R)  # Position within the R-sample window.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            is_out.eq(decim == (R - 1)),
            self.sink.ready.eq(Mux(is_out, adv, 1)),  # Drop freely; stall only on output beats.
            xfer.eq(self.sink.valid & self.sink.ready),
        ]
        self.sync += If(xfer, If(is_out, decim.eq(0)).Else(decim.eq(decim + 1)))

        # Datapath.
        # ---------
        for field in ["i", "q"]:
            x = getattr(self.sink, field)

            # Integrators (combinational cascade, registered, wrap-around).
            integ = [Signal((W, True)) for _ in range(N)]
            nxt   = []
            prev  = x
            for k in range(N):
                nk = Signal((W, True))
                self.comb += nk.eq(integ[k] + prev)
                nxt.append(nk)
                prev = nk
            self.sync += If(xfer, *[integ[k].eq(nxt[k]) for k in range(N)])

            # Comb stages at the decimated rate (M-deep differential delay).
            combq = [[Signal((W, True)) for _ in range(M)] for _ in range(N)]
            c     = nxt[N - 1]
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
            self.sync += [
                If(xfer & is_out,
                    getattr(self.source, field).eq(out),
                ),
            ]

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
            CSRField("staged", size=1,  description="One when the registered-stage architecture is selected."),
        ])
        self.comb += [
            self._config.fields.rate.eq(self.decimation),
            self._config.fields.stages.eq(self.n_stages),
            self._config.fields.staged.eq(self.staged),
        ]

# Runtime-rate CIC Decimator -----------------------------------------------------------------------

@ResetInserter()
class LiteDSPCICDecimatorRuntime(LiteXModule):
    """CIC decimator with a runtime-settable rate (datapath sized for ``r_max``).

    Unlike :class:`LiteDSPCICDecimator` (whose R/N/M are build-time so the output rescale is exact), this
    variant exposes ``rate`` and ``shift`` as runtime controls so the decimation ratio can change
    without a rebuild. Size the integrator/comb datapath for the maximum ratio ``r_max``; the host
    sets ``rate`` and the matching ``shift = cic_shift(rate, N, M)`` together so the processing gain
    ``(rate*M)**N`` stays normalized. The Hogenauer wrap-around property holds for any
    ``rate <= r_max``. Operates on a real (``iq=False``) or complex (``iq=True``) stream.
    """
    def __init__(self, data_width=16, r_max=8192, n_stages=4, diff_delay=1, iq=True, with_csr=True):
        N, M = n_stages, diff_delay  # Literature names.
        check(r_max >= 2 and N >= 1 and M >= 1, "expected r_max >= 2, n_stages >= 1, diff_delay >= 1")
        self.data_width = data_width
        self.r_max      = r_max
        self.n_stages, self.diff_delay = N, M
        self.latency    = 1
        growth          = _growth_bits(r_max, N, M)
        W               = data_width + growth
        self.growth     = growth

        fields = ["i", "q"] if iq else ["data"]
        layout = iq_layout(data_width) if iq else real_layout(data_width)
        self.sink   = stream.Endpoint(layout)
        self.source = stream.Endpoint(layout)

        self.rate  = Signal(bits_for(r_max), reset=8)                    # Decimation factor R (runtime).
        self.shift = Signal(bits_for(growth), reset=cic_shift(8, N, M))  # Rescale shift; keep = cic_shift(rate, N, M).

        # Decimation-window strobes (e.g. to drive a coherent side-channel accumulator).
        self.sample_ce = Signal()   # An input sample is consumed this beat.
        self.out_ce    = Signal()   # An output sample is emitted this beat.

        # # #

        # Handshake.
        # ----------
        adv    = Signal()                 # Output slot free or being consumed.
        is_out = Signal()                 # This input completes a decimation window.
        xfer   = Signal()                 # An input sample is consumed this beat.
        decim  = Signal(bits_for(r_max))  # Position within the rate-sample window.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            is_out.eq(decim == (self.rate - 1)),
            self.sink.ready.eq(Mux(is_out, adv, 1)),  # Drop freely; stall only on output beats.
            xfer.eq(self.sink.valid & self.sink.ready),
            self.sample_ce.eq(xfer),
            self.out_ce.eq(xfer & is_out),
        ]
        self.sync += If(xfer, If(is_out, decim.eq(0)).Else(decim.eq(decim + 1)))

        # Datapath.
        # ---------
        bias = Signal(W)
        self.comb += bias.eq(Mux(self.shift == 0, 0, (1 << self.shift) >> 1))  # Round-half-up bias.

        for field in fields:
            x = getattr(self.sink, field)

            # Integrators (combinational cascade, registered, wrap-around).
            integ = [Signal((W, True)) for _ in range(N)]
            nxt, prev = [], x
            for k in range(N):
                nk = Signal((W, True))
                self.comb += nk.eq(integ[k] + prev)
                nxt.append(nk); prev = nk
            self.sync += If(xfer, *[integ[k].eq(nxt[k]) for k in range(N)])

            # Comb stages at the decimated rate (M-deep differential delay).
            combq = [[Signal((W, True)) for _ in range(M)] for _ in range(N)]
            c, ins = nxt[N-1], []
            for k in range(N):
                d = Signal((W, True))
                self.comb += d.eq(c - combq[k][M-1])
                ins.append(c); c = d
            self.sync += If(xfer & is_out,
                *[combq[k][0].eq(ins[k]) for k in range(N)],
                *[combq[k][m].eq(combq[k][m-1]) for k in range(N) for m in range(1, M)])

            # Runtime rescale: round-half-up shift, then saturate to the output width.
            shifted = Signal((W, True))
            self.comb += shifted.eq((c + bias) >> self.shift)
            self.sync += If(xfer & is_out, getattr(self.source, field).eq(saturated(shifted, data_width)))

        # Output.
        # -------
        self.sync += If(xfer & is_out, self.source.valid.eq(1)).Elif(adv, self.source.valid.eq(0))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._rate  = CSRStorage(len(self.rate),  reset=self.rate.reset.value,
            description="Decimation factor R (2..r_max).")
        self._shift = CSRStorage(len(self.shift), reset=self.shift.reset.value,
            description="Output rescale shift; set to cic_shift(R, N, M) for the chosen rate.")
        self.comb += [self.rate.eq(self._rate.storage), self.shift.eq(self._shift.storage)]

# CIC Interpolator ---------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPCICInterpolator(LiteXModule):
    """CIC interpolator by ``R`` (N stages, comb delay M). Gain ``(R*M)**N / R``, rescaled.

    ``staged=False`` retains the one-cycle compatibility architecture.  ``staged=True`` uses
    elastic one-subtractor/adder stages, preserves the numerical output sequence, and increases
    no-stall latency to ``2*n_stages`` clocks while retaining one output sample per clock.
    """
    def __init__(self, data_width=16, interpolation=8, n_stages=3, diff_delay=1,
                 with_csr=True, staged=False):
        R, N, M = interpolation, n_stages, diff_delay  # Literature names.
        check(R >= 2 and N >= 1 and M >= 1, "expected decimation >= 2, n_stages >= 1, diff_delay >= 1")
        check(isinstance(staged, bool), "expected staged to be a bool")
        growth = int(math.ceil(N*math.log2(R*M) - math.log2(R)))  # Net gain (R*M)**N / R (zero-stuff loss).
        W      = data_width + _growth_bits(R, N, M)               # Registers still need full Hogenauer growth.
        self.data_width = data_width
        self.interpolation, self.n_stages, self.diff_delay = R, N, M
        self.staged = staged
        self.growth  = growth
        self.latency = 2*N if staged else 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        if staged:
            _build_staged_interpolator(self, W, R, N, M, growth, data_width)
            if with_csr:
                self.add_csr()
            return

        # Control.
        # --------
        adv   = Signal()        # Output slot free or being consumed.
        first = Signal()        # Start of an output group (consume one input).
        phase = Signal(max=R)   # Position within the R-output group.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            first.eq(phase == 0),
            self.sink.ready.eq(first & adv),
        ]
        take = Signal()         # Consuming a new input sample this beat.
        self.comb += take.eq(first & self.sink.valid & adv)
        emit = Signal()         # Producing an output sample this beat.
        self.comb += emit.eq(adv & (~first | self.sink.valid))
        self.sync += If(emit,
            If(phase == (R - 1), phase.eq(0)).Else(phase.eq(phase + 1)),
        )

        # Datapath.
        # ---------
        for field in ["i", "q"]:
            x = getattr(self.sink, field)

            # Comb stages at the input rate (run once per input sample).
            combq = [[Signal((W, True)) for _ in range(M)] for _ in range(N)]
            c     = Signal((W, True))
            self.comb += c.eq(x)
            ins   = []
            cval  = c
            for k in range(N):
                d = Signal((W, True))
                self.comb += d.eq(cval - combq[k][M - 1])
                ins.append(cval)
                cval = d
            self.sync += If(take, *[
                combq[k][0].eq(ins[k]) for k in range(N)
            ], *[
                combq[k][m].eq(combq[k][m - 1]) for k in range(N) for m in range(1, M)
            ])

            # Rate expand (zero-stuff) + integrators at the output rate.
            integ = [Signal((W, True)) for _ in range(N)]
            stuff = Signal((W, True))
            self.comb += stuff.eq(Mux(take, cval, 0))   # Comb output on group start, else zero.
            nxt   = []
            prev  = stuff
            for k in range(N):
                nk = Signal((W, True))
                self.comb += nk.eq(integ[k] + prev)
                nxt.append(nk)
                prev = nk
            self.sync += If(emit, *[integ[k].eq(nxt[k]) for k in range(N)])

            out, _ = scaled(nxt[N - 1], growth, data_width)  # Remove the net CIC gain (round + saturate).
            self.sync += If(emit, getattr(self.source, field).eq(out))

        # Output.
        # -------
        # Hold valid until accepted; clear on drain unless a new sample lands.
        self.sync += If(emit, self.source.valid.eq(1)).Elif(adv, self.source.valid.eq(0))

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("rate",   size=16, description="Interpolation factor R."),
            CSRField("stages", size=8,  description="CIC stages N."),
            CSRField("staged", size=1,  description="One when the registered-stage architecture is selected."),
        ])
        self.comb += [
            self._config.fields.rate.eq(self.interpolation),
            self._config.fields.stages.eq(self.n_stages),
            self._config.fields.staged.eq(self.staged),
        ]
