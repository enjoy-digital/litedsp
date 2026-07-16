#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Digital predistortion (DPD) actuator: per-tap complex-gain LUTs over delayed samples.

The actuator is the fabric half of a DPD system; adaptation (the LUT identification) runs on
the host, as in every deployed DPD: the sample-rate datapath only evaluates the predistorter,
while the least-squares fit happens offline on captured data (see
:mod:`litedsp.software.dpd`). This keeps the fabric cost at a few multipliers + LUT RAMs and
lets the adaptation algorithm evolve in Python without touching gateware.
"""

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, scaled, add_bypass, add_bypass_csr

# DPD Actuator -------------------------------------------------------------------------------------

@ResetInserter()
class LiteDSPDPD(LiteXModule):
    """Memory-polynomial-lite (GMP-lite) digital predistortion actuator.

    Computes ``y[n] = sum_m x[n-m] * G_m(|x[n-m]|)`` for ``m = 0..n_taps-1``: each branch
    multiplies a delayed input sample by a complex gain looked up from that branch's LUT,
    indexed by the sample's own magnitude. Tap 0 is the memoryless AM/AM + AM/PM corrector;
    the memory taps compensate mild PA memory effects. LUT entries are complex signed
    Q2.``coeff_frac`` pairs (|G| < 2), so the actuator can express the gain expansion +
    counter-rotation a compressing PA needs.

    The magnitude estimate is the two-region alpha-max-beta-min form
    ``max(hi, hi - hi/8 + lo/2)`` with ``hi = max(|I|, |Q|)``, ``lo = min(|I|, |Q|)``
    (shift/add only, ~3% peak error — 4x tighter than the single-region ``hi + lo/4``, which
    matters here because the magnitude quantization directly bounds the achievable
    linearization). The LUT index is the estimate's top ``log2(lut_depth)`` bits below full
    scale (``mag >> (data_width - 1 - log2(lut_depth))``, clamped to the last entry), i.e.
    bin ``b`` covers ``|x|`` in ``[b, b + 1) * 2**(data_width - 1) / lut_depth``.

    LUTs initialize to the identity (tap 0 = 1.0 + 0j everywhere, memory taps = 0), so the
    untrained block is an exact passthrough. They are host-(re)writable through a shared
    sequential write bus with a tap-select field (``lut_tap``/``lut_rst``/``lut_data``/
    ``lut_we`` signals, or the ``lut_tap``/``lut_reset``/``lut`` CSRs): select a tap, strobe
    the pointer reset, then write ``lut_depth`` packed ``{Q, I}`` entries. Program while the
    stream is quiescent (or bypassed): entries take effect as written.

    Fixed point: products are kept full width (data_width + coeff_frac + 3 bits per complex
    component covers |G| < 2 plus the cross-term add), the branch sum adds
    ``ceil(log2(n_taps))`` bits, and a single ``scaled()`` (round-half-up + saturate) by
    ``coeff_frac`` produces the output — identity LUTs reproduce the input bit-exactly.
    Latency is fixed at 4 cycles (magnitude, index, LUT read + complex multiply, sum/scale);
    ``bypass`` passes the input through delay-matched.

    Host adaptation workflow (indirect learning, see :mod:`litedsp.software.dpd`):

    1. Capture time-aligned (PA input, PA output) sample records through the existing
       capture path (``LiteDSPCapture``/DMA) — PA input is this block's output.
    2. ``DPDAdapter.fit(pa_input, pa_output)`` normalizes the PA output by the estimated
       linear gain, bins it with this block's exact magnitude/indexing arithmetic, solves
       the LUT-basis least-squares postdistorter (``numpy.linalg.lstsq``) and quantizes to
       Q2.``coeff_frac``.
    3. ``DPDAdapter.program(DPDDriver(bus, "dpd"))`` writes the LUTs; iterate capture + fit
       once or twice to converge (each iteration refits on the currently-predistorted PA).

    Parameters
    ----------
    n_taps : int
        Memory depth M (number of delayed-sample branches, >= 1). Each tap costs one LUT RAM
        and a complex multiplier (4 real multipliers).
    lut_depth : int
        Entries per gain LUT (power of two, magnitude bins). 64 matches the resolution of
        the magnitude estimate; more mainly costs RAM and thins the per-bin fit statistics.
    coeff_frac : int
        Fractional bits of the LUT entries (signed Q2.``coeff_frac`` per component, 1.0 =
        ``2**coeff_frac``); also the single output rescale shift.
    """
    def __init__(self, data_width=16, n_taps=3, lut_depth=64, coeff_frac=14, with_csr=True):
        check(n_taps >= 1,                            "expected n_taps >= 1")
        check(lut_depth >= 2 and (lut_depth & (lut_depth - 1)) == 0,
                                                      "expected lut_depth a power of two >= 2")
        check(log2_int(lut_depth) <= data_width - 1,  "expected log2(lut_depth) <= data_width - 1")
        check(coeff_frac >= 1,                        "expected coeff_frac >= 1")
        lut_width       = coeff_frac + 2                    # Signed Q2.coeff_frac per component.
        self.data_width = data_width
        self.n_taps     = n_taps
        self.lut_depth  = lut_depth
        self.coeff_frac = coeff_frac
        self.lut_width  = lut_width
        self.latency    = 4
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.lut_tap  = Signal(max=max(n_taps, 2))  # LUT write: tap (branch) select.
        self.lut_data = Signal(2*lut_width)         # LUT write: packed {Q, I} entry.
        self.lut_we   = Signal()                    # LUT write: strobe (auto-incrementing entry).
        self.lut_rst  = Signal()                    # LUT write: reset the entry pointer to 0.

        # # #

        # Handshake.
        # ----------
        adv  = Signal()  # Pipeline drains (output slot free or being consumed).
        xfer = Signal()  # A sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Gain LUTs (one per tap) + shared sequential write bus.
        # ------------------------------------------------------
        # Reset/init = identity: tap 0 all 1.0 + 0j, memory taps all 0 -> exact passthrough.
        one   = 1 << coeff_frac
        wptr  = Signal(max=lut_depth)
        rports = []
        for m in range(n_taps):
            lut = Memory(2*lut_width, lut_depth, init=[one if m == 0 else 0]*lut_depth)
            wp  = lut.get_port(write_capable=True)
            rp  = lut.get_port(async_read=True)
            self.specials += lut, wp, rp
            self.comb += [
                wp.adr.eq(wptr),
                wp.dat_w.eq(self.lut_data),
                wp.we.eq(self.lut_we & (self.lut_tap == m)),
            ]
            rports.append(rp)
        self.sync += If(self.lut_rst, wptr.eq(0)).Elif(self.lut_we,
            If(wptr == (lut_depth - 1), wptr.eq(0)).Else(wptr.eq(wptr + 1)))

        # Delay line (shifts on accepted samples only; tap 0 is the live input).
        # ----------------------------------------------------------------------
        taps_i, taps_q = [self.sink.i], [self.sink.q]
        for m in range(1, n_taps):
            di, dq = Signal((data_width, True)), Signal((data_width, True))
            self.sync += If(xfer, di.eq(taps_i[m - 1]), dq.eq(taps_q[m - 1]))
            taps_i.append(di)
            taps_q.append(dq)

        # Stage 1: magnitude estimate per tap (registered with the sample).
        # -----------------------------------------------------------------
        log2_depth = log2_int(lut_depth)
        idx_shift  = data_width - 1 - log2_depth  # Top bits below full scale index the LUT.
        v1, v2, v3 = Signal(), Signal(), Signal()
        x1_i, x1_q, mag1 = [], [], []
        for m in range(n_taps):
            ai, aq = Signal(data_width), Signal(data_width)      # |I|, |Q| (unsigned).
            hi, lo = Signal(data_width), Signal(data_width)
            est    = Signal(data_width + 1)
            mag    = Signal(data_width + 1)
            self.comb += [
                ai.eq(Mux(taps_i[m][-1], -taps_i[m], taps_i[m])),
                aq.eq(Mux(taps_q[m][-1], -taps_q[m], taps_q[m])),
                hi.eq(Mux(ai > aq, ai, aq)),
                lo.eq(Mux(ai > aq, aq, ai)),
                # Two-region alpha-max-beta-min: max(hi, hi - hi/8 + lo/2), ~3% peak error.
                est.eq(hi - (hi >> 3) + (lo >> 1)),
                mag.eq(Mux(est > hi, est, hi)),
            ]
            xi, xq = Signal((data_width, True)), Signal((data_width, True))
            mr     = Signal(data_width + 1)
            self.sync += If(adv, xi.eq(taps_i[m]), xq.eq(taps_q[m]), mr.eq(mag))
            x1_i.append(xi)
            x1_q.append(xq)
            mag1.append(mr)

        # Stage 2: LUT index clamp. Keeping the magnitude approximation and its wide compare
        # out of the LUT-address register path avoids the former near-100 MHz carry chain.
        # -------------------------------------------------------------------------------
        x2_i, x2_q, idx2 = [], [], []
        for m in range(n_taps):
            raw = Signal(log2_depth + 2)                         # mag >> idx_shift, pre-clamp.
            idx = Signal(log2_depth)
            self.comb += [
                raw.eq(mag1[m] >> idx_shift),
                idx.eq(Mux(raw >= lut_depth, lut_depth - 1, raw)),
            ]
            xi, xq = Signal((data_width, True)), Signal((data_width, True))
            ir     = Signal(log2_depth)
            self.sync += If(adv, xi.eq(x1_i[m]), xq.eq(x1_q[m]), ir.eq(idx))
            x2_i.append(xi)
            x2_q.append(xq)
            idx2.append(ir)

        # Stage 3: LUT read + complex product per tap.
        # --------------------------------------------
        # p = x * G with G signed Q2.coeff_frac: |component| <= 2**(data_width + coeff_frac + 1)
        # (product + cross-term add), held full width.
        prod_w = data_width + lut_width + 1
        p_re, p_im = [], []
        for m in range(n_taps):
            gi, gq = Signal((lut_width, True)), Signal((lut_width, True))
            self.comb += [
                rports[m].adr.eq(idx2[m]),
                gi.eq(rports[m].dat_r[:lut_width]),
                gq.eq(rports[m].dat_r[lut_width:]),
            ]
            pr, pi = Signal((prod_w, True)), Signal((prod_w, True))
            self.sync += If(adv,
                pr.eq(x2_i[m]*gi - x2_q[m]*gq),
                pi.eq(x2_i[m]*gq + x2_q[m]*gi),
            )
            p_re.append(pr)
            p_im.append(pi)

        # Stage 4: branch sum + single rescale (round-half-up + saturate).
        # -----------------------------------------------------------------
        acc_w = prod_w + (n_taps - 1).bit_length()  # + log2(n_taps) accumulation growth.
        acc_i, acc_q = Signal((acc_w, True)), Signal((acc_w, True))
        self.comb += [
            acc_i.eq(sum(p_re)),
            acc_q.eq(sum(p_im)),
        ]
        out_i, _ = scaled(acc_i, coeff_frac, data_width)
        out_q, _ = scaled(acc_q, coeff_frac, data_width)
        self.sync += If(adv,
            v1.eq(self.sink.valid),
            v2.eq(v1),
            v3.eq(v2),
            self.source.i.eq(out_i),
            self.source.q.eq(out_q),
            self.source.valid.eq(v3),
        )

        # Bypass.
        # -------
        add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        self._config = CSRStatus(fields=[
            CSRField("taps",  size=8,  description="Memory taps M (delayed-sample branches)."),
            CSRField("depth", size=16, description="LUT entries per tap (magnitude bins)."),
            CSRField("frac",  size=8,  description="LUT fractional bits (entries are signed Q2.frac)."),
        ])
        self._lut_tap = CSRStorage(self.lut_tap.nbits, name="lut_tap",
            description="Tap (branch) select for LUT writes.")
        self._lut_reset = CSRStorage(1, name="lut_reset",
            description="Reset the LUT entry write pointer to entry 0 (write to strobe).")
        self._lut = CSRStorage(2*self.lut_width, name="lut",
            description="Write the next LUT entry of the selected tap "
                        "({Q, I} packed, each signed Q2.frac; auto-incrementing entry index).")
        add_bypass_csr(self)
        self.comb += [
            self._config.fields.taps.eq(self.n_taps),
            self._config.fields.depth.eq(self.lut_depth),
            self._config.fields.frac.eq(self.coeff_frac),
            self.lut_tap.eq(self._lut_tap.storage),
            self.lut_rst.eq(self._lut_reset.re),
            self.lut_data.eq(self._lut.storage),
            self.lut_we.eq(self._lut.re),
        ]
