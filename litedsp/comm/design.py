#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side code design for the communications extras: GF(2^m) tables, BCH generators, Hamming
parity columns, Gray codes, FSK deviation words and HDLC framing."""

import math

from litedsp.common import check

# Galois fields ------------------------------------------------------------------------------------

PRIMITIVE_POLYS = {3: 0b1011, 4: 0b10011, 5: 0b100101, 6: 0b1000011, 7: 0b10001001, 8: 0b100011101}

def gf_tables(m, poly=None):
    """``(exp, log)`` tables of GF(2^m) for the primitive polynomial ``poly`` (default table)."""
    check(3 <= m <= 8, "expected 3 <= m <= 8")
    poly = poly or PRIMITIVE_POLYS[m]
    n = (1 << m) - 1
    exp, log = [0]*(2*n), [0]*(n + 1)
    x = 1
    for i in range(n):
        exp[i] = x
        log[x] = i
        x <<= 1
        if x & (1 << m):
            x ^= poly
    for i in range(n, 2*n):
        exp[i] = exp[i - n]
    return exp, log

def gf_mul_int(a, b, m, poly=None):
    """Bit-serial product in GF(2^m) (no tables)."""
    poly = poly or PRIMITIVE_POLYS[m]
    r = 0
    for _ in range(m):
        if b & 1:
            r ^= a
        b >>= 1
        a <<= 1
        if a & (1 << m):
            a ^= poly
    return r

def _poly_mul(a, b):
    r = 0
    while b:
        if b & 1:
            r ^= a
        a <<= 1
        b >>= 1
    return r

def minimal_polynomial(elem_power, m, poly=None):
    """Minimal polynomial over GF(2) of alpha^elem_power (integer bit vector, MSB = highest
    degree)."""
    exp, log = gf_tables(m, poly)
    n = (1 << m) - 1
    roots, r = set(), elem_power % n
    while r not in roots:
        roots.add(r)
        r = (2*r) % n
    # Product of (x + alpha^r): coefficients in GF(2^m), reduce to GF(2).
    coeffs = [1]                                      # Polynomial in x, coefficient list low..high.
    for r in sorted(roots):
        a = exp[r]
        new = [0]*(len(coeffs) + 1)
        for i, c in enumerate(coeffs):
            new[i] ^= gf_mul_int(c, a, m, poly)
            new[i + 1] ^= c
        coeffs = new
    check(all(c in (0, 1) for c in coeffs), "minimal polynomial not over GF(2)")
    return sum(c << i for i, c in enumerate(coeffs))

def bch_generator(m=4, t=2, poly=None):
    """``(g, n, k)`` of the narrow-sense binary BCH code over GF(2^m) correcting ``t`` errors:
    ``g`` = lcm of the minimal polynomials of alpha^1 .. alpha^2t (integer bit vector)."""
    check(1 <= t and 2*t < (1 << m) - 1, "expected 1 <= t < (2^m - 1) / 2")
    n = (1 << m) - 1
    g, done = 1, set()
    for i in range(1, 2*t + 1):
        r = i % n
        if r in done:
            continue
        mp = minimal_polynomial(r, m, poly)
        rr = r
        while rr not in done:
            done.add(rr)
            rr = (2*rr) % n
        g = _poly_mul(g, mp)
    k = n - (g.bit_length() - 1)
    check(k >= 1, "expected k >= 1 (t too large for m)")
    return g, n, k

# Hamming ------------------------------------------------------------------------------------------

def hamming_columns(m=3):
    """Parity-check columns of the (2^m - 1, 2^m - 1 - m) Hamming code in message order: the
    non-power-of-two column indexes (each an m-bit syndrome) followed by the parity columns
    (powers of two), so codeword bit i has syndrome ``columns[i]``."""
    check(2 <= m <= 8, "expected 2 <= m <= 8")
    n = (1 << m) - 1
    data = [c for c in range(1, n + 1) if c & (c - 1)]
    parity = [1 << i for i in range(m)]
    return data + parity

def hamming_params(m=3, secded=False):
    """``(n, k)`` of the Hamming (or SECDED extended) code."""
    n = (1 << m) - 1
    return (n + 1 if secded else n), n - m

# Gray ---------------------------------------------------------------------------------------------

def gray_encode(b):
    return b ^ (b >> 1)

def gray_decode(g):
    b = g
    while g:
        g >>= 1
        b ^= g
    return b

# FSK ----------------------------------------------------------------------------------------------

def fsk_deviation(h=1.0, sps=4, bits_per_symbol=1, phase_bits=32):
    """Deviation word for :class:`LiteDSPFSKModulator` / :class:`LiteDSPFrequencyModulator` fed
    with symbol levels ``l * 2**(dw-1-bps)``: modulation index ``h`` = tone spacing / symbol rate
    (``h = 0.5`` is MSK / GMSK), the outermost level lands at ``+/- h * Rs / 2``."""
    L = 1 << bits_per_symbol
    return int(round(h*(1 << phase_bits)*L/(2*sps*(L - 1))))

# HDLC ---------------------------------------------------------------------------------------------

HDLC_FLAG = 0x7E

def hdlc_fcs(bits):
    """X.25 / HDLC CRC-16 (0x1021 reflected = 0x8408, init and xor 0xFFFF) over an LSB-first bit
    list; returns the 16 FCS bits to append (LSB first), i.e. the ones-complement, transmitted
    low byte first."""
    crc = 0xFFFF
    for b in bits:
        crc ^= int(b) & 1
        crc = (crc >> 1) ^ 0x8408 if crc & 1 else crc >> 1
    crc ^= 0xFFFF
    return [(crc >> i) & 1 for i in range(16)]

def hdlc_stuff(bits):
    """Insert a 0 after five consecutive ones."""
    out, ones = [], 0
    for b in bits:
        out.append(int(b))
        ones = ones + 1 if b else 0
        if ones == 5:
            out.append(0)
            ones = 0
    return out

def hdlc_unstuff(bits):
    """Remove the stuffed zeros (the inverse of :func:`hdlc_stuff` on a clean frame)."""
    out, ones = [], 0
    skip = False
    for b in bits:
        if skip:
            skip = False
            ones = 0
            continue
        out.append(int(b))
        ones = ones + 1 if b else 0
        if ones == 5:
            skip = True
    return out

def hdlc_frame_bits(payload_bits, preamble=1):
    """Complete framed bit stream: ``preamble`` flags, stuffed payload + FCS, a closing flag
    (flags LSB first)."""
    flag = [(HDLC_FLAG >> i) & 1 for i in range(8)]
    body = hdlc_stuff(list(payload_bits) + hdlc_fcs(payload_bits))
    return flag*preamble + body + flag
