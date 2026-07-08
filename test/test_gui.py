#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the GUI's pure logic (graph<->netlist, param coercion, palette). The DearPyGui
rendering needs a display and is not unit-tested; we only assert litedsp.gui.app imports headlessly."""

import os
import unittest

from litedsp.flow import netlist as nlmod
from litedsp.flow import registry

from litedsp.gui import graph, palette
from litedsp.gui.params import coerce, coerce_params


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
        import litedsp.gui.app                          # must import without a display.
        self.assertTrue(hasattr(litedsp.gui.app, "main"))


class TestLiveSession(unittest.TestCase):
    def test_discovery_and_tune(self):
        from litedsp.gui.live import LiveSession
        from test.test_software import MockBus, MockCSR

        bus = MockBus({"lo_phase_inc": MockCSR(),
                       "capture_threshold": MockCSR(), "capture_force": MockCSR(),
                       "capture_status": MockCSR(),
                       "reader_data": MockCSR(), "reader_valid": MockCSR(1),
                       "reader_pop": MockCSR()})
        bus.constants = type("C", (), {"config_clock_frequency": 100e6})()

        live = LiveSession(bus=bus)
        blocks = live.open()
        self.assertEqual(set(blocks), {"lo", "capture", "reader"})
        self.assertEqual(set(live.ncos), {"lo"})

        live.tune("lo", 25e6)
        self.assertEqual(bus.regs.lo_phase_inc.writes, [1 << 30])   # fs/4.

        freq, psd = live.capture_psd("capture", "reader", n=16)
        self.assertEqual(bus.regs.capture_force.writes, [0, 1, 0])
        self.assertEqual(len(freq), 16)
        self.assertEqual(len(psd), 16)


if __name__ == "__main__":
    unittest.main()
