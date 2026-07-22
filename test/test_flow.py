#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the flow (block-graph -> gateware) tooling."""

import os
import unittest

import numpy as np

from litex.gen import LiteXModule

from litedsp.common           import iq_layout
from litedsp.filter.dc_blocker import LiteDSPDCBlocker
from litedsp.level.gain        import LiteDSPGain
from litedsp.stream.split      import LiteDSPSplit
from litedsp.stream.combine    import LiteDSPCombine
from litedsp.flow              import registry, docgen, netlist as nlmod
from litedsp.flow.builder      import LiteDSPFlowChain
from litedsp.flow.generate     import generate

from test.common import run_stream, column


def _samples(n, seed=0):
    rng = np.random.RandomState(seed)
    xi  = rng.randint(-3000, 3000, n)
    xq  = rng.randint(-3000, 3000, n)
    return [{"i": int(xi[k]), "q": int(xq[k])} for k in range(n)]


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
                self.assertIn(p.layout, ("iq", "iq_symbol", "real", "raw"))

    def test_categories(self):
        cats = registry.by_category()
        for expected in ("generation", "filter", "stream", "analysis"):
            self.assertIn(expected, cats)

    def test_datasheet_lists_all_reference_devices(self):
        spec = registry.registry()["gain"]
        devices = {device: {"lut": 1, "ff": 2, "bram": 0, "dsp": 0}
            for device in ("ecp5", "xilinx", "xilinx_au")}
        page = docgen.block_page(spec, {"gain": devices})
        for device in devices:
            self.assertIn(f"| {device} |", page)


class TestAssemblyMatchesManual(unittest.TestCase):
    """The netlist assembler must produce the same hardware as hand-wiring (bit-exact)."""

    def test_linear_chain(self):
        n = 300
        samples = _samples(n, seed=1)

        nl = nlmod.from_dict({
            "name": "lin", "data_width": 16,
            "inputs": [{"id": "in0", "layout": "iq"}], "outputs": [{"id": "out0", "layout": "iq"}],
            "blocks": [{"id": "dc", "type": "dc_blocker", "params": {}},
                       {"id": "g",  "type": "gain",       "params": {}}],
            "connections": [{"from": "in0", "to": "dc.sink"},
                            {"from": "dc.source", "to": "g.sink"},
                            {"from": "g.source", "to": "out0"}],
        })
        flow = LiteDSPFlowChain(nl, with_csr=False)

        class Manual(LiteXModule):
            def __init__(self):
                self.dc = LiteDSPDCBlocker(data_width=16, with_csr=False)
                self.g  = LiteDSPGain(data_width=16, with_csr=False)
                self.sink, self.source = self.dc.sink, self.g.source
                self.comb += self.dc.source.connect(self.g.sink)

        a = run_stream(flow,   samples, n, ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        b = run_stream(Manual(), samples, n, ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(a, "i", 16), column(b, "i", 16)))
        self.assertTrue(np.array_equal(column(a, "q", 16), column(b, "q", 16)))

    def test_fanout_split_matches_manual(self):
        # Fan out a top-level input to two branches (one to the output, one drained); the assembler
        # must insert a Split. No reconvergence, so no latency-balancing needed.
        from litedsp.stream.csr_io import LiteDSPNullSink
        n = 256
        samples = _samples(n, seed=2)

        nl = nlmod.from_dict({
            "name": "fan", "data_width": 16,
            "inputs": [{"id": "in0", "layout": "iq"}], "outputs": [{"id": "out0", "layout": "iq"}],
            "blocks": [{"id": "g1", "type": "gain",      "params": {}},
                       {"id": "g2", "type": "gain",      "params": {}},
                       {"id": "ns", "type": "null_sink", "params": {}}],
            "connections": [{"from": "in0", "to": "g1.sink"},
                            {"from": "in0", "to": "g2.sink"},
                            {"from": "g1.source", "to": "out0"},
                            {"from": "g2.source", "to": "ns.sink"}],
        })
        flow = LiteDSPFlowChain(nl, with_csr=False)
        self.assertEqual(len(flow.flow_inserted), 1)        # one auto-inserted Split on in0.

        class Manual(LiteXModule):
            def __init__(self):
                self.g1  = LiteDSPGain(data_width=16, with_csr=False)
                self.g2  = LiteDSPGain(data_width=16, with_csr=False)
                self.ns  = LiteDSPNullSink(data_width=16, with_csr=False)
                self.spl = LiteDSPSplit(n=2, data_width=16)
                self.sink, self.source = self.spl.sink, self.g1.source
                self.comb += [
                    self.spl.sources[0].connect(self.g1.sink),
                    self.spl.sources[1].connect(self.g2.sink),
                    self.g2.source.connect(self.ns.sink),
                ]

        a = run_stream(flow,     samples, n, ["i", "q"], ["i", "q"], sink_throttle=0.1, source_ready_rate=0.8)
        b = run_stream(Manual(), samples, n, ["i", "q"], ["i", "q"], sink_throttle=0.1, source_ready_rate=0.8)
        self.assertTrue(np.array_equal(column(a, "i", 16), column(b, "i", 16)))
        self.assertTrue(np.array_equal(column(a, "q", 16), column(b, "q", 16)))


class TestAutoDelay(unittest.TestCase):
    """Unequal-latency joins are auto-balanced with Delay glue (bit-exact vs explicit wiring)."""

    def _mix_netlist(self):
        # NCO (latency 1) into mixer sink_b vs a direct input into sink_a: 1-cycle imbalance.
        return nlmod.from_dict({
            "name": "mixnl", "data_width": 16,
            "inputs": [{"id": "in0", "layout": "iq"}], "outputs": [{"id": "out0", "layout": "iq"}],
            "blocks": [{"id": "lo",  "type": "nco",   "params": {}},
                       {"id": "mix", "type": "mixer", "params": {}}],
            "connections": [{"from": "in0",        "to": "mix.sink_a"},
                            {"from": "lo.source",  "to": "mix.sink_b"},
                            {"from": "mix.source", "to": "out0"}],
        })

    def test_delay_inserted_no_warning(self):
        flow = LiteDSPFlowChain(self._mix_netlist(), with_csr=False)
        self.assertEqual(flow.flow_inserted, ["delay_mix_sink_a"])
        self.assertEqual(flow.flow_warnings, [])

    def test_auto_delay_off_warns(self):
        flow = LiteDSPFlowChain(self._mix_netlist(), with_csr=False, auto_delay=False)
        self.assertEqual(flow.flow_inserted, [])
        self.assertEqual(len(flow.flow_warnings), 1)
        self.assertIn("unequal latency", flow.flow_warnings[0])

    def test_matches_manual_delay(self):
        from litedsp.generation.nco import LiteDSPNCO
        from litedsp.mixing.mixer   import LiteDSPMixer
        from litedsp.stream.delay   import LiteDSPDelay
        n = 256
        samples = _samples(n, seed=3)
        flow = LiteDSPFlowChain(self._mix_netlist(), with_csr=False)

        class Manual(LiteXModule):
            def __init__(self):
                self.lo  = LiteDSPNCO(data_width=16, with_csr=False)
                self.dly = LiteDSPDelay(depth=1, data_width=16)
                self.mix = LiteDSPMixer(data_width=16, with_csr=False)
                self.sink, self.source = self.dly.sink, self.mix.source
                self.comb += [
                    self.dly.source.connect(self.mix.sink_a),
                    self.lo.source.connect(self.mix.sink_b),
                ]

        a = run_stream(flow,     samples, n, ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        b = run_stream(Manual(), samples, n, ["i", "q"], ["i", "q"], sink_throttle=0.2, source_ready_rate=0.7)
        self.assertTrue(np.array_equal(column(a, "i", 16), column(b, "i", 16)))
        self.assertTrue(np.array_equal(column(a, "q", 16), column(b, "q", 16)))


class TestValidationAndGenerate(unittest.TestCase):
    def test_loop_rejected(self):
        nl = nlmod.from_dict({
            "name": "loop", "data_width": 16, "inputs": [], "outputs": [],
            "blocks": [{"id": "a", "type": "gain", "params": {}},
                       {"id": "b", "type": "gain", "params": {}}],
            "connections": [{"from": "a.source", "to": "b.sink"},
                            {"from": "b.source", "to": "a.sink"}],
        })
        with self.assertRaises(nlmod.NetlistError):
            LiteDSPFlowChain(nl, with_csr=False)

    def test_generate_emits_verilog(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ddc  = os.path.join(here, "litedsp", "flow", "examples", "ddc.json")
        path, chain = generate(ddc, "/tmp/litedsp_flow_test/ddc", with_csr=False)
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            v = f.read()
        self.assertIn("rx_in_payload_i", v)         # named top-level AXI-Stream-ready ports.
        self.assertIn("bb_out_payload_q", v)


class TestIPCore(unittest.TestCase):
    def _ddc(self):
        return nlmod.load(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "litedsp", "flow", "examples", "ddc.json"))

    def test_generate_ip_and_register_map(self):
        import json
        from litedsp.flow.ipcore import generate_ip
        path, ip = generate_ip(self._ddc(), "/tmp/litedsp_flow_test/ddc_ip")
        self.assertTrue(os.path.exists(path))
        with open(path) as f:
            v = f.read()
        for port in ("s_axil_awvalid", "s_axil_wdata", "s_axil_rdata", "rx_in_payload_i"):
            self.assertIn(port, v)
        with open(os.path.join(os.path.dirname(path), "csr.json")) as f:
            d = json.load(f)
        addrs = [r["addr"] for r in d["csr_registers"].values()]
        self.assertEqual(len(addrs), len(set(addrs)))            # unique addresses.
        self.assertIn("lo_phase_inc", d["csr_registers"])         # per-block, prefixed.

    def test_axilite_write_reaches_csr(self):
        from migen import run_simulation
        from litedsp.flow.ipcore import LiteDSPFlowIPCore
        ip  = LiteDSPFlowIPCore(self._ddc())
        res = {}
        def tb():
            yield from ip.axil.write(0x800, 0x0abcdef0)          # lo_phase_inc bank base.
            yield
            res["rb"]  = (yield from ip.axil.read(0x800))
            res["nco"] = (yield ip.chain.lo.phase_inc)
        run_simulation(ip, [tb()])
        rb = res["rb"][0] if isinstance(res["rb"], (list, tuple)) else res["rb"]
        self.assertEqual(res["nco"], 0x0abcdef0)
        self.assertEqual(rb, 0x0abcdef0)


class TestVivadoIPPackage(unittest.TestCase):
    def _package(self, config, name):
        import tempfile
        from litedsp.gen import generate_core
        from litedsp.flow.vivado import package_vivado
        root = tempfile.mkdtemp(prefix="litedsp_vivado_")
        path, ip = generate_core(config, os.path.join(root, "core"))
        component = package_vivado(ip, path, os.path.join(root, "ip"), name=name,
            run_vivado=False)
        return root, component

    def test_ddc_package_has_canonical_buses_and_driver_artifacts(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        root, component = self._package(os.path.join(here, "examples", "ddc_core.yml"),
            "ddc_core")
        package = os.path.dirname(component)
        self.assertFalse(os.path.exists(component))  # Script-only mode is portable without Vivado.
        for rel in ("hdl/ddc_core.v", "hdl/ddc_core_vivado.v", "hdl/cos_rom.init",
                    "drivers/csr.csv", "drivers/csr.json", "drivers/csr.h",
                    "drivers/blocks.json", "package_ip.tcl", "validate_ip.tcl",
                    "vivado_ip.json"):
            self.assertTrue(os.path.exists(os.path.join(package, rel)), rel)
        with open(os.path.join(package, "hdl", "ddc_core_vivado.v")) as f:
            wrapper = f.read()
        for port in ("s_axis_rx_in_tdata", "m_axis_bb_out_tdata", "s_axi_awvalid",
                     "aclk", "aresetn"):
            self.assertIn(port, wrapper)
        self.assertIn("assign m_axis_bb_out_tdata = {bb_out_payload_q, bb_out_payload_i};",
            wrapper)
        with open(os.path.join(package, "package_ip.tcl")) as f:
            script = f.read()
        for bus in ("S_AXI", "S_AXIS_RX_IN", "M_AXIS_BB_OUT", "ASSOCIATED_BUSIF"):
            self.assertIn(bus, script)
        self.assertIn("set_property value 100000000 $frequency", script)
        with open(os.path.join(package, "validate_ip.tcl")) as f:
            validation = f.read()
        self.assertIn("create_bd_cell -type ip -vlnv enjoy-digital.fr:litedsp:ddc_core:1.0",
            validation)
        self.assertIn("assign_bd_address", validation)
        self.assertIn("validate_bd_design", validation)
        self.assertIn("launch_runs synth_1", validation)

    def test_symbol_stream_is_byte_padded_and_keeps_first_last(self):
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _, component = self._package(
            os.path.join(here, "examples", "qpsk_receiver_core.yml"), "qpsk_receiver_core")
        wrapper_path = os.path.join(os.path.dirname(component), "hdl",
            "qpsk_receiver_core_vivado.v")
        with open(wrapper_path) as f:
            wrapper = f.read()
        self.assertIn("output wire [39:0] m_axis_symbols_out_tdata", wrapper)
        self.assertIn("assign m_axis_symbols_out_tdata = {6'd0, symbols_out_payload_symbol, "
                      "symbols_out_payload_q, symbols_out_payload_i};", wrapper)
        self.assertIn(".symbols_out_first(m_axis_symbols_out_tuser)", wrapper)
        self.assertIn(".symbols_out_last(m_axis_symbols_out_tlast)", wrapper)


if __name__ == "__main__":
    unittest.main()
