# LiteDSP Fixed-Point Conventions

LiteDSP samples are signed two's-complement **Qm.n** fixed-point: `m` integer bits (including
the sign bit) and `n` fractional bits, total width `m + n`. The default sample format is
**Q1.15** (16-bit, range `[-1.0, +1.0)`), matching typical RF data paths (e.g. AD9361).

Helpers live in `litedsp/common.py`; their NumPy twins (used by the golden models) live in
`test/common.py` and produce **identical** results so simulation can be checked bit-for-bit.

## Format descriptor

`Qmn(m, n)` describes a format: `.width`, `.shape` (Migen `(width, True)`), `.scale` (`2**n`),
`.to_float()`, `.from_float()` (clamped). `Q15 = Qmn(1, 15)` is the default.

## Rescaling rule

After a multiply or accumulation, results are wider than a sample and must be brought back to
the target width. **Always** round then saturate — never slice/truncate or let values wrap:

- `rounded(value, shift)` — arithmetic right shift by `shift`, rounding half up
  (`floor(value/2**shift + 0.5)`).
- `saturated(value, out_width)` — clamp to the signed `out_width` range.
- `scaled(value, shift, out_width)` — `rounded` then `saturated`; returns `(result, overflow)`.

Typical shifts:

| Operation                         | Operand formats        | Shift to return to Qm.n |
|-----------------------------------|------------------------|-------------------------|
| sample × coefficient (FIR, mixer) | Q1.15 × Q1.15 → Q2.30  | `data_width - 1` (15)   |
| sample × gain mantissa            | Q1.15 × Q2.14 → Q3.29  | `gain_frac (=14) + extra shift` |

## Why this matters

The original tetra blocks truncated (`mixer >> 15`, `acc[15:32]`) and let the multi-channel
sum wrap. Truncation adds a DC bias and ~6 dB more quantization noise than rounding; wrapping
turns a loud sum into garbage. Centralizing round+saturate makes every block consistent,
testable against a NumPy reference, and free of these defects.
