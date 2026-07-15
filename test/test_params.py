#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Registry-driven parameter validation: invalid constructor parameters raise ValueError.

Generic vectors are derived from each parameter's reflected kind (zero/negative widths and
factors); block-specific vectors cover the constraints the generic rules cannot guess. The
constructor contract (litedsp.common.check) survives ``python -O`` — unlike ``assert``.
"""

import unittest

from litedsp.flow import registry as flow_registry
from litedsp.flow.metadata import _accepts_with_csr

# Parameters where zero/negative values must be rejected when the block validates them.
NONPOSITIVE_REJECTED = {
    "n_taps", "decimation", "interpolation", "n_stages", "diff_delay", "lut_depth", "N",
    "fft_size", "n_samples", "n_channels", "depth", "modulus", "n_sum",
}

# Block-specific invalid vectors (beyond the generic non-positive rules).
SPECIFIC = [
    ("cic_decimator",   {"decimation": 1}),                # CIC needs >= 2.
    ("cic_interpolator", {"interpolation": 1}),
    ("nco",             {"lut_depth": 1000}),              # Power of two required.
    ("fft",             {"N": 100}),
    ("fft_iter",        {"N": 100}),
    ("parallel_fft",    {"N": 100}),
    ("parallel_fft",    {"N": 4}),                         # Power of two >= 8 required.
    ("parallel_fft",    {"n_samples": 4}),                 # Only P=2 landed (P=4 follow-up).
    ("psd",             {"N": 100}),
    ("hilbert",         {"n_taps": 8}),                    # Odd taps required.
    ("decimator",       {"method": "invalid"}),
    ("interpolator",    {"method": "invalid"}),
    ("cp_insert",       {"cp_len": 0}),
    ("cp_insert",       {"cp_len": 64, "fft_size": 64}),   # cp_len < fft_size.
    ("cfr",             {"pulse_span": 7}),                # Even span required.
    ("cfr",             {"pulse_span": 2}),                # >= 4 required.
    ("cfr",             {"cutoff": 0.6}),                  # Normalized cutoff <= 0.5.
    ("dpd",             {"lut_depth": 100}),               # Power of two required.
    ("dpd",             {"lut_depth": 1 << 16}),           # log2(depth) <= data_width - 1.
    ("dpd",             {"coeff_frac": 0}),
    ("cordic_rot",      {"mode": "invalid"}),
    ("timing_recovery", {"ted": "invalid"}),
    ("magnitude",       {"method": "invalid"}),
    ("cfo_estimator",   {"delay": 12}),                    # Power of two required.
    ("cfo_estimator",   {"span_log2": 0}),
    ("block_interleaver",   {"rows": 0}),                  # Interleaving depth I >= 1.
    ("block_interleaver",   {"cols": 0}),
    ("block_deinterleaver", {"rows": 0}),
    ("block_deinterleaver", {"rows": 1, "cols": 1}),       # Block of at least 2 symbols.
    ("rs_encoder",      {"n": 254}),                       # n fixed at 255 over GF(2^8).
    ("rs_encoder",      {"k": 222}),                       # Odd n - k.
    ("rs_decoder",      {"k": 221}),                       # t = 17 > 16.
]

class TestParams(unittest.TestCase):
    def _build(self, spec, override):
        kwargs = dict(spec.kwargs)
        kwargs.update(override)
        if _accepts_with_csr(spec.cls):
            kwargs["with_csr"] = False
        return spec.cls(**kwargs)

    def test_specific_invalid_vectors(self):
        palette = flow_registry.registry()
        for key, bad in SPECIFIC:
            with self.subTest(block=key, kwargs=bad):
                with self.assertRaises(ValueError):
                    self._build(palette[key], bad)

    def test_generic_nonpositive_rejected(self):
        # For every int parameter in the rejected vocabulary, 0 (or -1) must not silently
        # produce a block. ValueError is the contract; blocks that currently accept the
        # value are reported so validation coverage can only grow.
        palette  = flow_registry.registry()
        accepted = []
        for key, spec in sorted(palette.items()):
            for p in spec.params:
                if p.kind != "int" or p.name not in NONPOSITIVE_REJECTED:
                    continue
                bad = -1 if p.name == "depth" else 0
                try:
                    self._build(spec, {p.name: bad})
                    accepted.append(f"{key}.{p.name}")
                except ValueError:
                    pass
                except Exception as e:
                    # Crashing with a random exception is not a contract; record it.
                    accepted.append(f"{key}.{p.name} ({type(e).__name__})")
        known = ALLOWED_UNVALIDATED
        new   = sorted(set(accepted) - known)
        self.assertFalse(new,
            f"parameters accepting 0 without ValueError (add check() or allowlist): {new}")
        gone = sorted(known - set(accepted))
        self.assertFalse(gone,
            f"allowlisted entries now validate (remove from ALLOWED_UNVALIDATED): {gone}")

# Parameters that currently accept 0 (or fail non-ValueError); each is a candidate for a
# validation fix. This list may only shrink.
ALLOWED_UNVALIDATED = set()

if __name__ == "__main__":
    unittest.main()
