#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Implementation smoke test: a couple of blocks synthesize clean for ECP5 (Yosys).

Full coverage + resource budgets live in impl/run.py and the Implementation CI workflow; this
just guards portability/compile-cleanliness in the normal test run. Skipped without Yosys.
"""

import os
import json
import tempfile
import threading
import time
import unittest
from unittest import mock

from impl import budgets, ecp5, xilinx, wrap, modules
from impl import run as impl_run


class TestImplementationBudgets(unittest.TestCase):
    def test_parallel_builds_preserve_order_and_collect_errors(self):
        def builder(name):
            if name == "bad":
                raise RuntimeError("expected")
            return {"name": name}
        results, errors = impl_run.build_many(["first", "bad", "last"], builder, jobs=2)
        self.assertEqual(list(results), ["first", "last"])
        self.assertEqual(results["last"], {"name": "last"})
        self.assertEqual(errors, {"bad": "RuntimeError: expected"})

    def test_parallel_verilog_generation_keeps_each_worker_directory(self):
        observed = {}
        state_lock = threading.Lock()
        active = 0
        peak_active = 0

        def fake_to_verilog(dut, ios, name, build_dir):
            nonlocal active, peak_active
            with state_lock:
                active += 1
                peak_active = max(peak_active, active)
            time.sleep(0.02)
            observed[name] = os.getcwd()
            with state_lock:
                active -= 1

        with tempfile.TemporaryDirectory() as tmp:
            def builder(name):
                path = os.path.join(tmp, name)
                wrap.gen(name, None, set(), path)
                return path
            with mock.patch.object(wrap, "to_verilog", side_effect=fake_to_verilog):
                results, errors = impl_run.build_many(["first", "second"], builder, jobs=2)
            self.assertEqual(errors, {})
            self.assertEqual(set(results), {"first", "second"})
            self.assertEqual(observed, {
                "first": os.path.join(tmp, "first"),
                "second": os.path.join(tmp, "second"),
            })
            self.assertEqual(peak_active, 1)

    def test_xilinx_profiles_use_distinct_reference_parts(self):
        self.assertEqual(xilinx.PARTS["xilinx"], "xc7a200tsbg484-3")
        self.assertEqual(xilinx.PARTS["xilinx_au"], "xcau20p-ffvb676-2-e")
        artix7 = xilinx._tcl("dut.v", "dut", 10.0, False,
            part=xilinx.PARTS["xilinx"])
        artix_au = xilinx._tcl("dut.v", "dut", 10.0, False,
            part=xilinx.PARTS["xilinx_au"])
        self.assertIn("-part xc7a200tsbg484-3", artix7)
        self.assertIn("-part xcau20p-ffvb676-2-e", artix_au)
        self.assertNotEqual(artix7, artix_au)
        routed = xilinx._tcl("dut.v", "dut", 10.0, True,
            part=xilinx.PARTS["xilinx_au"])
        self.assertIn("report_timing_summary -file timing_summary.rpt", routed)
        self.assertIn("-max_paths 10 -file timing_paths.rpt", routed)
        checkpointed = xilinx._tcl("dut.v", "dut", 10.0, False,
            part=xilinx.PARTS["xilinx"], checkpoint="dut_synth.dcp")
        self.assertIn("write_checkpoint -force {dut_synth.dcp}", checkpointed)
        explored = xilinx._pnr_tcl("/tmp/dut_synth.dcp", 10.0, "explore")
        self.assertIn("open_checkpoint {/tmp/dut_synth.dcp}", explored)
        self.assertIn("place_design -directive Explore", explored)
        self.assertIn("route_design -directive Explore", explored)

    def test_complete_ddc_ip_is_an_implementation_sentinel(self):
        self.assertIn("ddc_ip", modules.REGISTRY)
        self.assertIn("ddc_ip", modules.PNR_SUBSET)
        dut, ios, clock_ns = modules.REGISTRY["ddc_ip"]()
        names = {signal.name_override for signal in ios if signal.name_override}
        self.assertEqual(clock_ns, 10.0)
        self.assertIn("s_axil_awvalid", names)
        self.assertIn("rx_in", dut.chain.inputs)
        self.assertIn("bb_out", dut.chain.outputs)
        self.assertIn(dut.chain.inputs["rx_in"].payload.i, ios)
        self.assertIn(dut.chain.outputs["bb_out"].payload.q, ios)

    def test_complete_qpsk_receiver_ip_is_an_implementation_sentinel(self):
        self.assertIn("qpsk_receiver_ip", modules.REGISTRY)
        self.assertIn("qpsk_receiver_ip", modules.PNR_SUBSET)
        dut, ios, clock_ns = modules.REGISTRY["qpsk_receiver_ip"]()
        names = {signal.name_override for signal in ios if signal.name_override}
        self.assertEqual(clock_ns, 10.0)
        self.assertIn("s_axil_awvalid", names)
        self.assertIn("samples_in", dut.chain.inputs)
        self.assertIn("symbols_out", dut.chain.outputs)
        self.assertEqual(dut.chain.carrier.detector, "qpsk")
        self.assertEqual(dut.chain.timing.sps, 2)
        self.assertIn(dut.chain.inputs["samples_in"].payload.i, ios)
        self.assertIn(dut.chain.outputs["symbols_out"].payload.q, ios)
        self.assertIn(dut.chain.outputs["symbols_out"].payload.symbol, ios)

    def test_capacity_cliff_routes_are_isolated_from_the_regular_subset(self):
        self.assertEqual(modules.PNR_STRESS,
            ["fft_parallel_native_x4", "ldpc_decoder_z_parallel"])
        for name in modules.PNR_STRESS:
            self.assertIn(name, modules.REGISTRY)
            self.assertNotIn(name, modules.PNR_SUBSET)
        self.assertIn("fft_parallel_native_x4", modules.TARGET_CLOSED)
        self.assertNotIn("ldpc_decoder_z_parallel", modules.TARGET_CLOSED)

        self.assertIn("fft_parallel_native_x2", modules.PNR_SUBSET)
        self.assertIn("fft_parallel_native_x2", modules.TARGET_CLOSED)

    def test_route_sensitive_closed_targets_use_the_stability_set(self):
        self.assertEqual(modules.PNR_STABILITY, ["dpd", "fft_parallel_native_x4"])
        for name in modules.PNR_STABILITY:
            self.assertIn(name, modules.REGISTRY)
            self.assertNotIn(name, modules.PNR_SUBSET)
            self.assertIn(name, modules.TARGET_CLOSED)

    def test_route_statistics_select_median_run(self):
        runs = [
            (0, {"fmax_mhz": 91.0, "lut": 10}),
            (1, {"fmax_mhz": 105.0, "lut": 12}),
            (2, {"fmax_mhz": 99.0, "lut": 11}),
        ]
        selected, stats = impl_run.aggregate_pnr_runs(runs, [(3, "timeout")])
        self.assertEqual(selected["fmax_mhz"], 99.0)
        self.assertEqual(stats["worst_mhz"], 91.0)
        self.assertEqual(stats["median_mhz"], 99.0)
        self.assertEqual(stats["best_mhz"], 105.0)
        self.assertEqual(stats["completed"], 3)
        self.assertEqual(stats["failed"], 1)

    def test_route_statistics_require_a_completed_run(self):
        with self.assertRaisesRegex(RuntimeError, "no P&R run completed"):
            impl_run.aggregate_pnr_runs([], [(0, "timeout")])

    def test_route_statistics_record_the_even_run_median(self):
        selected, stats = impl_run.aggregate_pnr_runs([
            (0, {"fmax_mhz": 73.8, "lut": 10}),
            (1, {"fmax_mhz": 81.6, "lut": 10}),
        ], [(2, "timeout")])
        self.assertEqual(selected["fmax_mhz"], 77.7)
        self.assertEqual(selected["lut"], 10)
        self.assertEqual(stats["median_mhz"], 77.7)

    def test_route_statistics_label_vivado_strategies(self):
        _, stats = impl_run.aggregate_pnr_runs([
            ("default", {"fmax_mhz": 96.0}),
            ("explore", {"fmax_mhz": 101.0}),
        ], [("timing", "timeout")], run_kind="strategy")
        self.assertEqual(stats["run_kind"], "strategy")
        self.assertEqual(stats["runs"], [
            {"strategy": "default", "fmax_mhz": 96.0},
            {"strategy": "explore", "fmax_mhz": 101.0},
        ])
        self.assertEqual(stats["failures"], [
            {"strategy": "timing", "error": "timeout"},
        ])

    def test_closed_target_gate_leaves_open_objectives_advisory(self):
        misses = {
            "ldpc_decoder_z_parallel": ["open objective"],
            "ddc": [],
        }
        self.assertFalse(impl_run.targets_fail_gate(misses, gate_closed=True))
        misses["ddc"] = ["closed objective"]
        self.assertTrue(impl_run.targets_fail_gate(misses, gate_closed=True))
        self.assertTrue(impl_run.targets_fail_gate(
            {"ldpc_decoder_z_parallel": ["open objective"]}, gate_all=True))

    def test_update_preserves_measured_fmax_and_gate_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with mock.patch.object(budgets, "PATH", path):
                budgets.update("ecp5", {
                    "example": {
                        "lut": 10, "ff": 20, "bram": 1, "dsp": 2,
                        "pnr": {"fmax_mhz": 123.456},
                    },
                }, flow="pnr")
                with open(path) as f:
                    entry = json.load(f)["example"]["ecp5"]
        self.assertEqual(entry["fmax_mhz"], 123.5)
        self.assertEqual(entry["fmax_min"], 104.9)
        self.assertEqual(entry["pnr"]["fmax_mhz"], 123.5)

    def test_update_preserves_explicit_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with open(path, "w") as f:
                json.dump({"example": {"ecp5": {"fmax_target": 150.0}}}, f)
            with mock.patch.object(budgets, "PATH", path):
                budgets.update("ecp5", {"example": {"pnr": {"fmax_mhz": 123.456}}},
                    flow="pnr")
                entry = budgets.load()["example"]["ecp5"]
        self.assertEqual(entry["fmax_target"], 150.0)
        self.assertEqual(entry["fmax_min"], 104.9)

    def test_new_device_inherits_the_reviewed_target_not_the_regression_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with open(path, "w") as f:
                json.dump({"example": {"ecp5": {
                    "fmax_target": 100.0, "fmax_min": 85.0,
                }}}, f)
            with mock.patch.object(budgets, "PATH", path):
                budgets.update("xilinx_au", {"example": {
                    "pnr": {"fmax_mhz": 140.0},
                }}, flow="pnr")
                entry = budgets.load()["example"]["xilinx_au"]
        self.assertEqual(entry["fmax_target"], 100.0)
        self.assertEqual(entry["fmax_min"], 119.0)

    def test_target_check_is_separate_from_regression_floor(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with open(path, "w") as f:
                json.dump({"example": {"ecp5": {
                    "fmax_min": 80.0, "fmax_target": 100.0,
                }}}, f)
            result = {"pnr": {"fmax_mhz": 90.0}}
            with mock.patch.object(budgets, "PATH", path):
                self.assertEqual(budgets.check("ecp5", "example", result, flow="pnr"), [])
                self.assertEqual(budgets.check_target("ecp5", "example", result),
                    ["fmax 90.0 < target 100.0 MHz"])

    def test_synth_and_pnr_resource_baselines_are_independent(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "budgets.json")
            with mock.patch.object(budgets, "PATH", path):
                budgets.update("xilinx", {"fft": {"lut": 295, "ff": 90}}, flow="synth")
                budgets.update("xilinx", {"fft": {
                    "lut": 254, "ff": 90, "pnr": {"fmax_mhz": 104.5},
                }}, flow="pnr")
                entry = budgets.load()["fft"]["xilinx"]
                self.assertEqual(entry["synth"]["lut"], 295)
                self.assertEqual(entry["pnr"]["lut"], 254)
                self.assertEqual(entry["lut"], 254)  # Flat display view prefers P&R.
                self.assertEqual(budgets.check("xilinx", "fft", {"lut": 295},
                    flow="synth"), [])
                self.assertEqual(budgets.check("xilinx", "fft", {"lut": 254},
                    flow="pnr"), [])

    def test_migrate_seeds_timed_and_synthesis_only_entries(self):
        data = {
            "timed": {"ecp5": {"lut": 10, "ff": 2, "fmax_mhz": 100.0,
                "fmax_min": 85.0, "fmax_target": 100.0}},
            "synth": {"ecp5": {"lut": 5, "ff": 1}},
        }
        budgets.migrate(data)
        self.assertEqual(data["timed"]["ecp5"]["synth"]["lut"], 10)
        self.assertEqual(data["timed"]["ecp5"]["pnr"]["fmax_min"], 85.0)
        self.assertNotIn("pnr", data["synth"]["ecp5"])

    def test_closed_targets_are_pnr_sentinels(self):
        data = budgets.load()
        self.assertEqual(modules.TARGET_CLOSED,
            ["dpd", "ddc", "duc", "channelizer", "frame_sync", "resampler_farm", "ldpc_decoder",
             "rs_decoder", "ccsds_rs_decoder",
             "cic_decimator", "cic_interpolator", "agc", "fft_iter",
             "viterbi_decoder", "viterbi_decoder_soft",
             "cic_parallel_x2", "cic_parallel_x4",
             "fft_folded", "fft_interleaved_x2", "fft_parallel_native_x2",
             "fft_parallel_native_x4",
             "goertzel_folded", "iir_biquad_folded",
             "pfb_channelizer_folded", "pfb_channelizer_fft",
             "timing_recovery", "cfr_pipelined", "lms_equalizer_pipelined", "ddc_ip"])
        gated = set(modules.PNR_SUBSET) | set(modules.PNR_STABILITY)
        for name in modules.TARGET_CLOSED:
            self.assertIn(name, gated)
            for device in ("ecp5", "xilinx", "xilinx_au"):
                with self.subTest(name=name, device=device):
                    entry = data[name][device]
                    self.assertIn("fmax_target", entry)
                    self.assertGreaterEqual(entry["pnr"]["fmax_mhz"],
                        entry["fmax_target"])

    def test_compatibility_ffts_have_regression_floors_not_targets(self):
        data = budgets.load()
        for name in ("fft", "fft_parallel_x2", "fft_parallel_x2_folded"):
            for device, entry in data[name].items():
                with self.subTest(name=name, device=device):
                    self.assertNotIn("fmax_target", entry)

@unittest.skipUnless(ecp5.have_yosys(), "yosys not installed")
class TestImplementationECP5(unittest.TestCase):
    def synth(self, name):
        dut, ios, _ = modules.REGISTRY[name]()
        bd = os.path.join("/tmp/litedsp_impl_test", name)
        verilog = wrap.gen(name, dut, ios, bd)
        return ecp5.synth(verilog, name, bd)

    def test_nco_synthesizes(self):
        res = self.synth("nco")
        self.assertGreater(res["lut"], 0)
        self.assertGreater(res["ff"], 0)

    def test_fir_synthesizes(self):
        res = self.synth("fir_complex")
        self.assertGreater(res["lut"], 0)
        self.assertGreater(res["dsp"], 0)      # FIR uses multipliers.

if __name__ == "__main__":
    unittest.main()
