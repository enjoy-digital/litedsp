#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the flow (block-graph -> gateware) tooling."""

import unittest

from litedsp.flow import registry


class TestRegistry(unittest.TestCase):
    def test_all_blocks_build(self):
        # Reflecting every block instantiates it with with_csr=True; this is also a regression
        # guard against broken add_csr() (e.g. invalid CSRStorage kwargs).
        r = registry.registry()
        self.assertGreater(len(r), 50)
        for key, spec in r.items():
            self.assertTrue(spec.ports, f"{key} has no stream ports")
            for p in spec.ports:
                self.assertIn(p.direction, ("sink", "source"))
                self.assertIn(p.layout, ("iq", "real", "raw"))

    def test_categories(self):
        cats = registry.by_category()
        for expected in ("generation", "filter", "stream", "analysis"):
            self.assertIn(expected, cats)


if __name__ == "__main__":
    unittest.main()
