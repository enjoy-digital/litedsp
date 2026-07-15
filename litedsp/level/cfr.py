#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

import numpy as np

from migen import *

from litex.gen import *

from litex.soc.interconnect.csr import *
from litex.soc.interconnect     import stream

from litedsp.common import check, iq_layout, rounded, saturated, scaled, add_bypass, add_bypass_csr

# CFR Pulse / Reciprocal LUT -------------------------------------------------------------------------

def cfr_pulse(pulse_span=16, data_width=16, cutoff=0.25):
    """Unit-peak low-pass cancellation pulse (Hamming-windowed sinc, RRC-like).

    Returns ``pulse_span + 1`` signed Q1.(N-1) taps, normalized so the center tap is full
    scale (unit peak). The spectrum is contained below ``cutoff`` (normalized, 0..0.5), so
    subtracting scaled copies of the pulse stays (mostly) inside the signal band and bounds
    the ACLR degradation: set ``cutoff`` to the signal's one-sided bandwidth.
    """
    check(pulse_span >= 4 and (pulse_span % 2) == 0, "expected pulse_span >= 4 and even")
    check(0.0 < cutoff <= 0.5, "expected 0.0 < cutoff <= 0.5")
    n = pulse_span + 1
    m = np.arange(n) - pulse_span/2
    h = 2*cutoff*np.sinc(2*cutoff*m)*np.hamming(n)
    h = h/h[pulse_span//2]                              # Unit peak.
    scale = (1 << (data_width - 1)) - 1
    return [int(round(v*scale)) for v in h]

def cfr_recip_lut(index_bits=6, frac_bits=15):
    """Reciprocal LUT for the divider-free ``(|x| - T)/|x|`` (see :class:`LiteDSPCFR`).

    Entry ``k`` approximates ``1/u`` over ``u in [1 + k/2**index_bits, 1 + (k+1)/2**index_bits)``
    by the interval midpoint, as an unsigned Q0.``frac_bits`` value:
    ``round(2**frac_bits / (1 + (k + 0.5)/2**index_bits))``. Midpoint max error <= 2**-7
    relative (~0.8%) for the default 64 entries.
    """
    return [int(round((1 << frac_bits)/(1 + (k + 0.5)/(1 << index_bits))))
            for k in range(1 << index_bits)]

# CFR (Peak Cancellation) ----------------------------------------------------------------------------

# Reciprocal-LUT fixed-point geometry (mirrored by test/models.py:cfr_model).
CFR_INDEX_BITS = 6   # Reciprocal LUT depth = 64 entries.
CFR_RECIP_FRAC = 15  # Reciprocal LUT fractional bits (Q0.15).

@ResetInserter()
class LiteDSPCFR(LiteXModule):
    """Crest-factor reduction by peak cancellation: subtract a scaled low-pass pulse per peak.

    Detects local maxima of the alpha-max-beta-min magnitude estimate (same idiom as
    :class:`~litedsp.level.agc.LiteDSPAGC`: ``|x| ~ max + min/4``) that exceed the runtime
    ``threshold`` T, and subtracts a cancellation pulse centered on the peak from the
    delay-line-matched stream: ``y[n] = x[n] - g * x_pk * p[n - n_pk]`` with
    ``g = (|x_pk| - T)/|x_pk|``, so the peak magnitude lands at ~T while the correction
    energy stays inside the pulse's low-pass band (bounded ACLR/EVM impact, see
    :func:`cfr_pulse`).

    The division in ``g`` is avoided with a shift-normalized reciprocal LUT: ``|x_pk|`` is
    left-shifted by its leading-zero count ``e`` onto ``[0.5, 1.0) * 2**data_width``
    (mantissa ``u in [1, 2)``), a 64-entry midpoint LUT (:func:`cfr_recip_lut`) gives
    ``r ~ 1/u`` in Q0.15, and ``g = (((|x_pk| - T) << e) * r) >> 15`` (round-half-up,
    clamped to Q0.15 max). Max relative error ~0.8% of ``g`` (LUT interval half-width
    2**-7), i.e. <1% residual-peak error — well under the alpha-max-beta-min estimate
    spread (-11.6%..+3.1% vs the true magnitude), which sets the residual-peak accuracy.

    Single-engine simplification: one pulse generator; while it plays a pulse
    (``pulse_span + 1`` samples), further above-threshold local maxima pass uncorrected and
    are counted in ``missed_count`` (``peak_count`` counts fired/corrected peaks). Cycle
    latency is 1; the datapath additionally delays the signal by ``self.delay =
    pulse_span/2 + 2`` samples (delay line + 1-sample local-max lookahead) so the pulse
    center aligns with the peak.

    Parameters
    ----------
    pulse_span : int
        Cancellation pulse span in samples (even, >= 4; the pulse has ``pulse_span + 1``
        taps). Longer = more spectrally contained corrections, but longer engine busy time
        (more missed peaks at high peak density) and a deeper delay line.
    threshold : int
        Reset value of the runtime peak threshold, compared against the alpha-max-beta-min
        magnitude estimate (~|x|, full-scale units). Defaults to ``2**data_width - 1``
        (above any reachable estimate, i.e. correction disabled until programmed).
    cutoff : float
        Pulse low-pass cutoff in normalized frequency (0..0.5]; set to the signal's
        one-sided bandwidth so corrections stay in-band (see :func:`cfr_pulse`).
    """
    def __init__(self, data_width=16, pulse_span=16, threshold=None, cutoff=0.25, with_csr=True):
        check(data_width >= 8, "expected data_width >= 8")
        # pulse_span/cutoff are validated by cfr_pulse.
        self.pulse = cfr_pulse(pulse_span, data_width, cutoff)
        if threshold is None:
            threshold = (1 << data_width) - 1  # Above any magnitude estimate: disabled.
        self.data_width = data_width
        self.pulse_span = pulse_span
        self.latency    = 1                    # Cycle latency (see also self.delay).
        self.delay      = pulse_span//2 + 2    # Datapath delay in samples (delay line + lookahead).
        self.sink   = stream.Endpoint(iq_layout(data_width))
        self.source = stream.Endpoint(iq_layout(data_width))
        self.threshold    = Signal(data_width, reset=threshold)  # Peak threshold (~|x|).
        self.peak_count   = Signal(32)                           # Fired (corrected) peaks.
        self.missed_count = Signal(32)                           # Peaks skipped while busy.

        # # #

        W = data_width
        L = pulse_span + 1        # Pulse length in taps.
        D = self.delay
        beta_shift = 2            # Alpha-max-beta-min beta = 1/4 (the AGC idiom).

        # Handshake.
        # ----------
        adv  = Signal()  # Pipeline drains (output slot free or being consumed).
        xfer = Signal()  # A sample is consumed this beat.
        self.comb += [
            adv.eq(self.source.ready | ~self.source.valid),
            self.sink.ready.eq(adv),
            xfer.eq(self.sink.valid & adv),
        ]

        # Magnitude Estimate + Local-Max Peak Detection.
        # ----------------------------------------------
        # |x| ~ max + min/2**beta_shift on the incoming sample; the peak candidate is the
        # *previous* sample (1-sample lookahead): above threshold, at least as large as the
        # current estimate, strictly larger than the one before it.
        ai, aq = Signal(W + 1), Signal(W + 1)
        self.comb += [
            ai.eq(Mux(self.sink.i[-1], -self.sink.i, self.sink.i)),  # |I|.
            aq.eq(Mux(self.sink.q[-1], -self.sink.q, self.sink.q)),  # |Q|.
        ]
        mag = Signal(W)  # <= 1.25 * 2**(W-1), fits W bits.
        self.comb += mag.eq(Mux(ai > aq, ai + (aq >> beta_shift), aq + (ai >> beta_shift)))
        pm1, pm2 = Signal(W), Signal(W)       # mag one/two samples ago.
        pi,  pq  = Signal((W, True)), Signal((W, True))  # Peak candidate sample (x one sample ago).
        self.sync += If(xfer, pm2.eq(pm1), pm1.eq(mag), pi.eq(self.sink.i), pq.eq(self.sink.q))
        peak = Signal()
        self.comb += peak.eq((pm1 > self.threshold) & (pm1 >= mag) & (pm1 > pm2))

        # Correction Coefficient (divider-free g = (|x_pk| - T)/|x_pk|).
        # --------------------------------------------------------------
        # Normalize pm1 by its leading-zero count, look the mantissa reciprocal up in a
        # 64-entry midpoint LUT (Q0.15), scale the excess d = pm1 - T by it, then form the
        # complex pulse amplitude a = g * x_pk (round + saturate). Evaluated combinationally
        # from the *registered* pm1/pi/pq and sampled only on a fire beat.
        d = Signal(W)
        e = Signal(max=W)  # Leading-zero count of pm1 (pm1 >= 1 whenever peak is set).
        self.comb += d.eq(pm1 - self.threshold)
        for k in range(W):
            self.comb += If(pm1[k], e.eq(W - 1 - k))  # Last (highest) set bit wins.
        mn  = Signal(W)                 # pm1 normalized to [2**(W-1), 2**W).
        dn  = Signal(W)                 # d << e (same normalization).
        rec = Signal(CFR_RECIP_FRAC)    # ~1/u, Q0.15.
        self.comb += [
            mn.eq(pm1 << e),
            dn.eq(d << e),
            rec.eq(Array(cfr_recip_lut(CFR_INDEX_BITS, CFR_RECIP_FRAC))
                   [mn[W - 1 - CFR_INDEX_BITS:W - 1]]),
        ]
        gmax  = (1 << (W - 1)) - 1
        g_raw = Signal(W + 1)
        g     = Signal(W - 1)           # g = (|x_pk| - T)/|x_pk|, Q0.(W-1), clamped < 1.0.
        self.comb += [
            g_raw.eq(rounded(dn*rec, CFR_RECIP_FRAC)),
            g.eq(Mux(g_raw > gmax, gmax, g_raw)),
        ]
        coef_i, _ = scaled(g*pi, W - 1, W)  # a = g * x_pk (round + saturate).
        coef_q, _ = scaled(g*pq, W - 1, W)

        # Delay Line (advances on real transfers only, so it is handshake-invariant).
        # ----------------------------------------------------------------------------
        dly_i = [Signal((W, True)) for _ in range(D)]
        dly_q = [Signal((W, True)) for _ in range(D)]
        self.sync += If(xfer,
            dly_i[0].eq(self.sink.i),
            dly_q[0].eq(self.sink.q),
            *[dly_i[k].eq(dly_i[k - 1]) for k in range(1, D)],
            *[dly_q[k].eq(dly_q[k - 1]) for k in range(1, D)],
        )

        # Pulse Engine (single generator: new peaks while busy pass uncorrected).
        # -----------------------------------------------------------------------
        prom = Memory(W, L, init=[v & ((1 << W) - 1) for v in self.pulse])
        prp  = prom.get_port(async_read=True)
        self.specials += prom, prp
        busy  = Signal()
        k     = Signal(max=L)           # Pulse tap index.
        a_i   = Signal((W, True))       # Registered complex pulse amplitude a = g * x_pk.
        a_q   = Signal((W, True))
        fire  = Signal()
        self.comb += [fire.eq(peak & ~busy), prp.adr.eq(k)]
        self.sync += If(xfer,
            If(busy,
                k.eq(k + 1),
                If(k == (L - 1), busy.eq(0)),
            ),
            If(fire,
                busy.eq(1),
                k.eq(0),
                a_i.eq(coef_i),
                a_q.eq(coef_q),
                self.peak_count.eq(self.peak_count + 1),
            ).Elif(peak,
                self.missed_count.eq(self.missed_count + 1),
            ),
        )

        # Correction + Output (idempotent on bubble beats: state above only moves on xfer).
        # ---------------------------------------------------------------------------------
        coeff  = Signal((W, True))
        pc_i   = Signal((2*W, True))    # Full-width products (avoid context-sized truncation).
        pc_q   = Signal((2*W, True))
        corr_i = Signal((W + 1, True))
        corr_q = Signal((W + 1, True))
        self.comb += [
            coeff.eq(prp.dat_r),
            pc_i.eq(a_i*coeff),
            pc_q.eq(a_q*coeff),
            If(busy,
                corr_i.eq(rounded(pc_i, W - 1)),
                corr_q.eq(rounded(pc_q, W - 1)),
            ),
        ]
        valid = Signal()
        self.sync += If(adv,
            self.source.i.eq(saturated(dly_i[-1] - corr_i, W)),
            self.source.q.eq(saturated(dly_q[-1] - corr_q, W)),
            valid.eq(self.sink.valid),
        )
        self.comb += self.source.valid.eq(valid)

        # Bypass.
        # -------
        add_bypass(self)

        # CSR.
        # ----
        if with_csr:
            self.add_csr()

    def add_csr(self):
        add_bypass_csr(self)
        self._threshold = CSRStorage(self.data_width, reset=self.threshold.reset.value,
            name="threshold",
            description="Peak threshold, in alpha-max-beta-min magnitude units (~|x|).")
        self._peaks  = CSRStatus(32, name="peaks",
            description="Corrected peaks (cancellation pulses fired). Wraps.")
        self._missed = CSRStatus(32, name="missed",
            description="Uncorrected peaks (detected while the pulse engine was busy). Wraps.")
        self.comb += [
            self.threshold.eq(self._threshold.storage),
            self._peaks.status.eq(self.peak_count),
            self._missed.status.eq(self.missed_count),
        ]
