#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""OFDM LS channel estimation + one-tap equalization (divider-free).

``LiteDSPOFDMEqualizer`` closes the OFDM receive chain (CP remove -> FFT -> equalizer): a
``train`` pulse consumes the next full frame as a known preamble and least-squares-estimates
the channel per bin (``H_k = Y_k * conj(X_ref_k)`` — the reference is restricted to QPSK
``+/-1 +/-1j``, so estimation is sign add/subtract only, no multiplier); every following
frame is equalized with the standard divider-free one-tap formulation
``S_k = Y_k * conj(H_k)`` and the per-bin CSI ``|H_k|**2`` is emitted alongside so a
downstream soft demapper can weight its LLRs (max-log LLRs of ``Y*conj(H)`` scale by
``|H|**2``, exactly the CSI weighting). Frames are position-indexed: estimation and
equalization address bins identically, so the block is bin-order-agnostic — it works
directly on the FFT's bit-reversed output (load the reference in the same order) or on
natural-order frames after a reorder.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, scaled

# OFDM Equalizer -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPOFDMEqualizer(LiteXModule):
    """LS channel estimation + divider-free one-tap OFDM equalizer with per-bin CSI.

    Pulse ``train`` (Signal, or the CSR ``control.train``): the **next full frame** is
    consumed as the preamble (no output) and ``H_k = scaled(Y_k * conj(X_ref_k), 1)`` is
    stored per bin; subsequent frames are equalized as ``S_k = scaled(Y_k * conj(H_k),
    coeff_frac)`` with ``|H_k|**2`` (same ``coeff_frac`` scaling) on the ``csi`` source
    param field. There is no divider: hard-decision users see a per-bin gain/phase-corrected
    constellation up to the (positive, real) ``|H_k|**2`` scaling — phase is exact, QPSK
    signs are unaffected, and amplitude-sensitive consumers normalize by ``csi`` (the
    standard CSI-weighted soft-demapping formulation).

    The 2-bit-per-bin reference RAM holds the preamble's QPSK signs (bit 0 = I, bit 1 = Q,
    ``1`` = positive: ``X_ref_k = (+/-1) + j*(+/-1)``), reset to ``1 + 1j`` on every bin and
    runtime-loadable through ``ref_data``/``ref_we``/``ref_rst`` (sequential write, like the
    FIR coefficient reload). ``H`` is signed Q(data_width-coeff_frac).``coeff_frac`` per
    component and resets to ``1.0 + 0j`` on every bin, so the untrained block is a unit-gain
    passthrough (``csi = 1.0``); with a preamble axis amplitude of ``2**coeff_frac`` LSBs and
    a flat channel it re-estimates to 1.0.

    Frames are ``fft_size`` beats, counted from the first sample after reset (align upstream
    — CP remove / FFT — before this block, as with the CP blocks); ``first``/``last`` are
    (re)generated from the position counter. Bins are addressed by frame position for both
    estimation and equalization, so bit-reversed FFT order needs no reorder — only the
    reference must be loaded in the same order. Downstream sinks without a ``csi`` field
    connect with ``connect(..., omit={"csi"})``.

    Parameters
    ----------
    fft_size : int
        OFDM symbol length N in bins per frame; sets the H/reference RAM depths.
    coeff_frac : int
        Fractional bits of the stored channel estimate H (signed
        Q(data_width-coeff_frac).coeff_frac, 1.0 = 2**coeff_frac); also the rescale shift of
        the equalized output and of the csi field (1 <= coeff_frac <= data_width - 1).
    """
    def __init__(self, fft_size=64, data_width=16, coeff_frac=14, with_csr=True):
        check(fft_size >= 2,                      "expected fft_size >= 2")
        check(1 <= coeff_frac <= data_width - 1,  "expected 1 <= coeff_frac <= data_width - 1")
        self.fft_size   = fft_size
        self.coeff_frac = coeff_frac
        self.latency    = 2
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(stream.EndpointDescription(iq_layout(data_width),
            [("csi", data_width)]))
        self.train    = Signal()            # Pulse: train H on the next full frame.
        self.ref_data = Signal(2)           # Reference reload: next bin's QPSK signs ({q, i}).
        self.ref_we   = Signal()
        self.ref_rst  = Signal()            # Reset the reference write pointer to bin 0.

        # # #

        # Memories.
        # ---------
        # H RAM: one channel estimate per bin ({q, i} packed), reset to 1.0 + 0j (unit-gain
        # passthrough until trained). Written during the training frame, read (async, same
        # beat) on the equalize path — training never reads, so no read/write hazard.
        one   = (1 << coeff_frac) & ((1 << data_width) - 1)
        h_mem = Memory(2*data_width, fft_size, init=[one]*fft_size)
        h_wp  = h_mem.get_port(write_capable=True)
        h_rp  = h_mem.get_port(async_read=True)
        # Reference RAM: 2 bits per bin (bit 0 = I sign, bit 1 = Q sign, 1 = positive),
        # reset to 0b11 = 1 + 1j on every bin.
        r_mem = Memory(2, fft_size, init=[0b11]*fft_size)
        r_wp  = r_mem.get_port(write_capable=True)
        r_rp  = r_mem.get_port(async_read=True)
        self.specials += h_mem, h_wp, h_rp, r_mem, r_wp, r_rp

        # Reference Reload.
        # -----------------
        # Sequential write interface (default = the all-(1 + 1j) preamble).
        rptr = Signal(max=fft_size)
        self.comb += [r_wp.adr.eq(rptr), r_wp.dat_w.eq(self.ref_data), r_wp.we.eq(self.ref_we)]
        self.sync += If(self.ref_rst, rptr.eq(0)).Elif(self.ref_we,
            If(rptr == (fft_size - 1), rptr.eq(0)).Else(rptr.eq(rptr + 1)))

        # Frame Position / Training Control.
        # ----------------------------------
        # cnt indexes the bin (frame position) of the sink beat; a train pulse arms
        # train_pend, sampled at the next frame start into training for that whole frame.
        cnt      = Signal(max=fft_size)
        start    = Signal()
        last     = Signal()
        pend     = Signal()   # A train request is armed (applies at the next frame start).
        training = Signal()   # Current frame is the preamble (consumed, H written).
        tr       = Signal()   # This beat belongs to a training frame.
        adv      = Signal()   # Equalize pipeline advances (output slot free or consumed).
        xfer     = Signal()   # Input beat accepted this cycle.
        self.comb += [
            start.eq(cnt == 0),
            last.eq(cnt == (fft_size - 1)),
            tr.eq(Mux(start, pend, training)),
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(Mux(tr, 1, adv)),   # Preamble beats are consumed freely.
            xfer.eq(self.sink.valid & self.sink.ready),
        ]
        self.sync += [
            If(xfer,
                If(last, cnt.eq(0)).Else(cnt.eq(cnt + 1)),
                If(start, training.eq(tr), pend.eq(0)),
                If(last, training.eq(0)),
            ),
            If(self.train, pend.eq(1)),   # Set wins: a pulse at a frame start trains the next frame.
        ]

        # LS Estimation (training frame): H = scaled(Y * conj(X_ref), 1).
        # ----------------------------------------------------------------
        # X_ref = si + j*sq with si/sq in {+1, -1}: the conjugate multiply is sign
        # add/subtract only — H = (Yi*si + Yq*sq) + j*(Yq*si - Yi*sq) — and |X_ref|**2 = 2
        # is folded by the 1-bit rescale, so H never saturates.
        yi_si  = Signal((data_width + 1, True))   # Yi * si.
        yq_si  = Signal((data_width + 1, True))   # Yq * si.
        yi_sq  = Signal((data_width + 1, True))   # Yi * sq.
        yq_sq  = Signal((data_width + 1, True))   # Yq * sq.
        h_wr_i = Signal((data_width, True))
        h_wr_q = Signal((data_width, True))
        self.comb += [
            r_rp.adr.eq(cnt),
            yi_si.eq(Mux(r_rp.dat_r[0], self.sink.i, -self.sink.i)),
            yq_si.eq(Mux(r_rp.dat_r[0], self.sink.q, -self.sink.q)),
            yi_sq.eq(Mux(r_rp.dat_r[1], self.sink.i, -self.sink.i)),
            yq_sq.eq(Mux(r_rp.dat_r[1], self.sink.q, -self.sink.q)),
            h_wr_i.eq(scaled(yi_si + yq_sq, 1, data_width)[0]),
            h_wr_q.eq(scaled(yq_si - yi_sq, 1, data_width)[0]),
            h_wp.adr.eq(cnt),
            h_wp.dat_w.eq(Cat(h_wr_i, h_wr_q)),
            h_wp.we.eq(xfer & tr),
        ]

        # One-Tap Equalization: S = scaled(Y * conj(H), coeff_frac), csi = scaled(|H|**2, coeff_frac).
        # ---------------------------------------------------------------------------------------------
        # 2-stage pipeline (advances on adv, like the soft demapper): stage 1 registers the
        # full-width products, stage 2 the rescaled outputs. Training beats never enter
        # (valid gated by ~tr), so the H write above cannot collide with a read in flight.
        hi = Signal((data_width, True))
        hq = Signal((data_width, True))
        self.comb += [h_rp.adr.eq(cnt), hi.eq(h_rp.dat_r[:data_width]), hq.eq(h_rp.dat_r[data_width:])]

        valid_sr = Signal(self.latency)
        self.sync += If(adv, valid_sr.eq(Cat(self.sink.valid & ~tr, valid_sr[:-1])))
        self.comb += self.source.valid.eq(valid_sr[-1])

        prod_i  = Signal((2*data_width + 1, True))   # Re{Y * conj(H)}.
        prod_q  = Signal((2*data_width + 1, True))   # Im{Y * conj(H)}.
        mag2    = Signal((2*data_width + 1, True))   # |H|**2 (non-negative).
        first_r = Signal()
        last_r  = Signal()
        self.sync += If(adv,
            prod_i.eq(self.sink.i*hi + self.sink.q*hq),
            prod_q.eq(self.sink.q*hi - self.sink.i*hq),
            mag2.eq(hi*hi + hq*hq),
            first_r.eq(start),
            last_r.eq(last),
        )
        self.sync += If(adv,
            self.source.i.eq(scaled(prod_i, coeff_frac, data_width)[0]),
            self.source.q.eq(scaled(prod_q, coeff_frac, data_width)[0]),
            self.source.csi.eq(scaled(mag2, coeff_frac, data_width)[0]),
            self.source.first.eq(first_r),
            self.source.last.eq(last_r),
        )

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("fft_size",   size=16, description="Bins per frame N."),
            CSRField("coeff_frac", size=8,  description="Fractional bits of H (1.0 = 2**coeff_frac)."),
        ])
        self._control = CSRStorage(fields=[
            CSRField("train", size=1, offset=0, pulse=True, description=
                "Train: consume the next full frame as the known preamble and store "
                "H_k = Y_k * conj(X_ref_k) per bin (no output for that frame)."),
        ])
        self._ref_rst = CSRStorage(1, name="ref_reset",
            description="Reset the reference write pointer to bin 0 (write to strobe).")
        self._ref = CSRStorage(2, name="ref",
            description="Write the next bin's 2-bit preamble reference (bit 0 = I sign, "
                        "bit 1 = Q sign, 1 = positive; auto-incrementing bin index).")
        self.comb += [
            self._config.fields.fft_size.eq(self.fft_size),
            self._config.fields.coeff_frac.eq(self.coeff_frac),
            self.train.eq(self._control.fields.train),
            self.ref_rst.eq(self._ref_rst.re),
            self.ref_data.eq(self._ref.storage),
            self.ref_we.eq(self._ref.re),
        ]
