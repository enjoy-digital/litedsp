#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the standalone core generator (litedsp/gen.py)."""

import os
import json
import unittest
import tempfile

from litedsp.gen import parse_config, generate_core

_CONFIG_INLINE = """
name     : dut_core
csr_base : 0x0

flow:
  name       : dut
  data_width : 16
  inputs     : [{id: in0,  layout: iq}]
  outputs    : [{id: out0, layout: iq}]
  blocks:
    - {id: lo,  type: nco,   params: {}}
    - {id: dly, type: delay, params: {depth: 1}}
    - {id: mix, type: mixer, params: {}}
  connections:
    - {from: in0,        to: dly.sink}
    - {from: dly.source, to: mix.sink_a}
    - {from: lo.source,  to: mix.sink_b}
    - {from: mix.source, to: out0}
"""

class TestGen(unittest.TestCase):
    def _write_config(self, tmp, text):
        path = os.path.join(tmp, "config.yml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def test_parse_config_inline_flow(self):
        with tempfile.TemporaryDirectory() as tmp:
            nl, core_config = parse_config(self._write_config(tmp, _CONFIG_INLINE))
            self.assertEqual(nl.name, "dut")
            self.assertEqual(core_config, {"name": "dut_core", "csr_base": 0})

    def test_parse_config_netlist_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow = {
                "name": "ref", "data_width": 16,
                "inputs":  [{"id": "in0",  "layout": "iq"}],
                "outputs": [{"id": "out0", "layout": "iq"}],
                "blocks":  [{"id": "g0", "type": "gain", "params": {}}],
                "connections": [
                    {"from": "in0",       "to": "g0.sink"},
                    {"from": "g0.source", "to": "out0"},
                ],
            }
            with open(os.path.join(tmp, "ref.json"), "w") as f:
                json.dump(flow, f)
            path = self._write_config(tmp, "netlist: ref.json\n")
            nl, core_config = parse_config(path)
            self.assertEqual(nl.name, "ref")
            self.assertEqual(core_config, {})

    def test_parse_config_rejects_flow_and_netlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_config(tmp, "flow: {name: x}\nnetlist: x.json\n")
            with self.assertRaises(ValueError):
                parse_config(path)
            with self.assertRaises(ValueError):
                parse_config(self._write_config(tmp, "name: only_options\n"))

    def test_generate_core_artifacts(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self._write_config(tmp, _CONFIG_INLINE)
            build_dir = os.path.join(tmp, "build")
            path, ip = generate_core(config, output_dir=build_dir)
            self.assertEqual(os.path.basename(path), "dut_core.v")
            v = open(path).read()
            for port in ("s_axil_awvalid", "s_axil_rdata", "in0_payload_i", "out0_payload_q"):
                self.assertIn(port, v)
            for artifact in ("csr.csv", "csr.json", "csr.h"):
                self.assertTrue(os.path.exists(os.path.join(build_dir, artifact)))
            d = json.load(open(os.path.join(build_dir, "csr.json")))
            self.assertIn("lo_phase_inc", d["csr_registers"])

    def test_generate_core_example_config(self):
        example = os.path.join(os.path.dirname(__file__), "..", "examples", "ddc_core.yml")
        with tempfile.TemporaryDirectory() as tmp:
            path, ip = generate_core(example, output_dir=tmp)
            self.assertEqual(os.path.basename(path), "ddc_core.v")
            self.assertEqual(ip.chain.flow_warnings, [])   # delay block aligns the mixer inputs.

if __name__ == "__main__":
    unittest.main()
