#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Completeness meta-test over the verification registry (test/registry.py).

Turns "we forgot to verify block X" into a CI failure: every palette block needs a VSPEC
row, every VSPEC row must reference a real palette block and a real golden model, and the
latency classification must match the block's declared contract.
"""

import unittest

from litedsp.flow import registry as flow_registry

from test import models
from test.registry import VSPEC

class TestRegistryMeta(unittest.TestCase):
    def setUp(self):
        self.palette = flow_registry.registry()

    def test_every_block_classified(self):
        missing = sorted(set(self.palette) - set(VSPEC))
        self.assertFalse(missing, f"palette blocks without a VSPEC row: {missing}")

    def test_no_stale_vspec_rows(self):
        # New-block keys may be pre-registered in VSPEC before the block lands; they must be
        # explicitly marked by a leading key comment instead of silently ignored. Keep strict.
        stale = sorted(k for k in VSPEC if k not in self.palette and k not in PLANNED)
        self.assertFalse(stale, f"VSPEC rows without a palette block: {stale}")

    def test_models_bound(self):
        for key, v in VSPEC.items():
            if v["model"] is not None:
                self.assertTrue(hasattr(models, v["model"]),
                    f"{key}: VSPEC model '{v['model']}' not found in test/models.py")

    def test_latency_classification_matches(self):
        for key, spec in self.palette.items():
            v = VSPEC.get(key)
            if v is None:
                continue
            sinks   = [p for p in spec.ports if p.direction == "sink"]
            sources = [p for p in spec.ports if p.direction == "source"]
            if v["latency"] == "n/a":
                continue
            self.assertTrue(sinks and sources,
                f"{key}: latency '{v['latency']}' but block is source/sink-only")
            if v["latency"] == "check":
                self.assertIsNotNone(spec.latency,
                    f"{key}: VSPEC says fixed latency but self.latency is None")
            elif v["latency"] == "variable":
                self.assertIsNone(spec.latency,
                    f"{key}: VSPEC says variable latency but self.latency = {spec.latency}")

    def test_cosim_eligibility(self):
        for key, v in VSPEC.items():
            if v["cosim"]:
                self.assertIsNotNone(v["model"], f"{key}: cosim=True requires a golden model")

# Keys reserved for blocks planned in the roadmap but not landed yet.
PLANNED = set()

if __name__ == "__main__":
    unittest.main()
