#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the GUI's pure logic (graph<->netlist, param coercion, palette). The DearPyGui
rendering needs a display and is not unit-tested; we only assert gui.app imports headlessly."""

import os
import unittest

from litedsp.flow import netlist as nlmod
from litedsp.flow import registry

from gui import graph, palette
from gui.params import coerce, coerce_params


def _ddc():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return nlmod.load(os.path.join(here, "litedsp", "flow", "examples", "ddc.json"))


class TestGraphRoundtrip(unittest.TestCase):
    def test_netlist_model_netlist(self):
        nl = _ddc()
        nodes, links = graph.netlist_to_model(nl)
        meta = {"name": nl.name, "data_width": nl.data_width, "clock_ns": nl.clock_ns}
        nl2 = graph.model_to_netlist(meta, nodes, links)
        self.assertEqual([b.id for b in nl2.blocks], [b.id for b in nl.blocks])
        self.assertEqual([io.id for io in nl2.inputs],  [io.id for io in nl.inputs])
        self.assertEqual([io.id for io in nl2.outputs], [io.id for io in nl.outputs])
        self.assertEqual({(c.src, c.dst) for c in nl2.connections},
                         {(c.src, c.dst) for c in nl.connections})


class TestParams(unittest.TestCase):
    def test_coerce_types(self):
        fft = registry.get("fft")
        n   = next(p for p in fft.params if p.name == "N")
        inv = next(p for p in fft.params if p.name == "inverse")
        self.assertEqual(coerce(n, "256"), 256)
        self.assertEqual(coerce(n, "0x40"), 64)
        self.assertIs(coerce(inv, "true"), True)
        self.assertIs(coerce(inv, "0"), False)

    def test_coerce_params_drops_defaults(self):
        fft = registry.get("fft")
        out = coerce_params(fft, {"N": "256", "inverse": "false"})
        self.assertEqual(out["N"], 256)
        self.assertNotIn("inverse", out)        # equals default -> dropped.


class TestPalette(unittest.TestCase):
    def test_categories(self):
        cats = palette.categories()
        self.assertIn("filter", cats)
        self.assertTrue(all(isinstance(s.key, str) for specs in cats.values() for s in specs))


class TestImport(unittest.TestCase):
    def test_app_imports_headless(self):
        import gui.app                          # must import without a display.
        self.assertTrue(hasattr(gui.app, "main"))


if __name__ == "__main__":
    unittest.main()
