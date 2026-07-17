#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr              import *
from litex.soc.interconnect.csr_eventmanager import EventManager, EventSourceProcess
from litex.soc.interconnect                  import stream

from litedsp.common     import check, iq_layout, saturated
from litedsp.filter.fir import LiteDSPFIRFilterComplex

# Helpers ------------------------------------------------------------------------------------------

def frame_sync_taps(sequence, data_width=16):
    """Matched-filter taps for ``sequence``: conjugate, time-reversed, full-scale Q1.(N-1).

    ``sequence`` entries may be complex numbers, ``(i, q)`` tuples/lists or plain reals (e.g.
    a +/-1 Barker/PN code), components in [-1.0, +1.0]. Returns ``(real, imag)`` integer
    coefficient lists (``imag`` is all-zero for a real sequence). Shared by the gateware and
    the golden model (test/models.py) so both quantize identically.
    """
    values = []
    for v in sequence:
        if isinstance(v, (tuple, list)):
            check(len(v) == 2, "expected (i, q) pairs in sequence")
            c = complex(v[0], v[1])
        else:
            c = complex(v)
        check(abs(c.real) <= 1.0 and abs(c.imag) <= 1.0, "expected sequence components in [-1.0, +1.0]")
        values.append(c)
    scale = (1 << (data_width - 1)) - 1  # Full-scale Q1.(N-1).
    taps  = [v.conjugate() for v in reversed(values)]
    return ([int(round(t.real*scale)) for t in taps],
            [int(round(t.imag*scale)) for t in taps])

# Frame Sync / Preamble Detector -------------------------------------------------------------------

@ResetInserter()
class LiteDSPFrameSync(LiteXModule):
    """Preamble detector + stream aligner: the gateway block for burst receivers.

    Correlates the I/Q stream against a known ``sequence`` (complex matched filter, i.e.
    :class:`litedsp.comm.correlator.LiteDSPCorrelator` conventions: taps are the conjugated
    time-reversed reference at full-scale Q1.(N-1)) and applies a CFAR-style *normalized*
    threshold so detection is invariant to input gain::

        detect when |corr|**2 * 2**threshold_frac >= threshold * (N * window_energy)

    where ``window_energy`` is the exact moving sum of ``I**2 + Q**2`` over the ``N``
    sequence samples ending at the correlated sample, and ``threshold`` is a runtime
    unsigned Q2.(threshold_frac) control. By Cauchy-Schwarz ``|corr|**2 <= N*window_energy``,
    so ``threshold`` reads as the normalized correlation power: 1.0 is a perfect match,
    noise averages ``1/N``; the reset value is 0.5. A zero-energy window (dead line) never
    detects. Both compare sides stay in wide exact
    fixed-point (no rounding on the detection path): ``|corr|**2`` and ``|x|**2`` grow to
    ``2*data_width + 1`` bits, the energy window adds ``ceil(log2(N))`` bits, the left side
    adds ``threshold_frac`` shift bits and the right side the ``2 + threshold_frac``
    threshold plus ``ceil(log2(N))`` scale bits. The only quantization on the path is the
    correlator's own round+saturate to ``data_width`` (keep preamble amplitude below
    full-scale/N to stay out of correlator saturation).

    On a threshold crossing, the local ``|corr|**2`` maximum within the next ``peak_window``
    samples is selected as the peak, ``detected`` pulses (counted in a CSR, optional IRQ via
    ``with_irq=True``), and the output stream — the input delayed by ``self.latency``
    samples, payload untouched — is tagged: ``source.first`` on the first sample after the
    preamble (peak + 1 + ``offset``), and, when ``frame_len`` is given, ``source.last``
    ``frame_len`` samples later. New crossings are ignored while an alignment/frame is in
    progress (so a preamble-like pattern inside the payload cannot re-trigger mid-frame).

    The whole detection pipeline advances only when a sample is consumed (never on input
    bubbles), so sample positions and pipeline slots coincide: peak-picking look-ahead and
    the ``first``/``last`` alignment are exact under any valid/ready pattern.

    ``architecture="classic"`` computes input power and ``threshold * (N * window_energy)``
    directly at their consumer registers and uses the matched filter's combinational reduction.
    ``architecture="pipelined"`` registers every matched-filter reduction level, then registers
    input power/correlation and splits normalized threshold formation across two stages. It adds
    ``ceil(log2(N)) + 2`` samples of latency without changing initiation rate, arithmetic, peak
    selection, or tags.

    Parameters
    ----------
    sequence : list
        Reference preamble: complex values, ``(i, q)`` tuples or +/-1 reals (Barker/PN code),
        components in [-1.0, +1.0]. Length ``N`` sets the correlator tap count (one complex
        FIR for a real sequence, two for a complex one) and the energy-window length.
    threshold_frac : int
        Fractional bits of the unsigned Q2.(threshold_frac) detection threshold
        (1.0 = ``2**threshold_frac`` = perfect correlation power; reset 0.5).
    frame_len : int or None
        Frame length in samples; when given, ``source.last`` is asserted ``frame_len``
        samples after (and including) the ``first`` sample. ``None`` tags ``first`` only.
    peak_window : int
        Local-maximum search window after a threshold crossing, in samples. Also sets the
        output look-ahead delay (classic ``latency = correlator latency + peak_window + 2``).
    """
    def __init__(self, sequence, data_width=16, threshold_frac=14, frame_len=None,
        peak_window=4, with_csr=True, with_irq=False, architecture="classic"):
        check(len(sequence) >= 2,                   "expected len(sequence) >= 2")
        check(threshold_frac >= 1,                  "expected threshold_frac >= 1")
        check(frame_len is None or frame_len >= 1,  "expected frame_len >= 1 (or None)")
        check(peak_window >= 1,                     "expected peak_window >= 1")
        check(architecture in ("classic", "pipelined"),
            "architecture must be 'classic' or 'pipelined'.")
        coeffs_r, coeffs_i = frame_sync_taps(sequence, data_width)
        n_seq       = len(sequence)
        complex_seq = any(coeffs_i)
        W           = peak_window
        self.sequence       = sequence
        self.data_width     = data_width
        self.threshold_frac = threshold_frac
        self.frame_len      = frame_len
        self.peak_window    = peak_window
        self.architecture   = architecture
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.threshold   = Signal(2 + threshold_frac, reset=1 << (threshold_frac - 1))  # Q2.f, 0.5.
        self.offset      = Signal(8)   # Extra samples between peak+1 and the `first` tag.
        self.detected    = Signal()    # 1-cycle pulse per accepted detection.
        self.count       = Signal(32)  # Detections since reset/clear.
        self.clear_count = Signal()    # Clear the detection counter.

        # # #

        def _and(sigs):
            expr = sigs[0]
            for s in sigs[1:]:
                expr = expr & s
            return expr

        # Correlator (matched filter).
        # ----------------------------
        # Complex FIR(s) with the conjugated time-reversed sequence as taps (LiteDSPCorrelator
        # conventions): fir_r applies Re(taps) to I/Q; for a complex sequence fir_i applies
        # Im(taps) and the two recombine at the join below (corr = x (*) conj(reversed(seq))).
        fir_architecture = "pipelined" if architecture == "pipelined" else "classic"
        self.fir_r = LiteDSPFIRFilterComplex(n_taps=n_seq, data_width=data_width,
            coefficients=coeffs_r, with_csr=False, architecture=fir_architecture)
        firs = [self.fir_r]
        if complex_seq:
            self.fir_i = LiteDSPFIRFilterComplex(n_taps=n_seq, data_width=data_width,
                coefficients=coeffs_i, with_csr=False, architecture=fir_architecture)
            firs.append(self.fir_i)
        pipeline = 2*int(architecture == "pipelined")
        self.latency = self.fir_r.latency + peak_window + 2 + pipeline

        # Raw-Sample Delay FIFO.
        # ----------------------
        # Carries the raw input past the correlator so the join below re-pairs corr[k] with
        # x[k] (the FIR holds at most latency+1 samples in flight; depth has margin).
        self.fifo = fifo = stream.SyncFIFO(iq_layout(data_width), self.fir_r.latency + 5)

        # Input Fork (correlator(s) + raw FIFO, joint ready).
        # ---------------------------------------------------
        sinks = [f.sink for f in firs] + [fifo.sink]
        for s in sinks:
            self.comb += [
                s.valid.eq(self.sink.valid & _and([o.ready for o in sinks if o is not s])),
                s.i.eq(self.sink.i),
                s.q.eq(self.sink.q),
            ]
        self.comb += self.sink.ready.eq(_and([s.ready for s in sinks]))

        # Output Handshake (no-bubble join).
        # ----------------------------------
        # The peak-picker looks ahead of the emitted stream, so the detection pipeline only
        # advances when a correlated sample AND its matching raw sample are both available:
        # bubbles never enter, slot position == sample position, and the first/last
        # alignment below stays exact under any valid/ready pattern.
        srcs = [f.source for f in firs] + [fifo.source]
        adv  = Signal()  # Output register can accept a sample.
        step = Signal()  # Detection pipeline advances (consumes one corr/raw pair).
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            step.eq(adv & _and([s.valid for s in srcs])),
        ]
        self.comb += [s.ready.eq(step) for s in srcs]

        # Correlation Combine.
        # --------------------
        corr_i = Signal((data_width, True))
        corr_q = Signal((data_width, True))
        if complex_seq:
            # Saturating recombine (each term is already rounded to data_width by its FIR).
            self.comb += [
                corr_i.eq(saturated(self.fir_r.source.i - self.fir_i.source.q, data_width)),
                corr_q.eq(saturated(self.fir_r.source.q + self.fir_i.source.i, data_width)),
            ]
        else:
            self.comb += [
                corr_i.eq(self.fir_r.source.i),
                corr_q.eq(self.fir_r.source.q),
            ]

        # Window Energy (wide moving sum of |x|**2 over the sequence length).
        # -------------------------------------------------------------------
        # acc += |x[k]|**2 - |x[k-N]|**2, kept exact (no rounding: the CFAR compare needs
        # both sides bit-true for gain invariance). All shift registers reset to zero, so
        # pre-stream samples count as zero energy (matching the model's zero padding).
        pw_width = 2*data_width + 1            # |x|**2, |corr|**2.
        nb       = n_seq.bit_length()
        en_width = pw_width + nb               # Sum of N squared samples.
        p        = Signal(pw_width)
        p_hist   = [Signal(pw_width) for _ in range(n_seq)]
        acc      = Signal(en_width)
        acc_next = Signal(en_width)
        self.comb += p.eq(fifo.source.i*fifo.source.i + fifo.source.q*fifo.source.q)

        # Stage 1: |corr|**2 + aligned window energy. The pipelined architecture first
        # registers input power and correlation, splitting the FIFO-read/square/sum path from
        # the moving-energy recurrence. Its valid/raw alignment advances by the same stage.
        # -------------------------------------------------------------------------------
        mag2_1 = Signal(pw_width)  # |corr[k]|**2.
        en_1   = Signal(en_width)  # Energy of x[k-N+1..k].
        if architecture == "classic":
            self.comb += acc_next.eq(acc + p - p_hist[-1])
            self.sync += If(step,
                acc.eq(acc_next),
                p_hist[0].eq(p),
                [p_hist[t].eq(p_hist[t-1]) for t in range(1, n_seq)],
                mag2_1.eq(corr_i*corr_i + corr_q*corr_q),
                en_1.eq(acc_next),
            )
        else:
            power_0 = Signal(pw_width)
            corr_i_0 = Signal((data_width, True))
            corr_q_0 = Signal((data_width, True))
            self.comb += acc_next.eq(acc + power_0 - p_hist[-1])
            self.sync += If(step,
                power_0.eq(p),
                corr_i_0.eq(corr_i),
                corr_q_0.eq(corr_q),
                acc.eq(acc_next),
                p_hist[0].eq(power_0),
                [p_hist[t].eq(p_hist[t-1]) for t in range(1, n_seq)],
                mag2_1.eq(corr_i_0*corr_i_0 + corr_q_0*corr_q_0),
                en_1.eq(acc_next),
            )

        # Normalized threshold pipeline + compare.
        # ----------------------------------------
        # detect when |corr|**2 * 2**threshold_frac >= threshold * (N * window_energy).
        # Left side: pw_width + threshold_frac bits; right side: (2 + threshold_frac) +
        # en_width + ceil(log2(N)) bits. Exact unsigned compare, no rounding. A zero-energy
        # window (dead line) never detects: 0 >= 0 must not count as a crossing.
        rhs_width = 2 + threshold_frac + en_width + nb
        mag2_2 = Signal(pw_width)
        nz_2   = Signal()
        exceed = Signal()
        if architecture == "classic":
            rhs_2 = Signal(rhs_width)
            self.sync += If(step,
                mag2_2.eq(mag2_1),
                rhs_2.eq(self.threshold * (en_1 * n_seq)),
                nz_2.eq(en_1 != 0),
            )
            metric = mag2_2
            rhs    = rhs_2
            nz     = nz_2
            fsm_plane = 1
        else:
            en_scaled_2 = Signal(en_width + nb)
            threshold_2 = Signal(2 + threshold_frac)
            mag2_3 = Signal(pw_width)
            rhs_3  = Signal(rhs_width)
            nz_3   = Signal()
            self.sync += If(step,
                mag2_2.eq(mag2_1),
                en_scaled_2.eq(en_1 * n_seq),
                threshold_2.eq(self.threshold),
                nz_2.eq(en_1 != 0),
                mag2_3.eq(mag2_2),
                rhs_3.eq(threshold_2 * en_scaled_2),
                nz_3.eq(nz_2),
            )
            metric = mag2_3
            rhs    = rhs_3
            nz     = nz_3
            fsm_plane = 3
        self.comb += exceed.eq(nz & ((metric << threshold_frac) >= rhs))

        # Delay-Matched Raw Stream + Valid Pipe.
        # --------------------------------------
        # Planes: [0] pairs with stage 1, [fsm_plane] with the compare/FSM, and the remainder the
        # peak-window look-ahead: the output register trails the FSM by W-1 samples so
        # `first` can land right after the peak even when the peak is the crossing sample.
        depth = W + 1 + pipeline
        raw_i = [Signal((data_width, True)) for _ in range(depth)]
        raw_q = [Signal((data_width, True)) for _ in range(depth)]
        vpipe = Signal(depth)
        self.sync += If(step,
            raw_i[0].eq(fifo.source.i),
            raw_q[0].eq(fifo.source.q),
            [raw_i[t].eq(raw_i[t-1]) for t in range(1, depth)],
            [raw_q[t].eq(raw_q[t-1]) for t in range(1, depth)],
            vpipe.eq(Cat(C(1, 1), vpipe[:-1])),
        )

        # Peak Search / Alignment FSM (sample domain: advances only on valid steps).
        # ---------------------------------------------------------------------------
        S_IDLE, S_SEARCH, S_ALIGN, S_FRAME = range(4)
        state = Signal(2)
        best  = Signal(pw_width)         # Best |corr|**2 in the search window.
        b_off = Signal(max=max(W, 2))    # Sample offset of the best so far (0 = crossing).
        s_cnt = Signal(max=max(W, 2))    # Samples examined in the search window.
        a_cnt = Signal(max=W + 257)      # Steps until the `first` tag (peak+1+offset).
        f_cnt = Signal(max=frame_len + 1) if (frame_len is not None and frame_len > 1) else None

        step_fsm  = Signal()             # Compare/FSM plane holds a real sample and advances.
        first_now = Signal()             # Tag `first` on the sample entering the output register.
        last_now  = Signal()             # Tag `last` on the sample entering the output register.
        self.comb += step_fsm.eq(step & vpipe[fsm_plane])

        # Crossing decision: at the end of the search window the peak position is known.
        if W == 1:
            self.comb += self.detected.eq(step_fsm & (state == S_IDLE) & exceed)
            trigger = [a_cnt.eq(1 + self.offset), state.eq(S_ALIGN)]
        else:
            self.comb += self.detected.eq(step_fsm & (state == S_SEARCH) & (s_cnt == W - 1))
            trigger = [best.eq(metric), b_off.eq(0), s_cnt.eq(1), state.eq(S_SEARCH)]
        self.comb += first_now.eq(step_fsm & (state == S_ALIGN) & (a_cnt == 1))
        if frame_len is None:
            align_end = [state.eq(S_IDLE)]
        elif frame_len == 1:
            align_end = [state.eq(S_IDLE)]
            self.comb += last_now.eq(first_now)
        else:
            align_end = [f_cnt.eq(frame_len - 1), state.eq(S_FRAME)]
            self.comb += last_now.eq(step_fsm & (state == S_FRAME) & (f_cnt == 1))

        fsm = If(state == S_IDLE,
            If(exceed, *trigger),
        )
        if W > 1:
            fsm = fsm.Elif(state == S_SEARCH,
                If(metric > best,
                    best.eq(metric),
                    b_off.eq(s_cnt),
                ),
                s_cnt.eq(s_cnt + 1),
                If(s_cnt == W - 1,  # Window complete: peak+1+offset is b_off+1+offset ahead.
                    a_cnt.eq(Mux(metric > best, s_cnt, b_off) + 1 + self.offset),
                    state.eq(S_ALIGN),
                ),
            )
        fsm = fsm.Elif(state == S_ALIGN,
            If(a_cnt == 1, *align_end).Else(a_cnt.eq(a_cnt - 1)),
        )
        if f_cnt is not None:
            fsm = fsm.Elif(state == S_FRAME,
                If(f_cnt == 1, state.eq(S_IDLE)).Else(f_cnt.eq(f_cnt - 1)),
            )
        self.sync += If(step_fsm, fsm)
        self.sync += [
            If(self.clear_count,
                self.count.eq(0),
            ).Elif(self.detected,
                self.count.eq(self.count + 1),
            ),
        ]

        # Output (aligned stream + first/last tagging).
        # ---------------------------------------------
        self.sync += If(adv,
            If(step,
                self.source.i.eq(raw_i[-1]),
                self.source.q.eq(raw_q[-1]),
                self.source.first.eq(first_now),
                self.source.last.eq(last_now),
                self.source.valid.eq(vpipe[-1]),
            ).Else(
                self.source.valid.eq(0),
            ),
        )

        # CSR / IRQ.
        # ----------
        if with_csr:
            self.add_csr()
        if with_irq:
            self.add_irq()

    def add_irq(self):
        self.ev          = EventManager()
        self.ev.detected = EventSourceProcess(edge="rising", description="Preamble detected (correlation peak accepted).")
        self.ev.finalize()
        self.comb += self.ev.detected.trigger.eq(self.detected)

    def add_csr(self):
        f = self.threshold_frac
        self._threshold = CSRStorage(2 + f, reset=1 << (f - 1), name="threshold",
            description=f"Detection threshold (unsigned Q2.{f}): detect when |corr|^2 >= "
                        f"threshold * N * window_energy; 1.0 (= 2**{f}) is a perfect match.")
        self._offset = CSRStorage(8, name="offset",
            description="Extra samples between peak+1 and the `first` tag.")
        self._control = CSRStorage(fields=[
            CSRField("clear", size=1, offset=0, pulse=True, description="Clear the detection counter."),
        ])
        self._count = CSRStatus(32, name="count", description="Detections since reset/clear.")
        self.comb += [
            self.threshold.eq(self._threshold.storage),
            self.offset.eq(self._offset.storage),
            self.clear_count.eq(self._control.fields.clear),
            self._count.status.eq(self.count),
        ]
