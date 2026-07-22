#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Polyphase filter-bank (PFB) channelizer: critical or 2x-oversampled DFT filter bank.

Splits a wide band into ``M`` uniformly-spaced channels through one shared prototype filter
(polyphase-decomposed) followed by an M-point DFT — the resource-optimal alternative to the
per-channel DDC bank (:mod:`litedsp.mixing.channelizer`): a single time-shared MAC computes
all M branch FIRs and a single serial DFT replaces M mixers + M decimating filters. Model
first: all products/accumulations are kept full width and a single round + saturate happens
at the output, so the block is bit-exact against ``test/models.py:pfb_channelizer_model``.
"""

import math

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common        import check, iq_layout, rounded, scaled
from litedsp.filter.design import firwin_lowpass

# Helpers ------------------------------------------------------------------------------------------

# Next power of two >= n (memory depths, so address pointers wrap for free).
def _pow2_ceil(n):
    return 1 << (max(1, n - 1)).bit_length()

# PFB Channelizer (polyphase FIR + DFT) -------------------------------------------------------------

@ResetInserter()
class LiteDSPPFBChannelizer(LiteXModule):
    """Uniform filter bank (polyphase FIR + scalable direct/FFT transform).

    A commutator distributes consecutive input samples over ``M = n_channels`` polyphase
    branches; every ``M/oversampling`` input samples, each branch computes a
    ``taps_per_channel``-tap dot-
    product over its sample history (prototype phase ``p``: taps ``coefficients[p::M]``,
    newest frame sample on branch 0) and the M branch results feed an M-point DFT with
    kernel ``exp(+2j*pi*k*p/M)``. ``oversampling=1`` preserves the aggregate rate: M channel
    samples out per M inputs. ``oversampling=2`` uses overlapping histories and emits M
    samples per M/2 new inputs; odd channels receive the alternating half-frame phase
    correction required to keep a channel-center tone at DC. Each output set is a framed
    burst (``first`` on channel 0, ``last`` on channel M-1).

    Channel convention: channel ``k`` is the band centered at ``+k/M`` of the input sample
    rate (``k > M/2`` wraps to the negative frequencies, center ``(k - M)/M``), brought to
    baseband and decimated by M — an input tone at exactly ``k/M`` lands as DC in channel
    ``k``; a tone at ``k/M + d`` (``|d|`` inside the prototype passband) lands in channel
    ``k`` as a tone at ``d*M`` of the channel output rate. Adjacent-channel isolation is
    the prototype's stopband attenuation at the neighboring channel offsets ``l/M``.

    Fixed-point: coefficients and DFT twiddles are signed Q1.(W-1). Bit growth is carried
    in full: branch accumulators are ``2*W + clog2(T) + 1`` bits (product + accumulation),
    DFT accumulators add ``W + clog2(M) + 1`` bits (twiddle product + M-term sum); a single
    :func:`litedsp.common.scaled` (round half-up + saturate) by ``2*(W - 1)`` bits (the
    coefficient + twiddle fractional bits) produces the output — no intermediate rounding.

    Throughput: one shared MAC, ``H + M*(T + 1) + M*(M + 1)`` cycles per frame, where
    ``H = M/oversampling``
    (load + branch FIRs + DFT/emit), so ``fs_in <= f_clk * M / cycles_per_frame`` (roughly
    ``f_clk / (T + M + 3)``); the input is stalled (backpressured) while a frame computes.
    ``architecture="folded"`` separates every multiply from its recursive accumulation,
    increasing this to ``M + M*(2*T + 1) + M*(2*M + 1)`` cycles while preserving the exact
    full-precision sums. ``"classic"`` remains the default.

    ``architecture="auto"`` is the unified scalable option: it selects the direct transform
    for ``M <= 8`` and the time-multiplexed radix-2 DIF transform for ``M >= 16``.
    ``architecture="fft"`` selects that FFT transform explicitly.
    It uses the timing-oriented two-cycle polyphase MAC and computes one butterfly in four
    clocks (registered read/difference, registered multiply, then two single-port
    feedback-memory writes), reducing the DFT work from O(M^2) to O(M log2(M)) while retaining
    full branch precision and natural channel order. Twiddle products round back to the branch
    accumulator's fractional scale after each FFT rank; this arithmetic has its own bit-exact
    golden model.

    Parameters
    ----------
    n_channels : int
        Number of uniformly-spaced channels M (power of two; 2..8 for direct/folded DFT,
        M >= 16 for the FFT stage). Channel k is centered at ``k/M`` of the input rate.
    taps_per_channel : int
        Prototype taps per polyphase branch T (prototype length = ``n_channels *
        taps_per_channel``). Sets the channel shape/stopband and the MAC length.
    coefficients : list
        Prototype low-pass taps, signed Q1.(W-1) integers, length ``n_channels *
        taps_per_channel`` (default: ``firwin_lowpass(M*T, 0.4/M)``, unity DC gain, so a
        full-scale tone at a channel center emerges at full scale in that channel).
    architecture : str
        ``"auto"`` to select classic for M <= 8 and FFT for M >= 16, ``"classic"`` for one
        MAC term per clock, ``"folded"`` for separate multiply and accumulate clocks in both
        direct sections, or ``"fft"`` for the scalable DFT stage.
    oversampling : int
        Aggregate output/input rate: 1 for critically sampled (M outputs per M inputs), or
        2 for overlapping frames (M outputs per M/2 inputs) with odd-bin phase correction.
    """
    def __init__(self, n_channels=4, taps_per_channel=8, data_width=16, coefficients=None,
        architecture="auto", oversampling=1, with_csr=True):
        M, T = n_channels, taps_per_channel  # Literature names.
        check(M >= 2 and (M & (M - 1)) == 0, "expected n_channels power of two and >= 2")
        check(T >= 1, "expected taps_per_channel >= 1")
        check(oversampling in (1, 2), "oversampling must be 1 or 2")
        check(architecture in ("auto", "classic", "folded", "fft"),
            "architecture must be 'auto', 'classic', 'folded', or 'fft'.")
        requested_architecture = architecture
        if architecture == "auto":
            architecture = "classic" if M <= 8 else "fft"
        if architecture == "fft":
            check(M >= 16, "fft architecture requires n_channels >= 16")
        else:
            check(M <= 8, "direct/folded architecture requires n_channels <= 8")
        if coefficients is None:
            coefficients = firwin_lowpass(M*T, 0.4/M, data_width=data_width)
        check(len(coefficients) == M*T, "expected len(coefficients) == n_channels*taps_per_channel")
        self.n_channels       = M
        self.taps_per_channel = T
        self.data_width       = data_width
        self.coefficients     = coefficients
        self.architecture     = architecture
        self.requested_architecture = requested_architecture
        self.oversampling      = oversampling
        self.frame_stride      = M//oversampling
        H = self.frame_stride
        if architecture == "classic":
            self.cycles_per_frame = H + M*(T + 1) + M*(M + 1)
        elif architecture == "folded":
            self.cycles_per_frame = H + M*(2*T + 1) + M*(2*M + 1)
        else:
            self.cycles_per_frame = H + M*(2*T + 1) + 2*M*int(math.log2(M)) + M
        self.latency = self.cycles_per_frame               # Burst latency (cycles per frame).
        self.sink   = stream.Endpoint(iq_layout(data_width))  # Wide-band I/Q input.
        self.source = stream.Endpoint(iq_layout(data_width))  # Framed channel samples (M per frame).

        # # #

        # Memories.
        # ---------
        depth  = _pow2_ceil(M*T)                             # Sample history (pow2: free pointer wrap).
        acc_w  = 2*data_width + (T - 1).bit_length() + 1     # Branch: product + log2(T) accumulation.
        dacc_w = acc_w + data_width + (M - 1).bit_length() + 1  # DFT: + twiddle product + log2(M) sum.
        shift  = 2*(data_width - 1)                          # Coefficient + twiddle fractional bits.
        mask   = (1 << data_width) - 1
        tw     = (1 << (data_width - 1)) - 1                 # Twiddle scale (Q1.(W-1)).

        # Coefficients laid out by phase: crom[p*T + t] = c[p + t*M] (branch-major, MAC order).
        crom = Memory(data_width, M*T, init=[coefficients[p + t*M] & mask for p in range(M) for t in range(T)])
        # Sample history (I and Q), written by the commutator, read back with stride M.
        mi = Memory(data_width, depth)
        mq = Memory(data_width, depth)
        # Branch dot-products (full accumulator width), M entries, rewritten every frame.
        ui = Memory(acc_w, M)
        uq = Memory(acc_w, M)
        # M-entry DFT twiddle ROMs: exp(+2j*pi*j/M) (kernel index j = k*p mod M).
        cos_rom = Memory(data_width, M, init=[int(round(math.cos(2*math.pi*j/M)*tw)) & mask for j in range(M)])
        sin_rom = Memory(data_width, M, init=[int(round(math.sin(2*math.pi*j/M)*tw)) & mask for j in range(M)])
        crp      = crom.get_port(async_read=True)
        wip, wqp = mi.get_port(write_capable=True), mq.get_port(write_capable=True)
        rip, rqp = mi.get_port(async_read=True),    mq.get_port(async_read=True)
        uiw, uqw = ui.get_port(write_capable=True), uq.get_port(write_capable=True)
        uir, uqr = ui.get_port(async_read=True),    uq.get_port(async_read=True)
        cos_rp   = cos_rom.get_port(async_read=True)
        sin_rp   = sin_rom.get_port(async_read=True)
        self.specials += crom, mi, mq, ui, uq, cos_rom, sin_rom
        self.specials += crp, wip, wqp, rip, rqp, uiw, uqw, uir, uqr, cos_rp, sin_rp

        # Signals.
        # --------
        wptr = Signal(max=depth)   # Sample write pointer (commutator).
        base = Signal(max=depth)   # Newest sample of the current frame.
        pos  = Signal(max=M)       # Position within the M-sample input frame.
        p    = Signal(max=M)       # Branch (polyphase phase) index.
        t    = Signal(max=T + 1)   # Tap index within the branch.
        k    = Signal(max=M)       # Output channel (DFT bin) index.
        pd   = Signal(max=M)       # DFT input (branch) index.
        tw_addr = Signal(max=M)    # Folded DFT twiddle index (recurrent k*p mod M).
        phase_flip = Signal()      # 2x mode: negate odd bins on alternating half-frames.
        radr = Signal(max=depth)   # History read pointer (walks back from newest, stride M).
        acc_i,  acc_q  = Signal((acc_w, True)),  Signal((acc_w, True))    # Branch accumulators.
        dacc_i, dacc_q = Signal((dacc_w, True)), Signal((dacc_w, True))   # DFT accumulators.
        ci = Signal((data_width, True))  # Signed views of the I/Q/coeff/twiddle/branch reads.
        cq = Signal((data_width, True))
        cc = Signal((data_width, True))
        tc = Signal((data_width, True))
        ts = Signal((data_width, True))
        ur = Signal((acc_w, True))
        uj = Signal((acc_w, True))
        mac_prod_i = Signal((2*data_width, True))
        mac_prod_q = Signal((2*data_width, True))
        dft_prod_rr = Signal((acc_w + data_width, True))
        dft_prod_ii = Signal((acc_w + data_width, True))
        dft_prod_ri = Signal((acc_w + data_width, True))
        dft_prod_ir = Signal((acc_w + data_width, True))
        self.comb += [
            wip.adr.eq(wptr), wqp.adr.eq(wptr),
            wip.dat_w.eq(self.sink.i), wqp.dat_w.eq(self.sink.q),
            rip.adr.eq(radr), rqp.adr.eq(radr),
            crp.adr.eq(p*T + t),
            ci.eq(rip.dat_r), cq.eq(rqp.dat_r), cc.eq(crp.dat_r),
            uiw.adr.eq(p), uqw.adr.eq(p),
            uiw.dat_w.eq(acc_i), uqw.dat_w.eq(acc_q),
            uir.adr.eq(pd), uqr.adr.eq(pd),
            ur.eq(uir.dat_r), uj.eq(uqr.dat_r),
            cos_rp.adr.eq(((k*pd) & (M - 1)) if architecture == "classic" else tw_addr),
            sin_rp.adr.eq(((k*pd) & (M - 1)) if architecture == "classic" else tw_addr),
            tc.eq(cos_rp.dat_r), ts.eq(sin_rp.dat_r),
        ]

        # Scalable DFT state. The polyphase branch sums already carry one Q1.(W-1)
        # coefficient factor. Each FFT twiddle multiplication rounds back by W-1 bits, so
        # the transform retains that scale and needs one final W-1 output shift.
        if architecture == "fft":
            fft_bits = int(math.log2(M))
            fft_w    = acc_w + fft_bits
            fft_mem_i = Memory(fft_w, M)
            fft_mem_q = Memory(fft_w, M)
            fft_wp_i  = fft_mem_i.get_port(write_capable=True)
            fft_wp_q  = fft_mem_q.get_port(write_capable=True)
            fft_ra_i  = fft_mem_i.get_port(async_read=True)
            fft_ra_q  = fft_mem_q.get_port(async_read=True)
            fft_rb_i  = fft_mem_i.get_port(async_read=True)
            fft_rb_q  = fft_mem_q.get_port(async_read=True)
            self.specials += fft_mem_i, fft_mem_q, fft_wp_i, fft_wp_q
            self.specials += fft_ra_i, fft_ra_q, fft_rb_i, fft_rb_q
            fft_stage = Signal(max=fft_bits)
            fft_bfly = Signal(max=M//2)
            fft_a    = Signal(max=M)
            fft_b    = Signal(max=M)
            fft_tw   = Signal(max=M)
            fft_raddr_a = Signal(max=M)
            fft_waddr = Signal(max=M)
            fft_wdata_i = Signal((fft_w, True))
            fft_wdata_q = Signal((fft_w, True))
            fft_we = Signal()
            fft_cases = {}
            for s in range(fft_bits):
                D      = M >> (s + 1)
                dbits  = int(math.log2(D)) if D > 1 else 0
                # Exact-width bit assembly avoids the implicit extensions produced by
                # mask/shift arithmetic in generated Verilog. DIF butterflies insert the
                # a/b-select bit between p and the group index; twiddle index is p << s.
                a_parts = []
                b_parts = []
                if dbits:
                    a_parts.append(fft_bfly[:dbits])
                    b_parts.append(fft_bfly[:dbits])
                a_parts.append(Constant(0, 1))
                b_parts.append(Constant(1, 1))
                if dbits < len(fft_bfly):
                    a_parts.append(fft_bfly[dbits:])
                    b_parts.append(fft_bfly[dbits:])
                tw_parts = []
                if s:
                    tw_parts.append(Constant(0, s))
                if dbits:
                    tw_parts.append(fft_bfly[:dbits])
                tw_parts.append(Constant(0, fft_bits - s - dbits))
                fft_cases[s] = [
                    fft_a.eq(Cat(*a_parts)),
                    fft_b.eq(Cat(*b_parts)),
                    fft_tw.eq(Cat(*tw_parts)),
                ]
            self.comb += Case(fft_stage, fft_cases)
            self.comb += [cos_rp.adr.eq(fft_tw), sin_rp.adr.eq(fft_tw)]

            far = Signal((fft_w, True))
            faq = Signal((fft_w, True))
            fbr = Signal((fft_w, True))
            fbq = Signal((fft_w, True))
            self.comb += [
                fft_raddr_a.eq(fft_a),
                fft_ra_i.adr.eq(fft_raddr_a), fft_ra_q.adr.eq(fft_raddr_a),
                fft_rb_i.adr.eq(fft_b),       fft_rb_q.adr.eq(fft_b),
                far.eq(fft_ra_i.dat_r), faq.eq(fft_ra_q.dat_r),
                fbr.eq(fft_rb_i.dat_r), fbq.eq(fft_rb_q.dat_r),
                fft_wp_i.adr.eq(fft_waddr), fft_wp_q.adr.eq(fft_waddr),
                fft_wp_i.dat_w.eq(fft_wdata_i), fft_wp_q.dat_w.eq(fft_wdata_q),
                fft_wp_i.we.eq(fft_we), fft_wp_q.we.eq(fft_we),
                fft_waddr.eq(0), fft_wdata_i.eq(0), fft_wdata_q.eq(0), fft_we.eq(0),
            ]
            fft_sum_i = Signal((fft_w + 1, True))
            fft_sum_q = Signal((fft_w + 1, True))
            fft_diff_i = Signal((fft_w + 1, True))
            fft_diff_q = Signal((fft_w + 1, True))
            fft_term_w = fft_w + data_width
            fft_rr = Signal((fft_term_w, True))
            fft_ii = Signal((fft_term_w, True))
            fft_ri = Signal((fft_term_w, True))
            fft_ir = Signal((fft_term_w, True))
            fft_tc = Signal((data_width, True))
            fft_ts = Signal((data_width, True))
            fft_prod_i = Signal((fft_term_w + 1, True))
            fft_prod_q = Signal((fft_term_w + 1, True))
            self.comb += [
                fft_prod_i.eq(fft_rr - fft_ii),
                fft_prod_q.eq(fft_ri + fft_ir),
            ]
            fft_diff_tw_i = Signal((fft_w, True))
            fft_diff_tw_q = Signal((fft_w, True))
            self.comb += [
                fft_diff_tw_i.eq(Mux(fft_tw == 0, fft_diff_i,
                    rounded(fft_prod_i, data_width - 1))),
                fft_diff_tw_q.eq(Mux(fft_tw == 0, fft_diff_q,
                    rounded(fft_prod_q, data_width - 1))),
            ]
            fft_emit_addr = Array([int(f"{j:0{fft_bits}b}"[::-1], 2) for j in range(M)])[k]
            fft_correct_i = Mux(phase_flip & k[0], -far, far) if oversampling == 2 else far
            fft_correct_q = Mux(phase_flip & k[0], -faq, faq) if oversampling == 2 else faq
            fft_out_i, _ = scaled(fft_correct_i, data_width - 1, data_width)
            fft_out_q, _ = scaled(fft_correct_q, data_width - 1, data_width)

        dft_correct_i = Mux(phase_flip & k[0], -dacc_i, dacc_i) if oversampling == 2 else dacc_i
        dft_correct_q = Mux(phase_flip & k[0], -dacc_q, dacc_q) if oversampling == 2 else dacc_q
        out_i, _ = scaled(dft_correct_i, shift, data_width)
        out_q, _ = scaled(dft_correct_q, shift, data_width)

        # FSM.
        # ----
        self.fsm = fsm = FSM(reset_state="LOAD")
        # LOAD: commutate H new input samples into history; the H-th starts a transform over
        # the latest M*T history. In 2x mode consecutive transforms overlap by M/2 samples.
        fsm.act("LOAD",
            self.sink.ready.eq(1),
            If(self.sink.valid,
                wip.we.eq(1), wqp.we.eq(1),
                NextValue(wptr, wptr + 1),
                If(pos == (H - 1),
                    NextValue(pos, 0),
                    NextValue(p, 0), NextValue(t, 0),
                    NextValue(acc_i, 0), NextValue(acc_q, 0),
                    NextValue(base, wptr),       # Newest sample (just written at wptr).
                    NextValue(radr, wptr),       # Branch 0, tap 0 = the newest sample.
                    NextState("MAC" if architecture == "classic" else "MAC_MUL"),
                ).Else(
                    NextValue(pos, pos + 1),
                )
            )
        )
        # MAC: one branch tap per cycle; radr walks the history back with stride M (branch p
        # reads samples base - p - t*M) while p*T + t addresses the phase-major coefficients.
        if architecture == "classic":
            fsm.act("MAC",
                NextValue(acc_i, acc_i + ci*cc),
                NextValue(acc_q, acc_q + cq*cc),
                NextValue(radr, radr - M),
                NextValue(t, t + 1),
                If(t == (T - 1), NextState("STORE")),
            )
        else:
            fsm.act("MAC_MUL",
                NextValue(mac_prod_i, ci*cc),
                NextValue(mac_prod_q, cq*cc),
                NextState("MAC_ACC"),
            )
            fsm.act("MAC_ACC",
                NextValue(acc_i, acc_i + mac_prod_i),
                NextValue(acc_q, acc_q + mac_prod_q),
                NextValue(radr, radr - M),
                NextValue(t, t + 1),
                If(t == (T - 1),
                    NextState("STORE"),
                ).Else(
                    NextState("MAC_MUL"),
                ),
            )
        # STORE: latch branch p's dot-product into u[p]; next branch, or the DFT after branch M-1.
        fsm.act("STORE",
            uiw.we.eq(1), uqw.we.eq(1),
            NextValue(acc_i, 0), NextValue(acc_q, 0),
            NextValue(t, 0),
            NextValue(radr, base - 1 - p),       # Branch p+1, tap 0 = base - (p + 1).
            *([fft_we.eq(1), fft_waddr.eq(p), fft_wdata_i.eq(acc_i), fft_wdata_q.eq(acc_q)]
              if architecture == "fft" else []),
            If(p == (M - 1),
                NextValue(k, 0), NextValue(pd, 0),
                NextValue(tw_addr, 0),
                NextValue(dacc_i, 0), NextValue(dacc_q, 0),
                *([NextValue(fft_stage, 0), NextValue(fft_bfly, 0)]
                  if architecture == "fft" else []),
                NextState("FFT_READ" if architecture == "fft" else
                          ("DFT" if architecture == "classic" else "DFT_MUL")),
            ).Else(
                NextValue(p, p + 1),
                NextState("MAC" if architecture == "classic" else "MAC_MUL"),
            )
        )
        # DFT: channel k = sum over branches of u[p] * exp(+2j*pi*k*p/M), one branch per cycle.
        if architecture == "classic":
            fsm.act("DFT",
                NextValue(dacc_i, dacc_i + ur*tc - uj*ts),
                NextValue(dacc_q, dacc_q + ur*ts + uj*tc),
                NextValue(pd, pd + 1),
                If(pd == (M - 1), NextState("EMIT")),
            )
        elif architecture == "folded":
            fsm.act("DFT_MUL",
                NextValue(dft_prod_rr, ur*tc), NextValue(dft_prod_ii, uj*ts),
                NextValue(dft_prod_ri, ur*ts), NextValue(dft_prod_ir, uj*tc),
                NextState("DFT_ACC"),
            )
            fsm.act("DFT_ACC",
                NextValue(dacc_i, dacc_i + dft_prod_rr - dft_prod_ii),
                NextValue(dacc_q, dacc_q + dft_prod_ri + dft_prod_ir),
                NextValue(pd, pd + 1),
                NextValue(tw_addr, (tw_addr + k) & (M - 1)),
                If(pd == (M - 1),
                    NextState("EMIT"),
                ).Else(
                    NextState("DFT_MUL"),
                ),
            )
        if architecture == "fft":
            fsm.act("FFT_READ",
                NextValue(fft_sum_i, far + fbr),
                NextValue(fft_sum_q, faq + fbq),
                NextValue(fft_diff_i, far - fbr),
                NextValue(fft_diff_q, faq - fbq),
                NextValue(fft_tc, tc), NextValue(fft_ts, ts),
                NextState("FFT_MUL"),
            )
            fsm.act("FFT_MUL",
                NextValue(fft_rr, fft_diff_i*fft_tc),
                NextValue(fft_ii, fft_diff_q*fft_ts),
                NextValue(fft_ri, fft_diff_i*fft_ts),
                NextValue(fft_ir, fft_diff_q*fft_tc),
                NextState("FFT_WRITE_SUM"),
            )
            fsm.act("FFT_WRITE_SUM",
                fft_we.eq(1), fft_waddr.eq(fft_a),
                fft_wdata_i.eq(fft_sum_i), fft_wdata_q.eq(fft_sum_q),
                NextState("FFT_WRITE_DIFF"),
            )
            fsm.act("FFT_WRITE_DIFF",
                fft_we.eq(1), fft_waddr.eq(fft_b),
                fft_wdata_i.eq(fft_diff_tw_i), fft_wdata_q.eq(fft_diff_tw_q),
                If(fft_bfly == (M//2 - 1),
                    NextValue(fft_bfly, 0),
                    If(fft_stage == (fft_bits - 1),
                        NextValue(k, 0),
                        NextState("EMIT"),
                    ).Else(
                        NextValue(fft_stage, fft_stage + 1),
                        NextState("FFT_READ"),
                    ),
                ).Else(
                    NextValue(fft_bfly, fft_bfly + 1),
                    NextState("FFT_READ"),
                ),
            )
        # EMIT: present channel k (frame position = channel index); loop back through DFT for
        # the next channel, then return to LOAD after channel M-1.
        fsm.act("EMIT",
            *([fft_raddr_a.eq(fft_emit_addr)] if architecture == "fft" else []),
            self.source.valid.eq(1),
            self.source.first.eq(k == 0),
            self.source.last.eq(k == (M - 1)),
            self.source.i.eq(fft_out_i if architecture == "fft" else out_i),
            self.source.q.eq(fft_out_q if architecture == "fft" else out_q),
            If(self.source.ready,
                If(k == (M - 1),
                    *([NextValue(phase_flip, ~phase_flip)] if oversampling == 2 else []),
                    NextState("LOAD"),
                ).Else(
                    NextValue(k, k + 1),
                    NextValue(pd, 0),
                    NextValue(tw_addr, 0),
                    NextValue(dacc_i, 0), NextValue(dacc_q, 0),
                    NextState("EMIT" if architecture == "fft" else
                              ("DFT" if architecture == "classic" else "DFT_MUL")),
                )
            )
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("channels", size=16, description="Number of channels M."),
            CSRField("taps",     size=16, description="Prototype taps per polyphase branch."),
        ])
        self.comb += [
            self._config.fields.channels.eq(self.n_channels),
            self._config.fields.taps.eq(self.taps_per_channel),
        ]
