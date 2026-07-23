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

import numpy as np

from migen import Signal, passive, run_simulation

from litedsp.gen import parse_config, generate_core
from litedsp.flow.ipcore import LiteDSPFlowIPCore

from test.common import column, stream_capture, stream_driver

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
            with open(path) as f:
                v = f.read()
            for port in ("s_axil_awvalid", "s_axil_rdata", "in0_payload_i", "out0_payload_q"):
                self.assertIn(port, v)
            for artifact in ("csr.csv", "csr.json", "csr.h"):
                self.assertTrue(os.path.exists(os.path.join(build_dir, artifact)))
            with open(os.path.join(build_dir, "csr.json")) as f:
                d = json.load(f)
            self.assertIn("lo_phase_inc", d["csr_registers"])

    def test_generate_core_example_config(self):
        example = os.path.join(os.path.dirname(__file__), "..", "examples", "ddc_core.yml")
        with tempfile.TemporaryDirectory() as tmp:
            path, ip = generate_core(example, output_dir=tmp)
            self.assertEqual(os.path.basename(path), "ddc_core.v")
            self.assertEqual(ip.chain.flow_warnings, [])   # delay block aligns the mixer inputs.

    def test_generate_qpsk_receiver_example_config(self):
        example = os.path.join(os.path.dirname(__file__), "..", "examples",
            "qpsk_receiver_core.yml")
        with tempfile.TemporaryDirectory() as tmp:
            path, ip = generate_core(example, output_dir=tmp)
            self.assertEqual(os.path.basename(path), "qpsk_receiver_core.v")
            self.assertEqual([b.type for b in ip.netlist.blocks],
                ["carrier_loop", "timing_recovery", "slicer"])
            with open(path) as f:
                self.assertIn("symbols_out_payload_symbol", f.read())
            with open(os.path.join(tmp, "csr.json")) as f:
                registers = json.load(f)["csr_registers"]
            self.assertIn("carrier_frequency", registers)
            self.assertIn("timing_omega", registers)


class TestGeneratedIPTransactions(unittest.TestCase):
    """Exercise the emitted examples through their AXI-Lite and AXI-Stream interfaces."""

    def _example(self, name):
        return os.path.join(os.path.dirname(__file__), "..", "examples", name)

    def _generated_ip(self, name, build_dir):
        config = self._example(name)
        generate_core(config, output_dir=build_dir)
        # Verilog conversion consumes a Migen fragment, so elaborate the same parsed
        # configuration a second time for the behavioral transaction simulation.
        netlist, core_config = parse_config(config)
        core_config.pop("name", None)
        return LiteDSPFlowIPCore(netlist, **core_config)

    def _run_stream(self, ip, samples, n_out, sink_fields, source_fields, controller):
        configured = Signal()
        captured   = []

        @passive
        def configure():
            yield from controller(ip)
            yield configured.eq(1)

        @passive
        def drive_after_config():
            while not (yield configured):
                yield
            yield from stream_driver(ip.chain.sink, samples, sink_fields,
                seed=401, throttle=0.25)

        run_simulation(ip, [
            configure(),
            drive_after_config(),
            stream_capture(ip.chain.source, captured, n_out, source_fields,
                seed=409, ready_rate=0.65),
        ])
        return captured

    def test_ddc_axi_configuration_and_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            ip = self._generated_ip("ddc_core.yml", tmp)
            registers = json.loads(ip.export_json())["csr_registers"]

            def controller(dut):
                writes = {
                    "deci_factor": 2,
                    "lo_phase_inc": 0x13579bdf,
                    "lpf_bypass": 1,
                    "mix_control": 1 << 8,  # Bypass the mixer with its delayed signal input.
                }
                for name, value in writes.items():
                    address = registers[name]["addr"]
                    self.assertEqual((yield from dut.axil.write(address, value)), 0)
                    readback, response = (yield from dut.axil.read(address))
                    self.assertEqual(response, 0)
                    self.assertEqual(readback, value)

            rng = np.random.RandomState(397)
            samples = [{"i": int(i), "q": int(q)}
                for i, q in zip(rng.randint(-20000, 20001, 128),
                                rng.randint(-20000, 20001, 128))]
            captured = self._run_stream(ip, samples, len(samples)//2, ["i", "q"], ["i", "q"],
                controller)
            np.testing.assert_array_equal(column(captured, "i", 16),
                [sample["i"] for sample in samples[::2]])
            np.testing.assert_array_equal(column(captured, "q", 16),
                [sample["q"] for sample in samples[::2]])

    def test_qpsk_axi_status_and_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            ip = self._generated_ip("qpsk_receiver_core.yml", tmp)
            registers = json.loads(ip.export_json())["csr_registers"]

            def controller(dut):
                frequency, response = (yield from dut.axil.read(
                    registers["carrier_frequency"]["addr"]))
                self.assertEqual(response, 0)
                self.assertEqual(frequency, 0)
                omega, response = (yield from dut.axil.read(registers["timing_omega"]["addr"]))
                self.assertEqual(response, 0)
                self.assertEqual(omega, 2 << 16)

            # A stationary ideal QPSK point has zero carrier/timing error. It therefore gives
            # an exact end-to-end check while the randomized valid/ready pattern stresses both
            # generated stream interfaces and the feedback loops' accepted-sample scheduling.
            samples = [{"i": 8192, "q": 8192} for _ in range(180)]
            captured = self._run_stream(ip, samples, 64, ["i", "q"],
                ["i", "q", "symbol"], controller)
            self.assertEqual(set(column(captured, "i", 16)), {8192})
            self.assertEqual(set(column(captured, "q", 16)), {8192})
            self.assertEqual(set(column(captured, "symbol")), {3})


if __name__ == "__main__":
    unittest.main()
