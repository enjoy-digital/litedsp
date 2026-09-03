#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Chirp waveform helpers shared by the radar gateware and the golden models: the register
words that program :class:`~litedsp.generation.source.LiteDSPChirp`, a bit-exact NumPy replica of
its output and the matched-filter taps derived from it (NumPy only, not re-exported)."""

import math

import numpy as np

from litedsp.common import check

WINDOWS = ("rect", "hann", "hamming", "blackman")

def chirp_words(bandwidth=0.5, pulse_len=16, phase_bits=32):
    """``(start, rate)`` frequency words for a linear FM pulse sweeping ``-bandwidth/2`` to
    ``+bandwidth/2`` cycles/sample over ``pulse_len`` samples (two's complement start)."""
    check(0.0 < bandwidth <= 1.0, "expected 0 < bandwidth <= 1 (cycles per sample)")
    check(pulse_len >= 2, "expected pulse_len >= 2")
    full  = 1 << phase_bits
    start = (full - int(round(bandwidth/2*full))) % full
    rate  = int(round(bandwidth/pulse_len*full))
    return start, rate

def chirp_reference(pulse_len=16, bandwidth=0.5, data_width=16, phase_bits=32, lut_depth=1024):
    """Bit-exact replica of ``pulse_len`` samples of :class:`LiteDSPChirp` programmed with
    :func:`chirp_words`: ``phase[n] = n*start + rate*n*(n-1)/2 (mod 2**phase_bits)``, the top
    ``log2(lut_depth)`` bits address cos/sin ROMs of ``round(cos * (2**(data_width-1) - 1))``.
    Returns a complex integer array (I + jQ)."""
    start, rate = chirp_words(bandwidth, pulse_len, phase_bits)
    full, addr_bits = 1 << phase_bits, int(math.log2(lut_depth))
    scale = (1 << (data_width - 1)) - 1
    out = np.zeros(pulse_len, np.complex128)
    for n in range(pulse_len):
        phase = (n*start + rate*(n*(n - 1)//2)) % full
        k = phase >> (phase_bits - addr_bits)
        out[n] = complex(int(round(math.cos(2*math.pi*k/lut_depth)*scale)),
                         int(round(math.sin(2*math.pi*k/lut_depth)*scale)))
    return out

def window_taper(window, n):
    """Taper samples in [0, 1] for ``window`` in :data:`WINDOWS`."""
    check(window in WINDOWS, f"expected window in {WINDOWS}")
    return {"rect": np.ones(n), "hann": np.hanning(n), "hamming": np.hamming(n),
            "blackman": np.blackman(n)}[window]

def pulse_compressor_taps(pulse_len=16, bandwidth=0.5, data_width=16, window="rect",
    phase_bits=32, lut_depth=1024):
    """Matched-filter taps ``h = conj(reversed(s)) * taper`` for the :func:`chirp_reference`
    pulse, requantised to full-scale Q1.(N-1): returns ``(real, imag)`` integer lists (the same
    quantisation the gateware and the golden model use)."""
    s = chirp_reference(pulse_len, bandwidth, data_width, phase_bits, lut_depth)
    scale = (1 << (data_width - 1)) - 1
    h = np.conj(s[::-1])/scale*window_taper(window, pulse_len)
    q = lambda v: [int(max(-scale, min(scale, round(float(x)*scale)))) for x in v]
    return q(h.real), q(h.imag)
