#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Polyphase decimating / interpolating FIR filters (resource-optimal, serial-MAC).

Instead of N parallel multipliers running at the high sample rate, these use a single
time-shared multiply-accumulate per I/Q running at the fabric clock — the resource win of
polyphase filtering when the clock is faster than the sample rate. The decimator MACs the N
taps over the sample history once per output; the interpolator MACs one N/L-tap polyphase
sub-filter per output sample. Throughput is bounded by the MAC length (documented via
``self.cycles_per_output``); backpressure stalls the input while MACing.
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import iq_layout, scaled

# Helpers ------------------------------------------------------------------------------------------

def _pow2_ceil(n):
    return 1 << (max(1, n - 1)).bit_length()

# Decimating FIR -----------------------------------------------------------------------------------

@ResetInserter()
class FIRDecimator(LiteXModule):
    """Decimate-by-R complex FIR with a single time-shared MAC per I/Q.

    Collects R input samples then MACs the N taps over the sample window to produce one output
    (``y[m] = sum_t c[t]·x[mR-t]``), round + saturate. Coefficients are signed Q1.(W-1).
    """
    def __init__(self, n_taps, R, data_width=16, coefficients=None, shift=None, with_csr=True):
        assert n_taps >= 1 and R >= 1
        if shift is None:
            shift = data_width - 1
        if coefficients is None:
            coefficients = [(1 << (data_width - 1)) - 1] + [0]*(n_taps - 1)
        assert len(coefficients) == n_taps
        self.n_taps = n_taps
        self.R      = R
        self.cycles_per_output = R + n_taps
        self.latency = n_taps
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        depth = _pow2_ceil(n_taps + R)
        mask  = depth - 1
        acc_w = 2*data_width + (n_taps - 1).bit_length() + 1

        crom = Memory(data_width, n_taps, init=[c & ((1 << data_width) - 1) for c in coefficients])
        mi   = Memory(data_width, depth)
        mq   = Memory(data_width, depth)
        crp  = crom.get_port(async_read=True)
        wip, wqp = mi.get_port(write_capable=True), mq.get_port(write_capable=True)
        rip, rqp = mi.get_port(async_read=True),    mq.get_port(async_read=True)
        self.specials += crom, mi, mq, crp, wip, wqp, rip, rqp

        wptr  = Signal(max=depth)
        decim = Signal(max=R) if R > 1 else Signal()
        t     = Signal(max=n_taps + 1)
        radr  = Signal(max=depth)
        acc_i, acc_q = Signal((acc_w, True)), Signal((acc_w, True))
        ci = Signal((data_width, True))
        cq = Signal((data_width, True))
        cc = Signal((data_width, True))
        self.comb += [
            wip.adr.eq(wptr), wqp.adr.eq(wptr),
            wip.dat_w.eq(self.sink.i), wqp.dat_w.eq(self.sink.q),
            rip.adr.eq(radr), rqp.adr.eq(radr), crp.adr.eq(t),
            ci.eq(rip.dat_r), cq.eq(rqp.dat_r), cc.eq(crp.dat_r),
        ]

        self.fsm = fsm = FSM(reset_state="LOAD")
        fsm.act("LOAD",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                wip.we.eq(1), wqp.we.eq(1),
                NextValue(wptr, wptr + 1),
                If(decim == (R - 1),
                    NextValue(decim, 0),
                    NextValue(t, 0),
                    NextValue(acc_i, 0), NextValue(acc_q, 0),
                    NextValue(radr, wptr),       # Newest sample (just written at wptr).
                    NextState("MAC"),
                ).Else(
                    NextValue(decim, decim + 1),
                )
            )
        )
        fsm.act("MAC",
            NextValue(acc_i, acc_i + ci*cc),
            NextValue(acc_q, acc_q + cq*cc),
            NextValue(radr, radr - 1),
            NextValue(t, t + 1),
            If(t == (n_taps - 1), NextState("EMIT")),
        )
        out_i, _ = scaled(acc_i, shift, data_width)
        out_q, _ = scaled(acc_q, shift, data_width)
        fsm.act("EMIT",
            self.source.valid.eq(1),
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            If(self.source.ready, NextState("LOAD")),
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("taps", size=16, description="FIR taps N."),
            CSRField("rate", size=16, description="Decimation factor R."),
        ])
        self.comb += [self._config.fields.taps.eq(self.n_taps), self._config.fields.rate.eq(self.R)]

# Interpolating FIR --------------------------------------------------------------------------------

@ResetInserter()
class FIRInterpolator(LiteXModule):
    """Interpolate-by-L complex FIR with a single time-shared MAC per I/Q (polyphase).

    For each input it emits L outputs, output ``p`` computed from polyphase sub-filter
    ``c[p::L]`` over the recent inputs (``y[nL+p] = sum_k c[p+kL]·x[n-k]``), round + saturate.
    """
    def __init__(self, n_taps, L, data_width=16, coefficients=None, shift=None, with_csr=True):
        assert n_taps >= 1 and L >= 1
        if shift is None:
            shift = data_width - 1
        if coefficients is None:
            coefficients = [(1 << (data_width - 1)) - 1] + [0]*(n_taps - 1)
        assert len(coefficients) == n_taps
        self.n_taps = n_taps
        self.L      = L
        sub         = (n_taps + L - 1)//L          # Taps per polyphase sub-filter.
        self.sub    = sub
        self.cycles_per_output = sub + 1
        self.latency = n_taps
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        depth = _pow2_ceil(sub + 1)
        acc_w = 2*data_width + (sub if sub > 1 else 1).bit_length() + 1

        # Coefficients laid out by phase: crom[p*sub + k] = c[p + k*L] (0 if out of range).
        coeff_init = []
        for p in range(L):
            for k in range(sub):
                idx = p + k*L
                coeff_init.append((coefficients[idx] if idx < n_taps else 0) & ((1 << data_width) - 1))
        crom = Memory(data_width, L*sub, init=coeff_init)
        mi   = Memory(data_width, depth)
        mq   = Memory(data_width, depth)
        crp  = crom.get_port(async_read=True)
        wip, wqp = mi.get_port(write_capable=True), mq.get_port(write_capable=True)
        rip, rqp = mi.get_port(async_read=True),    mq.get_port(async_read=True)
        self.specials += crom, mi, mq, crp, wip, wqp, rip, rqp

        wptr  = Signal(max=depth)
        phase = Signal(max=L) if L > 1 else Signal()
        k     = Signal(max=sub + 1)
        radr  = Signal(max=depth)
        acc_i, acc_q = Signal((acc_w, True)), Signal((acc_w, True))
        ci = Signal((data_width, True))
        cq = Signal((data_width, True))
        cc = Signal((data_width, True))
        self.comb += [
            wip.adr.eq(wptr), wqp.adr.eq(wptr),
            wip.dat_w.eq(self.sink.i), wqp.dat_w.eq(self.sink.q),
            rip.adr.eq(radr), rqp.adr.eq(radr),
            crp.adr.eq(phase*sub + k),
            ci.eq(rip.dat_r), cq.eq(rqp.dat_r), cc.eq(crp.dat_r),
        ]

        out_i, _ = scaled(acc_i, shift, data_width)
        out_q, _ = scaled(acc_q, shift, data_width)

        self.fsm = fsm = FSM(reset_state="LOAD")
        fsm.act("LOAD",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                wip.we.eq(1), wqp.we.eq(1),
                NextValue(wptr, wptr + 1),
                NextValue(phase, 0),
                NextValue(k, 0),
                NextValue(acc_i, 0), NextValue(acc_q, 0),
                NextValue(radr, wptr),     # Newest sample.
                NextState("MAC"),
            )
        )
        fsm.act("MAC",
            NextValue(acc_i, acc_i + ci*cc),
            NextValue(acc_q, acc_q + cq*cc),
            NextValue(radr, radr - 1),
            NextValue(k, k + 1),
            If(k == (sub - 1), NextState("EMIT")),
        )
        fsm.act("EMIT",
            self.source.valid.eq(1),
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            If(self.source.ready,
                If(phase == (L - 1),
                    NextState("LOAD"),
                ).Else(
                    NextValue(phase, phase + 1),
                    NextValue(k, 0),
                    NextValue(acc_i, 0), NextValue(acc_q, 0),
                    NextValue(radr, wptr - 1),   # Re-scan window for the next phase.
                    NextState("MAC"),
                )
            )
        )

        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("taps", size=16, description="FIR taps N."),
            CSRField("rate", size=16, description="Interpolation factor L."),
        ])
        self.comb += [self._config.fields.taps.eq(self.n_taps), self._config.fields.rate.eq(self.L)]
