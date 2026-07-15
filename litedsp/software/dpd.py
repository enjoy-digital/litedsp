#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side DPD adaptation (indirect learning) for the ``LiteDSPDPD`` actuator.

The fabric actuator (:class:`litedsp.level.dpd.LiteDSPDPD`) only evaluates per-tap complex-
gain LUTs at the sample rate; identifying those LUTs is a least-squares problem solved here,
on the host, from captured data — the standard split of every deployed DPD (adaptation runs
at capture rate, not sample rate, and can iterate/evolve freely in software).

Indirect-learning workflow::

    from litedsp.software.dpd     import DPDAdapter
    from litedsp.software.drivers import DPDDriver

    adapter = DPDAdapter(n_taps=3, lut_depth=64, coeff_frac=14)
    # 1. Capture time-aligned records through the capture path (LiteDSPCapture / DMA):
    #    pa_input  = actuator output driving the PA, pa_output = PA feedback receiver.
    adapter.fit(pa_input, pa_output)                 # LS postdistorter -> predistorter LUTs.
    adapter.program(DPDDriver(bus, "dpd"))           # 2. Program the fabric LUTs.
    # 3. Capture again with DPD engaged and refit (1-2 iterations converge).

The fit normalizes the PA output by its estimated linear gain, bins it with the actuator's
exact integer magnitude/indexing arithmetic (so LUT bins align bit-for-bit with the
hardware), solves the LUT-basis least-squares postdistorter with ``numpy.linalg.lstsq`` and
quantizes to the Q2.``coeff_frac`` LUT format. :func:`simulate_pa` provides a synthetic
Saleh + memory PA for closed-loop testing without hardware.
"""

import numpy as np

# Fixed-point helpers (mirror litedsp.level.dpd / test.models bit-for-bit) ---------------------------

def _saturated(value, width):
    hi = (1 << (width - 1)) - 1
    lo = -(1 << (width - 1))
    return np.clip(np.asarray(value, dtype=np.int64), lo, hi)

def _scaled(value, shift, width):
    """Round-half-up right shift + saturate, matching ``litedsp.common.scaled``."""
    value = np.asarray(value, dtype=np.int64)
    if shift:
        value = (value + (1 << (shift - 1))) >> shift
    return _saturated(value, width)

def _delayed(x, m):
    x = np.asarray(x, np.int64)
    return np.concatenate([np.zeros(m, np.int64), x[:len(x) - m]]) if m else x

# DPD Adapter ----------------------------------------------------------------------------------------

class DPDAdapter:
    """Indirect-learning least-squares adaptation for the ``LiteDSPDPD`` actuator.

    Parameters mirror the actuator's construction parameters and must match the target
    block. LUTs start at the identity (tap 0 = 1.0 + 0j, memory taps = 0); :meth:`fit`
    replaces them from a captured (PA input, PA output) record.
    """
    def __init__(self, n_taps=3, lut_depth=64, coeff_frac=14, data_width=16):
        if lut_depth < 2 or lut_depth & (lut_depth - 1):
            raise ValueError("expected lut_depth a power of two >= 2")
        self.n_taps     = n_taps
        self.lut_depth  = lut_depth
        self.coeff_frac = coeff_frac
        self.data_width = data_width
        self.gain       = None
        self.luts       = [(np.full(lut_depth, (1 << coeff_frac) if m == 0 else 0, np.int64),
                            np.zeros(lut_depth, np.int64)) for m in range(n_taps)]

    # Binning (bit-exact vs the gateware) ----------------------------------------------------------

    def magnitude(self, i, q):
        """Two-region alpha-max-beta-min estimate ``max(hi, hi - hi/8 + lo/2)`` (gateware-exact)."""
        ai = np.abs(np.asarray(i, np.int64))
        aq = np.abs(np.asarray(q, np.int64))
        hi = np.maximum(ai, aq)
        lo = np.minimum(ai, aq)
        return np.maximum(hi, hi - (hi >> 3) + (lo >> 1))

    def lut_index(self, i, q):
        """LUT bin per sample: top magnitude bits below full scale, clamped to the last entry."""
        shift = self.data_width - 1 - int(np.log2(self.lut_depth))
        return np.minimum(self.magnitude(i, q) >> shift, self.lut_depth - 1)

    # Adaptation -----------------------------------------------------------------------------------

    def estimate_gain(self, pa_input, pa_output):
        """Linear (small-signal) complex PA gain: LS fit on the weakest half of the samples."""
        u = np.asarray(pa_input,  np.complex128)
        y = np.asarray(pa_output, np.complex128)
        r = np.abs(u)
        sel = (r <= np.median(r)) & (r > 0)
        return np.vdot(u[sel], y[sel]) / np.vdot(u[sel], u[sel])

    def fit(self, pa_input, pa_output, gain=None):
        """Fit the predistorter LUTs by indirect learning and return them.

        ``pa_input`` (the actuator output driving the PA) and ``pa_output`` (the feedback
        capture) are time-aligned complex arrays in LSB units (as the capture drivers return
        them). The PA output is normalized by ``gain`` (estimated once when None, then
        reused across iterations) and quantized; a postdistorter ``F(y/G) ~= pa_input`` is
        solved by least squares on the LUT-bin basis — one complex gain per (tap, magnitude
        bin) — and stored (quantized to Q2.``coeff_frac``) as the predistorter LUTs.
        Unvisited bins take the nearest fitted neighbor (tap 0) or zero (memory taps).
        """
        u = np.asarray(pa_input,  np.complex128)
        y = np.asarray(pa_output, np.complex128)
        if gain is None:
            gain = self.gain if self.gain is not None else self.estimate_gain(u, y)
        self.gain = gain
        # Quantize the normalized feedback: the postdistorter's input domain must be the
        # integer sample domain the actuator sees, or LUT bins would not align.
        zi = _saturated(np.round((y/gain).real), self.data_width)
        zq = _saturated(np.round((y/gain).imag), self.data_width)
        n  = len(zi)
        # LUT-bin basis regression matrix: column (m, b) holds z[k-m] where its bin is b.
        A = np.zeros((n, self.n_taps*self.lut_depth), np.complex128)
        counts = np.zeros((self.n_taps, self.lut_depth), np.int64)
        for m in range(self.n_taps):
            di, dq = _delayed(zi, m), _delayed(zq, m)
            idx = self.lut_index(di, dq)
            A[np.arange(n), m*self.lut_depth + idx] = di + 1j*dq
            np.add.at(counts[m], idx, 1)
        c = np.linalg.lstsq(A, u, rcond=None)[0].reshape(self.n_taps, self.lut_depth)
        # Unvisited bins: nearest fitted neighbor (tap 0) / zero (memory taps), so sparsely
        # exercised amplitude ranges degrade gracefully instead of applying a zero gain.
        for m in range(self.n_taps):
            filled = np.nonzero(counts[m])[0]
            if len(filled) == 0:
                c[m] = 1.0 if m == 0 else 0.0
                continue
            for b in np.nonzero(counts[m] == 0)[0]:
                c[m][b] = c[m][filled[np.argmin(np.abs(filled - b))]] if m == 0 else 0.0
        self.luts = self.quantize(c)
        return self.luts

    def quantize(self, gains):
        """Quantize per-tap complex gain arrays to the LUT format (signed Q2.``coeff_frac``)."""
        scale = 1 << self.coeff_frac
        lo, hi = -(2*scale), 2*scale - 1
        return [(np.clip(np.round(np.asarray(g).real*scale), lo, hi).astype(np.int64),
                 np.clip(np.round(np.asarray(g).imag*scale), lo, hi).astype(np.int64))
                for g in gains]

    def apply(self, i, q, luts=None):
        """Bit-exact actuator prediction with the current (or given) integer LUTs.

        Mirrors the gateware arithmetic exactly (host-side verification / predistorted-drive
        computation without hardware). Returns integer (i, q) arrays.
        """
        i = np.asarray(i, np.int64)
        q = np.asarray(q, np.int64)
        acc_i = np.zeros(len(i), np.int64)
        acc_q = np.zeros(len(q), np.int64)
        for m, (lut_i, lut_q) in enumerate(self.luts if luts is None else luts):
            xi, xq = _delayed(i, m), _delayed(q, m)
            idx = self.lut_index(xi, xq)
            acc_i += xi*np.asarray(lut_i, np.int64)[idx] - xq*np.asarray(lut_q, np.int64)[idx]
            acc_q += xi*np.asarray(lut_q, np.int64)[idx] + xq*np.asarray(lut_i, np.int64)[idx]
        return (_scaled(acc_i, self.coeff_frac, self.data_width),
                _scaled(acc_q, self.coeff_frac, self.data_width))

    def program(self, driver):
        """Write the fitted LUTs to the actuator through a ``DPDDriver``."""
        driver.load(self.luts, coeff_frac=self.coeff_frac)

# Synthetic PA ---------------------------------------------------------------------------------------

def simulate_pa(x, alpha_a=1.9638, beta_a=0.9945, alpha_p=2.5293, beta_p=2.8168,
    memory=(1.0, 0.08, 0.02)):
    """Synthetic power amplifier for closed-loop DPD testing without hardware.

    Saleh TWT envelope model (the classic fitted parameters) followed by a short memory FIR
    (Hammerstein structure, mild memory)::

        A(r)   = alpha_a * r / (1 + beta_a * r**2)          # AM/AM (compression).
        phi(r) = alpha_p * r**2 / (1 + beta_p * r**2)       # AM/PM (radians).
        y[n]   = sum_k memory[k] * NL(x[n-k])

    ``x`` is complex, normalized so ``|x| = 1.0`` is the AM/AM saturation region (drive
    around 0.15..0.20 RMS for a realistic operating point). Returns the complex PA output
    (small-signal gain ``alpha_a * memory[0]``).
    """
    x = np.asarray(x, np.complex128)
    r = np.abs(x)
    w = x * (alpha_a/(1 + beta_a*r**2)) * np.exp(1j*(alpha_p*r**2/(1 + beta_p*r**2)))
    y = np.zeros_like(w)
    for k, h in enumerate(memory):
        y[k:] += h*(w[:len(w) - k] if k else w)
    return y
