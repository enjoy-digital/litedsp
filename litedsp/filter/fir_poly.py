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

from litedsp.common import check, iq_layout, scaled

# Helpers ------------------------------------------------------------------------------------------

# Next power of two >= n (memory depths, so address pointers wrap for free).
def _pow2_ceil(n):
    return 1 << (max(1, n - 1)).bit_length()

# Decimating FIR -----------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPFIRDecimator(LiteXModule):
    """Decimate-by-R complex FIR with a single time-shared MAC per I/Q.

    Collects R input samples then MACs the N taps over the sample window to produce one output
    (``y[m] = sum_t c[t]·x[mR-t]``), round + saturate. Coefficients are signed Q1.(W-1).
    """
    def __init__(self, n_taps=32, decimation=8, data_width=16, coefficients=None, shift=None, with_csr=True):
        R = decimation  # Literature name.
        check(n_taps >= 1 and R >= 1, "expected n_taps >= 1 and decimation >= 1")
        if shift is None:
            shift = data_width - 1
        if coefficients is None:
            coefficients = [(1 << (data_width - 1)) - 1] + [0]*(n_taps - 1)
        check(len(coefficients) == n_taps, "expected len(coefficients) == n_taps")
        self.n_taps     = n_taps
        self.decimation = R
        self.data_width = data_width
        self.cycles_per_output = R + n_taps + 1
        self.latency = n_taps + 1
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Memories.
        # ---------
        depth = _pow2_ceil(n_taps + R)                        # Sample buffer depth (pow2: free pointer wrap).
        mask  = depth - 1
        acc_w = 2*data_width + (n_taps - 1).bit_length() + 1  # Product + log2(n_taps) accumulation growth.

        # Migen cannot build an address Signal for a depth-one Memory. Keep the public one-tap
        # configuration useful by padding the physical ROM; the FSM still visits only tap 0.
        crom_depth = max(2, n_taps)
        coeff_init = [c & ((1 << data_width) - 1) for c in coefficients] + [0]*(crom_depth - n_taps)
        crom = Memory(data_width, crom_depth, init=coeff_init)
        mi   = Memory(data_width, depth)
        mq   = Memory(data_width, depth)
        crp  = crom.get_port(async_read=True)
        cwp  = crom.get_port(write_capable=True)          # Runtime coefficient reload.
        wip, wqp = mi.get_port(write_capable=True), mq.get_port(write_capable=True)
        rip, rqp = mi.get_port(async_read=True),    mq.get_port(async_read=True)
        self.specials += crom, mi, mq, crp, cwp, wip, wqp, rip, rqp

        # Coefficient Reload.
        # -------------------
        # Coefficient-reload interface (write taps sequentially; default = the build-time taps).
        self.coeff_data = Signal(data_width)
        self.coeff_we   = Signal()
        self.coeff_rst  = Signal()
        cwptr = Signal(max=n_taps) if n_taps > 1 else Signal()
        self.comb += [cwp.adr.eq(cwptr), cwp.dat_w.eq(self.coeff_data), cwp.we.eq(self.coeff_we)]
        self.sync += If(self.coeff_rst, cwptr.eq(0)).Elif(self.coeff_we,
            If(cwptr == (n_taps - 1), cwptr.eq(0)).Else(cwptr.eq(cwptr + 1)))

        # Signals.
        # --------
        wptr  = Signal(max=depth)                     # Sample write pointer.
        decim = Signal(max=R) if R > 1 else Signal()  # Position within the R-sample window.
        t     = Signal(max=n_taps + 1)                # Tap index (MAC step / coefficient address).
        radr  = Signal(max=depth)                     # History read pointer (walks back from newest).
        acc_i, acc_q = Signal((acc_w, True)), Signal((acc_w, True))
        prod_i = Signal((2*data_width, True))
        prod_q = Signal((2*data_width, True))
        ci = Signal((data_width, True))               # Signed views of the I/Q/coeff read data.
        cq = Signal((data_width, True))
        cc = Signal((data_width, True))
        self.comb += [
            wip.adr.eq(wptr), wqp.adr.eq(wptr),
            wip.dat_w.eq(self.sink.i), wqp.dat_w.eq(self.sink.q),
            rip.adr.eq(radr), rqp.adr.eq(radr), crp.adr.eq(t),
            ci.eq(rip.dat_r), cq.eq(rqp.dat_r), cc.eq(crp.dat_r),
        ]

        # FSM.
        # ----
        self.fsm = fsm = FSM(reset_state="LOAD")
        # LOAD: store input samples; the R-th sample of a window kicks off a MAC pass.
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
        # MAC: register one product per cycle while accumulating the preceding tap. Splitting
        # the multiplier from the accumulator feedback is one extra drain cycle per output,
        # but preserves the serial-MAC area and bit-exact arithmetic while removing the
        # multiplier-plus-wide-adder critical path.
        fsm.act("MAC",
            NextValue(prod_i, ci*cc),
            NextValue(prod_q, cq*cc),
            If(t != 0,
                NextValue(acc_i, acc_i + prod_i),
                NextValue(acc_q, acc_q + prod_q),
            ),
            NextValue(radr, radr - 1),
            NextValue(t, t + 1),
            If(t == (n_taps - 1), NextState("MAC_DRAIN")),
        )
        fsm.act("MAC_DRAIN",
            NextValue(acc_i, acc_i + prod_i),
            NextValue(acc_q, acc_q + prod_q),
            NextState("EMIT"),
        )
        out_i, _ = scaled(acc_i, shift, data_width)
        out_q, _ = scaled(acc_q, shift, data_width)
        # EMIT: present the rescaled result; upstream stays stalled until it is accepted.
        fsm.act("EMIT",
            self.source.valid.eq(1),
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            If(self.source.ready, NextState("LOAD")),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("taps", size=16, description="FIR taps N."),
            CSRField("rate", size=16, description="Decimation factor R."),
        ])
        self._coeff_rst = CSRStorage(1, name="coeff_reset",
            description="Reset the coefficient write pointer to tap 0 (write to strobe).")
        self._coeff = CSRStorage(self.data_width, name="coeff",
            description="Write the next FIR coefficient (auto-incrementing tap index).")
        self.comb += [
            self._config.fields.taps.eq(self.n_taps), self._config.fields.rate.eq(self.decimation),
            self.coeff_rst.eq(self._coeff_rst.re),
            self.coeff_data.eq(self._coeff.storage),
            self.coeff_we.eq(self._coeff.re),
        ]

# Interpolating FIR --------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPFIRInterpolator(LiteXModule):
    """Interpolate-by-L complex FIR with a single time-shared MAC per I/Q (polyphase).

    For each input it emits L outputs, output ``p`` computed from polyphase sub-filter
    ``c[p::L]`` over the recent inputs (``y[nL+p] = sum_k c[p+kL]·x[n-k]``), round + saturate.
    """
    def __init__(self, n_taps=32, interpolation=8, data_width=16, coefficients=None, shift=None, with_csr=True):
        L = interpolation  # Literature name.
        check(n_taps >= 1 and L >= 1, "expected n_taps >= 1 and interpolation >= 1")
        if shift is None:
            shift = data_width - 1
        if coefficients is None:
            coefficients = [(1 << (data_width - 1)) - 1] + [0]*(n_taps - 1)
        check(len(coefficients) == n_taps, "expected len(coefficients) == n_taps")
        self.n_taps        = n_taps
        self.interpolation = L
        sub         = (n_taps + L - 1)//L          # Taps per polyphase sub-filter.
        self.sub    = sub
        self.cycles_per_output = sub + 1
        self.latency = n_taps
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Memories.
        # ---------
        depth = _pow2_ceil(sub + 1)                                     # Sample buffer depth (pow2 wrap).
        acc_w = 2*data_width + (sub if sub > 1 else 1).bit_length() + 1  # Product + log2(sub) growth.

        # Coefficients laid out by phase: crom[p*sub + k] = c[p + k*L] (0 if out of range).
        coeff_init = []
        for p in range(L):
            for k in range(sub):
                idx = p + k*L
                coeff_init.append((coefficients[idx] if idx < n_taps else 0) & ((1 << data_width) - 1))
        # As above, preserve the valid n_taps=interpolation=1 boundary by padding the ROM.
        crom_depth = max(2, L*sub)
        coeff_init += [0]*(crom_depth - len(coeff_init))
        crom = Memory(data_width, crom_depth, init=coeff_init)
        mi   = Memory(data_width, depth)
        mq   = Memory(data_width, depth)
        crp  = crom.get_port(async_read=True)
        wip, wqp = mi.get_port(write_capable=True), mq.get_port(write_capable=True)
        rip, rqp = mi.get_port(async_read=True),    mq.get_port(async_read=True)
        self.specials += crom, mi, mq, crp, wip, wqp, rip, rqp

        # Signals.
        # --------
        wptr  = Signal(max=depth)                     # Sample write pointer.
        phase = Signal(max=L) if L > 1 else Signal()  # Polyphase index p (output within the group of L).
        k     = Signal(max=sub + 1)                   # Tap index within the sub-filter.
        radr  = Signal(max=depth)                     # History read pointer (walks back from newest).
        acc_i, acc_q = Signal((acc_w, True)), Signal((acc_w, True))
        ci = Signal((data_width, True))               # Signed views of the I/Q/coeff read data.
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

        # FSM.
        # ----
        self.fsm = fsm = FSM(reset_state="LOAD")
        # LOAD: store one input, then compute its L polyphase outputs.
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
        # MAC: one sub-filter tap per cycle (sub taps per output sample).
        fsm.act("MAC",
            NextValue(acc_i, acc_i + ci*cc),
            NextValue(acc_q, acc_q + cq*cc),
            NextValue(radr, radr - 1),
            NextValue(k, k + 1),
            If(k == (sub - 1), NextState("EMIT")),
        )
        # EMIT: present output p; loop back through MAC for the next phase, re-scanning the window.
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

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("taps", size=16, description="FIR taps N."),
            CSRField("rate", size=16, description="Interpolation factor L."),
        ])
        self.comb += [self._config.fields.taps.eq(self.n_taps), self._config.fields.rate.eq(self.interpolation)]
