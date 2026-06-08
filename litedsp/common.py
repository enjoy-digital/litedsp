#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Shared layouts and fixed-point helpers for LiteDSP.

All LiteDSP blocks operate on signed two's-complement fixed-point samples in Qm.n format
(``m`` integer bits including sign, ``n`` fractional bits, total width ``m + n``). The
default sample format is Q1.15 (16-bit, range [-1.0, +1.0)), matching typical RF data paths.

Streaming uses LiteX ``stream.Endpoint``: real-valued blocks carry a single ``data`` field,
complex (I/Q) blocks carry ``i`` and ``q`` fields (see :func:`real_layout` / :func:`iq_layout`).

Downsizing (after a multiply or accumulation) must go through :func:`rounded` then
:func:`saturated` (or :func:`scaled`, which does both) so every block handles scaling and
overflow consistently instead of silently truncating/wrapping.
"""

from migen import *

# Layouts ------------------------------------------------------------------------------------------

def real_layout(data_width=16):
    """Stream payload layout for a real signed sample."""
    return [("data", (data_width, True))]

def iq_layout(data_width=16):
    """Stream payload layout for complex signed I/Q samples (Q1.(N-1) by default)."""
    return [
        ("i", (data_width, True)),
        ("q", (data_width, True)),
    ]

# Fixed-Point Format -------------------------------------------------------------------------------

class Qmn:
    """Signed fixed-point format descriptor.

    Parameters
    ----------
    m : int
        Integer bits, **including** the sign bit.
    n : int
        Fractional bits.

    Example: ``Qmn(1, 15)`` is Q1.15 (16-bit, range [-1.0, +1.0)).
    """
    def __init__(self, m, n):
        assert m >= 1 and n >= 0
        self.m     = m
        self.n     = n
        self.width = m + n

    @property
    def shape(self):
        """Migen signed shape tuple ``(width, True)``."""
        return (self.width, True)

    @property
    def scale(self):
        """Number of LSBs per integer unit (``2**n``)."""
        return 1 << self.n

    def to_float(self, x):
        """Convert a raw integer sample to float."""
        return x / self.scale

    def from_float(self, x):
        """Convert a float to a raw integer sample, clamped to the representable range."""
        v   = int(round(x * self.scale))
        lo  = -(1 << (self.width - 1))
        hi  =  (1 << (self.width - 1)) - 1
        return max(lo, min(hi, v))

    def __repr__(self):
        return f"Q{self.m}.{self.n}"

# Default sample format.
Q15 = Qmn(1, 15)

# Fixed-Point Helpers ------------------------------------------------------------------------------
#
# These return Migen expressions (use inside self.comb / self.sync). They mirror the NumPy
# reference helpers in test/models.py so simulation matches the golden model bit-for-bit.

def rounded(value, shift):
    """Arithmetic right-shift of signed ``value`` by ``shift`` bits, rounding half up.

    Equivalent to ``floor(value / 2**shift + 0.5)`` (round half toward +inf). With
    ``shift == 0`` it returns ``value`` unchanged.
    """
    if shift == 0:
        return value
    return (value + (1 << (shift - 1))) >> shift

def overflow(value, out_width):
    """Expression that is 1 when signed ``value`` does not fit in ``out_width`` bits."""
    hi =  (1 << (out_width - 1)) - 1
    lo = -(1 << (out_width - 1))
    return (value > hi) | (value < lo)

def saturated(value, out_width):
    """Clamp signed ``value`` to the signed ``out_width`` range (symmetric two's-complement)."""
    hi =  (1 << (out_width - 1)) - 1
    lo = -(1 << (out_width - 1))
    return Mux(value > hi, hi, Mux(value < lo, lo, value))

def scaled(value, shift, out_width):
    """Round ``value`` down by ``shift`` bits then saturate to ``out_width``.

    Returns ``(result, ovf)`` where ``result`` is the saturated rounded expression and
    ``ovf`` is a 1-bit overflow expression (set when rounding overflowed ``out_width``).
    """
    r = rounded(value, shift)
    return saturated(r, out_width), overflow(r, out_width)
