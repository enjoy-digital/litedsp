#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""API-policy ratchet over the block registry.

Enforces the conventions documented in doc/interfaces.md and CONTRIBUTING.md so they cannot
regress: constructor params all have defaults (GUI/reflection instantiation), the approved
rate/coefficient parameter vocabulary, latency classification for every processing block,
and ValueError (not AssertionError) on invalid parameters.
"""

import inspect
import unittest

from litedsp.flow import registry
from litedsp.flow.metadata import _real_init

# Parameter names banned from block constructors (renamed in the 2026.07 API harmonization).
# ``N`` stays allowed as the conventional transform size (FFT/PSD/Goertzel/Window).
BANNED_PARAMS = {"R", "L", "M", "factor", "ratio_int", "coeffs", "taps"}

# Blocks whose latency is data-dependent (explicit ``self.latency = None``).
VARIABLE_LATENCY = {
    "arb_resampler", "capture", "cp_insert", "depuncturer", "goertzel", "histogram", "power",
    "psd", "puncturer", "rational_resampler", "rms", "rs_decoder", "rs_encoder",
    "timing_recovery", "welch",
}

# Invalid-parameter vectors: every entry must raise ValueError (incl. under python -O).
INVALID_PARAMS = [
    ("cic_decimator",  {"decimation": 1}),
    ("cic_decimator",  {"n_stages": 0}),
    ("nco",            {"lut_depth": 1000}),
    ("fft",            {"N": 100}),
    ("fir_decimator",  {"n_taps": 0}),
    ("hilbert",        {"n_taps": 8}),
    ("decimator",      {"method": "invalid"}),
    ("cp_insert",      {"cp_len": 0}),
    ("rs_decoder",     {"k": 222}),
]

class TestMetadataPolicy(unittest.TestCase):
    def setUp(self):
        self.reg = registry.registry()

    def test_constructor_defaults(self):
        for key, spec in self.reg.items():
            for name, p in inspect.signature(_real_init(spec.cls)).parameters.items():
                if name == "self" or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
                    continue
                self.assertFalse(p.default is p.empty and name not in spec.kwargs,
                    f"{key}: parameter '{name}' has no default")

    def test_param_vocabulary(self):
        for key, spec in self.reg.items():
            params = set(inspect.signature(_real_init(spec.cls)).parameters)
            banned = params & BANNED_PARAMS
            self.assertFalse(banned, f"{key}: banned parameter names {sorted(banned)}")

    def test_latency_classified(self):
        for key, spec in self.reg.items():
            dirs = {p.dir if hasattr(p, "dir") else p.direction for p in spec.ports} \
                if spec.ports and hasattr(spec.ports[0], "dir") else None
            sinks   = [p for p in spec.ports if "sink"   in p.name]
            sources = [p for p in spec.ports if "source" in p.name]
            if not (sinks and sources):
                continue  # Sources/sinks have no input->output latency.
            if key in VARIABLE_LATENCY:
                self.assertIsNone(spec.latency, f"{key}: expected variable latency (None)")
            else:
                self.assertIsNotNone(spec.latency,
                    f"{key}: missing self.latency (add it, or allowlist as variable)")

    def test_invalid_params_raise_valueerror(self):
        for key, kwargs in INVALID_PARAMS:
            with self.subTest(block=key, kwargs=kwargs):
                spec = self.reg[key]
                bad  = dict(spec.kwargs)
                bad.update(kwargs)
                with self.assertRaises(ValueError):
                    spec.cls(**bad)

if __name__ == "__main__":
    unittest.main()
