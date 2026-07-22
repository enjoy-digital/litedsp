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

    ``architecture="classic"`` registers the product before the accumulator. The
    ``"pipelined"`` architecture also registers the RAM operands, adding one drain clock per
    output while separating address/read routing from the multiplier input.

    ``prune_zeros=True`` builds the MAC schedule and coefficient memory from only the non-zero
    build-time taps. The omitted positions remain structural zeros and cannot be changed by
    runtime coefficient reload; use the default rectangular schedule when every position must
    remain writable.
    """
    def __init__(self, n_taps=32, decimation=8, data_width=16, coefficients=None, shift=None,
        with_csr=True, architecture="classic", prune_zeros=False):
        R = decimation  # Literature name.
        check(n_taps >= 1 and R >= 1, "expected n_taps >= 1 and decimation >= 1")
        check(architecture in ("classic", "pipelined"),
            "architecture must be 'classic' or 'pipelined'.")
        if shift is None:
            shift = data_width - 1
        if coefficients is None:
            coefficients = [(1 << (data_width - 1)) - 1] + [0]*(n_taps - 1)
        check(len(coefficients) == n_taps, "expected len(coefficients) == n_taps")
        active_taps = [n for n, c in enumerate(coefficients) if c != 0] if prune_zeros else list(range(n_taps))
        check(active_taps, "cannot prune an all-zero FIR")
        self.n_taps     = n_taps
        self.n_mac_taps = len(active_taps)
        self.decimation = R
        self.data_width = data_width
        self.architecture = architecture
        self.prune_zeros = prune_zeros
        pipeline = int(architecture == "pipelined")
        self.cycles_per_output = R + self.n_mac_taps + 1 + pipeline
        self.latency = n_taps + 1 + pipeline
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
        crom_depth = max(2, self.n_mac_taps)
        coeff_init = [coefficients[n] & ((1 << data_width) - 1) for n in active_taps]
        coeff_init += [0]*(crom_depth - self.n_mac_taps)
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
        # Coefficient-reload interface (write scheduled taps sequentially; default = the
        # build-time taps). With zero pruning, omitted positions remain structural zeros.
        self.coeff_data = Signal(data_width)
        self.coeff_we   = Signal()
        self.coeff_rst  = Signal()
        cwptr = Signal(max=self.n_mac_taps) if self.n_mac_taps > 1 else Signal()
        self.comb += [cwp.adr.eq(cwptr), cwp.dat_w.eq(self.coeff_data), cwp.we.eq(self.coeff_we)]
        self.sync += If(self.coeff_rst, cwptr.eq(0)).Elif(self.coeff_we,
            If(cwptr == (self.n_mac_taps - 1), cwptr.eq(0)).Else(cwptr.eq(cwptr + 1)))

        # Signals.
        # --------
        wptr  = Signal(max=depth)                     # Sample write pointer.
        decim = Signal(max=R) if R > 1 else Signal()  # Position within the R-sample window.
        t     = Signal(max=self.n_mac_taps + 1)       # Scheduled MAC step / coefficient address.
        newest = Signal(max=depth)                    # History address of the newest input.
        # Pad the constant table because ``t`` advances one past the last entry for the drain
        # state. That value is never accumulated, but keeping it defined avoids a wide default
        # mux arm in generated RTL.
        tap_offset = Array([Constant(n, bits_for(depth - 1)) for n in active_taps] +
            [Constant(0, bits_for(depth - 1))])
        acc_i, acc_q = Signal((acc_w, True)), Signal((acc_w, True))
        prod_i = Signal((2*data_width, True))
        prod_q = Signal((2*data_width, True))
        ci = Signal((data_width, True))               # Signed views of the I/Q/coeff read data.
        cq = Signal((data_width, True))
        cc = Signal((data_width, True))
        self.comb += [
            wip.adr.eq(wptr), wqp.adr.eq(wptr),
            wip.dat_w.eq(self.sink.i), wqp.dat_w.eq(self.sink.q),
            rip.adr.eq(newest - tap_offset[t]), rqp.adr.eq(newest - tap_offset[t]), crp.adr.eq(t),
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
                    NextValue(newest, wptr),     # Newest sample (just written at wptr).
                    NextState("MAC"),
                ).Else(
                    NextValue(decim, decim + 1),
                )
            )
        )
        # MAC: register one product per cycle while accumulating the preceding tap. Splitting
        # the multiplier from the accumulator feedback preserves the serial-MAC area and
        # bit-exact arithmetic while removing the multiplier-plus-wide-adder critical path.
        if architecture == "classic":
            fsm.act("MAC",
                NextValue(prod_i, ci*cc),
                NextValue(prod_q, cq*cc),
                If(t != 0,
                    NextValue(acc_i, acc_i + prod_i),
                    NextValue(acc_q, acc_q + prod_q),
                ),
                NextValue(t, t + 1),
                If(t == (self.n_mac_taps - 1), NextState("MAC_DRAIN")),
            )
            fsm.act("MAC_DRAIN",
                NextValue(acc_i, acc_i + prod_i),
                NextValue(acc_q, acc_q + prod_q),
                NextState("EMIT"),
            )
        else:
            # Register the asynchronous sample/coefficient reads before the DSP multiplier.
            # Two fill clocks and two drain states keep one tap issued per MAC clock; only one
            # extra clock is added versus the classic product-only pipeline.
            operand_i = Signal((data_width, True))
            operand_q = Signal((data_width, True))
            operand_c = Signal((data_width, True))
            fsm.act("MAC",
                NextValue(operand_i, ci),
                NextValue(operand_q, cq),
                NextValue(operand_c, cc),
                NextValue(prod_i, operand_i*operand_c),
                NextValue(prod_q, operand_q*operand_c),
                If(t >= 2,
                    NextValue(acc_i, acc_i + prod_i),
                    NextValue(acc_q, acc_q + prod_q),
                ),
                NextValue(t, t + 1),
                If(t == (self.n_mac_taps - 1), NextState("MAC_DRAIN_PRODUCT")),
            )
            drain_product = [
                NextValue(prod_i, operand_i*operand_c),
                NextValue(prod_q, operand_q*operand_c),
            ]
            if self.n_mac_taps > 1:
                drain_product += [
                    NextValue(acc_i, acc_i + prod_i),
                    NextValue(acc_q, acc_q + prod_q),
                ]
            fsm.act("MAC_DRAIN_PRODUCT", *drain_product, NextState("MAC_DRAIN_ACC"))
            fsm.act("MAC_DRAIN_ACC",
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
            description="Write the next scheduled FIR coefficient (auto-incrementing MAC slot; "
                        "structurally pruned zero positions are not writable).")
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

    ``architecture="classic"`` performs the multiply and accumulator update in one clock.
    ``architecture="pipelined"`` registers the product and drains the final product in one
    additional clock per output, shortening the memory/multiply/accumulate critical path while
    retaining the same two-multiplier serial-MAC area and bit-exact output sequence.

    ``prune_zeros=True`` builds a compact, phase-specific MAC schedule from the non-zero
    build-time taps. Every phase must retain at least one tap. This is intended for structurally
    sparse filters such as half-band rate changers.
    """
    def __init__(self, n_taps=32, interpolation=8, data_width=16, coefficients=None, shift=None,
        with_csr=True, architecture="classic", prune_zeros=False):
        L = interpolation  # Literature name.
        check(n_taps >= 1 and L >= 1, "expected n_taps >= 1 and interpolation >= 1")
        check(architecture in ("classic", "pipelined"),
            "architecture must be 'classic' or 'pipelined'.")
        if shift is None:
            shift = data_width - 1
        if coefficients is None:
            coefficients = [(1 << (data_width - 1)) - 1] + [0]*(n_taps - 1)
        check(len(coefficients) == n_taps, "expected len(coefficients) == n_taps")
        self.n_taps        = n_taps
        self.interpolation = L
        sub         = (n_taps + L - 1)//L          # Taps per polyphase sub-filter.
        self.sub    = sub
        self.architecture = architecture
        self.prune_zeros = prune_zeros
        phase_taps = []
        for p in range(L):
            taps = []
            for k in range(sub):
                idx = p + k*L
                c = coefficients[idx] if idx < n_taps else 0
                if not prune_zeros or c != 0:
                    taps.append((k, c))
            phase_taps.append(taps)
        check(all(phase_taps), "zero pruning requires at least one active tap per phase")
        phase_counts = [len(taps) for taps in phase_taps]
        max_mac_taps = max(phase_counts)
        self.phase_mac_taps = tuple(phase_counts)
        pipeline = int(architecture == "pipelined")
        self.cycles_per_output = max_mac_taps + 1 + pipeline
        self.cycles_per_input = sum(phase_counts) + L*(1 + pipeline)
        self.latency = n_taps + pipeline
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))

        # # #

        # Memories.
        # ---------
        depth = _pow2_ceil(sub + 1)                                     # Sample buffer depth (pow2 wrap).
        acc_w = 2*data_width + (max_mac_taps if max_mac_taps > 1 else 1).bit_length() + 1

        # Coefficients and history offsets are laid out as the active schedule for each phase.
        # With pruning disabled this is the original rectangular p*sub+k layout.
        phase_bases, coeff_init, history_offsets = [], [], []
        for taps in phase_taps:
            phase_bases.append(len(coeff_init))
            coeff_init += [c & ((1 << data_width) - 1) for _, c in taps]
            history_offsets += [k for k, _ in taps]
        # As above, preserve the valid n_taps=interpolation=1 boundary by padding the ROM.
        # One extra slot also defines the address observed during the pipelined drain state.
        crom_depth = max(2, len(coeff_init) + 1)
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
        k     = Signal(max=max_mac_taps + 1)          # MAC slot within the active phase schedule.
        coeff_adr = Signal(max=crom_depth)
        newest = Signal(max=depth)
        phase_base = Array([Constant(v, bits_for(crom_depth - 1)) for v in phase_bases])
        phase_count = Array([Constant(v, bits_for(max_mac_taps)) for v in phase_counts])
        tap_offset = Array([Constant(v, bits_for(depth - 1)) for v in history_offsets] +
            [Constant(0, bits_for(depth - 1))])
        acc_i, acc_q = Signal((acc_w, True)), Signal((acc_w, True))
        ci = Signal((data_width, True))               # Signed views of the I/Q/coeff read data.
        cq = Signal((data_width, True))
        cc = Signal((data_width, True))
        self.comb += [
            wip.adr.eq(wptr), wqp.adr.eq(wptr),
            wip.dat_w.eq(self.sink.i), wqp.dat_w.eq(self.sink.q),
            coeff_adr.eq(phase_base[phase] + k),
            rip.adr.eq(newest - tap_offset[coeff_adr]),
            rqp.adr.eq(newest - tap_offset[coeff_adr]),
            crp.adr.eq(coeff_adr),
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
                NextValue(newest, wptr),   # Newest sample (just written at wptr).
                NextState("MAC"),
            )
        )
        # MAC: one sub-filter tap per cycle (sub taps per output sample). The explicit
        # pipelined option separates the memory/multiplier path from the accumulator recurrence;
        # its final registered product is consumed in one drain cycle.
        if architecture == "classic":
            fsm.act("MAC",
                NextValue(acc_i, acc_i + ci*cc),
                NextValue(acc_q, acc_q + cq*cc),
                NextValue(k, k + 1),
                If(k == (phase_count[phase] - 1), NextState("EMIT")),
            )
        else:
            prod_i = Signal((2*data_width, True))
            prod_q = Signal((2*data_width, True))
            prod_valid = Signal()
            fsm.act("MAC",
                NextValue(prod_i, ci*cc),
                NextValue(prod_q, cq*cc),
                If(prod_valid,
                    NextValue(acc_i, acc_i + prod_i),
                    NextValue(acc_q, acc_q + prod_q),
                ),
                NextValue(prod_valid, 1),
                NextValue(k, k + 1),
                If(k == (phase_count[phase] - 1), NextState("MAC_DRAIN")),
            )
            fsm.act("MAC_DRAIN",
                NextValue(acc_i, acc_i + prod_i),
                NextValue(acc_q, acc_q + prod_q),
                NextValue(prod_valid, 0),
                NextState("EMIT"),
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
