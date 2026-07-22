#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Tests for the flow (block-graph -> gateware) tooling."""

import os
import unittest

import numpy as np

from migen import Signal

from litex.gen import LiteXModule
from litex.soc.interconnect import stream

from litedsp.common           import iq_layout, real_layout
from litedsp.filter.dc_blocker import LiteDSPDCBlocker
from litedsp.level.gain        import LiteDSPGain
from litedsp.stream.split      import LiteDSPSplit
from litedsp.stream.combine    import LiteDSPCombine
from litedsp.flow              import registry, metadata, docgen, netlist as nlmod
from litedsp.flow.builder      import LiteDSPFlowChain
from litedsp.flow.generate     import generate

from test.common import run_stream, column


def _samples(n, seed=0):
    rng = np.random.RandomState(seed)
    xi  = rng.randint(-3000, 3000, n)
    xq  = rng.randint(-3000, 3000, n)
    return [{"i": int(xi[k]), "q": int(xq[k])} for k in range(n)]


class _SelectableRealDelay(LiteXModule):
    """Test-only non-I/Q block whose selected depth differs from its reflected default."""
    def __init__(self, data_width=9, depth=1):
        from litedsp.flow.glue import _FlowDelay
        self.latency = depth
        description = stream.EndpointDescription(real_layout(data_width))
        self.delay = _FlowDelay(description, depth)
        self.sink, self.source = self.delay.sink, self.delay.source


class _RealJoin(LiteXModule):
    """Test-only synchronous real-stream join used to exercise generic auto-alignment."""
    def __init__(self, data_width=9):
        self.latency = 0
        self.sink_a = stream.Endpoint(real_layout(data_width))
        self.sink_b = stream.Endpoint(real_layout(data_width))
        self.source = stream.Endpoint(real_layout(data_width))
        consume = Signal()
        self.comb += [
            self.source.valid.eq(self.sink_a.valid & self.sink_b.valid),
            consume.eq(self.source.valid & self.source.ready),
            self.sink_a.ready.eq(consume),
            self.sink_b.ready.eq(consume),
            self.source.data.eq(self.sink_a.data + self.sink_b.data),
            self.source.first.eq(self.sink_a.first),
            self.source.last.eq(self.sink_a.last),
        ]


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


class TestGenericFlowGlue(unittest.TestCase):
    def _real_registry(self):
        reg = dict(registry.registry())
        reg["test_real_delay"] = metadata.reflect(
            "test_real_delay", _SelectableRealDelay, {"data_width": 9, "depth": 1})
        reg["test_real_join"] = metadata.reflect(
            "test_real_join", _RealJoin, {"data_width": 9})
        return reg

    def test_real_fanout_and_selected_latency_alignment_preserve_frames(self):
        reg = self._real_registry()
        nl = nlmod.from_dict({
            "name": "real_reconverge", "data_width": 16,
            "inputs": [{"id": "samples", "layout": "real"}],
            "outputs": [{"id": "summed", "layout": "real"}],
            "blocks": [
                {"id": "branch", "type": "test_real_delay",
                 "params": {"data_width": 9, "depth": 2}},
                {"id": "join", "type": "test_real_join", "params": {"data_width": 9}},
            ],
            "connections": [
                {"from": "samples", "to": "branch.sink"},
                {"from": "samples", "to": "join.sink_b"},
                {"from": "branch.source", "to": "join.sink_a"},
                {"from": "join.source", "to": "summed"},
            ],
        })
        dut = LiteDSPFlowChain(nl, reg=reg, with_csr=False)
        self.assertEqual(dut.flow_inserted, ["split_samples", "delay_join_sink_b"])
        self.assertEqual(dut.flow_warnings, [])
        self.assertEqual(dut.delay_join_sink_b.depth, 2)  # Instance depth, not registry default 1.
        self.assertEqual(len(dut.sink.data), 9)            # Inferred concrete width, not global 16.

        n = 180
        rng = np.random.RandomState(51)
        data = rng.randint(-100, 101, n)
        samples = [{"data": int(value), "first": int(k % 15 == 0),
                    "last": int(k % 15 == 14)} for k, value in enumerate(data)]
        cap = run_stream(dut, samples, n, ["data", "first", "last"],
            ["data", "first", "last"], sink_throttle=0.25, source_ready_rate=0.6,
            sink_seed=53, source_seed=59)
        np.testing.assert_array_equal(column(cap, "data", 9), 2*data)
        self.assertEqual([sample["first"] for sample in cap],
            [sample["first"] for sample in samples])
        self.assertEqual([sample["last"] for sample in cap],
            [sample["last"] for sample in samples])

        warn_only = LiteDSPFlowChain(nl, reg=reg, with_csr=False, auto_delay=False)
        self.assertEqual(warn_only.flow_inserted, ["split_samples"])
        self.assertIn("'sink_a': 2", warn_only.flow_warnings[0])
        self.assertIn("'sink_b': 0", warn_only.flow_warnings[0])

    def test_same_category_with_different_concrete_widths_is_rejected(self):
        nl = nlmod.from_dict({
            "name": "width_mismatch", "data_width": 16,
            "inputs": [{"id": "samples", "layout": "real"}], "outputs": [],
            "blocks": [
                {"id": "nine", "type": "test_real_delay",
                 "params": {"data_width": 9, "depth": 1}},
                {"id": "ten", "type": "test_real_delay",
                 "params": {"data_width": 10, "depth": 1}},
            ],
            "connections": [
                {"from": "samples", "to": "nine.sink"},
                {"from": "samples", "to": "ten.sink"},
            ],
        })
        with self.assertRaisesRegex(nlmod.NetlistError, "incompatible concrete destinations"):
            LiteDSPFlowChain(nl, reg=self._real_registry(), with_csr=False)

        internal = nlmod.from_dict({
            "name": "internal_width_mismatch", "data_width": 16,
            "inputs": [], "outputs": [],
            "blocks": [
                {"id": "nine", "type": "test_real_delay",
                 "params": {"data_width": 9, "depth": 1}},
                {"id": "ten", "type": "test_real_delay",
                 "params": {"data_width": 10, "depth": 1}},
            ],
            "connections": [{"from": "nine.source", "to": "ten.sink"}],
        })
        with self.assertRaisesRegex(nlmod.NetlistError, "concrete layout mismatch"):
            LiteDSPFlowChain(internal, reg=self._real_registry(), with_csr=False)

    def test_timestamp_params_survive_fanout_to_top_level(self):
        nl = nlmod.from_dict({
            "name": "tagged_fanout", "data_width": 16,
            "inputs": [{"id": "samples", "layout": "iq"}],
            "outputs": [{"id": "tagged", "layout": "iq"}],
            "blocks": [
                {"id": "tag", "type": "timestamper", "params": {"stream_id": 23}},
                {"id": "strip", "type": "time_untagger", "params": {}},
                {"id": "drain", "type": "null_sink", "params": {}},
            ],
            "connections": [
                {"from": "samples", "to": "tag.sink"},
                {"from": "tag.source", "to": "tagged"},
                {"from": "tag.source", "to": "strip.sink"},
                {"from": "strip.source", "to": "drain.sink"},
            ],
        })
        dut = LiteDSPFlowChain(nl, with_csr=False)
        self.assertEqual(dut.flow_inserted, ["split_tag_source"])
        self.assertEqual([field[0] for field in dut.source.description.param_layout],
            ["timestamp", "stream_id"])
        n = 96
        samples = _samples(n, seed=61)
        for k, sample in enumerate(samples):
            sample.update(first=int(k % 12 == 0), last=int(k % 12 == 11))
        cap = run_stream(dut, samples, n, ["i", "q", "first", "last"],
            ["i", "q", "timestamp", "stream_id", "first", "last"],
            sink_throttle=0.2, source_ready_rate=0.65, sink_seed=67, source_seed=71)
        np.testing.assert_array_equal(column(cap, "i", 16), [sample["i"] for sample in samples])
        np.testing.assert_array_equal(column(cap, "q", 16), [sample["q"] for sample in samples])
        self.assertEqual([sample["timestamp"] for sample in cap], [0]*n)
        self.assertEqual([sample["stream_id"] for sample in cap], [23]*n)
        self.assertEqual([sample["first"] for sample in cap],
            [sample["first"] for sample in samples])
        self.assertEqual([sample["last"] for sample in cap],
            [sample["last"] for sample in samples])


class TestValidationAndGenerate(unittest.TestCase):
    def test_unknown_top_level_layout_rejected(self):
        nl = nlmod.from_dict({
            "name": "bad_layout", "inputs": [{"id": "in0", "layout": "bytes"}],
            "outputs": [], "blocks": [], "connections": [],
        })
        with self.assertRaisesRegex(nlmod.NetlistError, "unknown layout"):
            LiteDSPFlowChain(nl, with_csr=False)

    def test_unconnected_raw_top_level_requires_inference(self):
        nl = nlmod.from_dict({
            "name": "raw_without_shape", "inputs": [{"id": "in0", "layout": "raw"}],
            "outputs": [], "blocks": [], "connections": [],
        })
        with self.assertRaisesRegex(nlmod.NetlistError, "concrete endpoint schema"):
            LiteDSPFlowChain(nl, with_csr=False)

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
