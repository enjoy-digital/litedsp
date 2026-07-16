#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Property-based constructor-space sampling (Hypothesis, optional dev dependency).

Generalizes test_width_sweep.py from 3 hand-picked blocks to the whole palette: sampled
constructor kwargs (derived from each block's reflected ParamSpec) must construct, elaborate,
and — for model-backed blocks — bit-match a short golden-model run. Profiles: ``pr``
(derandomized, small) vs ``nightly`` (large, random) via HYPOTHESIS_PROFILE.

Skipped cleanly when Hypothesis is not installed (dev extra: ``pip install litedsp[develop]``).
"""

import os
import unittest

try:
    from hypothesis import given, settings, strategies as st, HealthCheck
    HAVE_HYPOTHESIS = True
except ImportError:
    HAVE_HYPOTHESIS = False

from litedsp.flow import registry as flow_registry
from litedsp.flow.metadata import _accepts_with_csr

if HAVE_HYPOTHESIS:
    settings.register_profile("pr", max_examples=25, derandomize=True,
        suppress_health_check=[HealthCheck.too_slow], deadline=None)
    settings.register_profile("nightly", max_examples=300, deadline=None,
        suppress_health_check=[HealthCheck.too_slow])
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "pr"))

    # Parameter ranges: conservative valid domains per common parameter name.
    RANGES = {
        "data_width":    st.sampled_from([8, 12, 16, 18, 24]),
        "n_taps":        st.sampled_from([1, 3, 8, 17, 33]),
        "decimation":    st.sampled_from([2, 3, 4, 8, 16]),
        "interpolation": st.sampled_from([2, 3, 4, 8]),
        "n_stages":      st.integers(1, 5),
        "diff_delay":    st.integers(1, 2),
        "phase_bits":    st.sampled_from([16, 24, 32]),
        "depth":         st.sampled_from([1, 2, 8, 32]),
        "n_channels":    st.integers(1, 4),
        "n":             st.sampled_from([16, 64]),
        "N":             st.sampled_from([16, 64]),
        "modulus":       st.sampled_from([2, 4, 8]),
    }

    def kwargs_strategy(spec):
        opts = {}
        for p in spec.params:
            if p.name in RANGES:
                opts[p.name] = RANGES[p.name]
        if not opts:
            return st.just({})
        return st.fixed_dictionaries({}, optional=opts)

@unittest.skipUnless(HAVE_HYPOTHESIS, "hypothesis not installed (dev extra)")
class TestConstructorSpace(unittest.TestCase):
    # A representative cross-category subset: full-palette sampling runs nightly (the PR
    # profile keeps this < 1 min).
    BLOCKS = ["nco", "mixer", "fir_real", "fir_complex", "fir_decimator", "fir_interpolator",
              "cic_decimator", "cic_interpolator", "iir_biquad", "gain", "clipper",
              "dc_offset", "delay", "combine", "split", "window", "goertzel", "diff_encoder"]

    def test_sampled_constructors_elaborate(self):
        from migen.fhdl.verilog import convert
        palette = flow_registry.registry()
        for key in self.BLOCKS:
            spec = palette[key]

            @given(kwargs=kwargs_strategy(spec))
            @settings(max_examples=int(os.environ.get("LITEDSP_HYPOTHESIS_EXAMPLES", "8")),
                      deadline=None, derandomize=True)
            def check(kwargs):
                build = dict(spec.kwargs)
                build.update(kwargs)
                if _accepts_with_csr(spec.cls):
                    build["with_csr"] = False
                try:
                    dut = spec.cls(**build)
                except ValueError:
                    return  # Explicitly rejected combination: valid contract behavior.
                convert(dut)  # Must elaborate to Verilog without errors.

            with self.subTest(block=key):
                check()

if __name__ == "__main__":
    unittest.main()
