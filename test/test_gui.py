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


class TestLoadRoundTrip(unittest.TestCase):
    def test_load_then_save_round_trips(self):
        # DearPyGui items can be created without a viewport, so the load path runs headless.
        import dearpygui.dearpygui as dpg
        from litedsp.gui.app import FlowEditor
        from litedsp.flow import netlist as nlmod

        nl = nlmod.from_dict({
            "name": "ddc", "data_width": 16,
            "inputs":  [{"id": "rx_in",  "layout": "iq"}],
            "outputs": [{"id": "bb_out", "layout": "iq"}],
            "blocks": [
                {"id": "lo",  "type": "nco",         "params": {}},
                {"id": "mix", "type": "mixer",       "params": {}},
                {"id": "lpf", "type": "fir_complex", "params": {"n_taps": 33}},
            ],
            "connections": [
                {"from": "rx_in",      "to": "mix.sink_a"},
                {"from": "lo.source",  "to": "mix.sink_b"},
                {"from": "mix.source", "to": "lpf.sink"},
                {"from": "lpf.source", "to": "bb_out"},
            ],
            "editor": {"positions": {"lo": [10, 20]}},
        })

        dpg.create_context()
        try:
            editor = FlowEditor()
            editor.build()
            editor.load_netlist(nl)
            self.assertEqual(set(editor.nodes), {"rx_in", "bb_out", "lo", "mix", "lpf"})
            self.assertEqual(len(editor.links), 4)
            # Saved position honored, grid fallback applied elsewhere.
            self.assertEqual(dpg.get_item_pos("node_lo"), [10, 20])
            # Round trip: the rebuilt canvas serializes back to the same netlist.
            out = nlmod.to_dict(editor.to_netlist())
            self.assertEqual(out["name"], "ddc")
            self.assertEqual({b["id"]: b["type"] for b in out["blocks"]},
                             {"lo": "nco", "mix": "mixer", "lpf": "fir_complex"})
            self.assertEqual(next(b for b in out["blocks"] if b["id"] == "lpf")["params"],
                             {"n_taps": 33})
            self.assertEqual(sorted((c["from"], c["to"]) for c in out["connections"]),
                             sorted((c.src, c.dst) for c in nl.connections))
            # New ids after a load do not collide with loaded ones.
            editor.add_block("nco")
            self.assertIn("nco1", editor.nodes)
        finally:
            dpg.destroy_context()


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
