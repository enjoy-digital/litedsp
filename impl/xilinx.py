#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Xilinx implementation flow: Vivado out-of-context synthesis (+ optional place & route)."""

import os
import re
import shutil
import subprocess

# Keep each reference part behind a stable implementation/budget key. Resource counts and timing
# floors are part/package/speed-grade specific, so changing a profile must never silently reuse a
# different device's checked-in baseline.
PARTS = {
    "xilinx":    "xc7a200tsbg484-3",
    "xilinx_au": "xcau20p-ffvb676-2-e",
}

# Backward-compatible spelling for callers that imported the original single-part constant.
PART = PARTS["xilinx"]

def have_vivado():
    return shutil.which("vivado") is not None

def _tcl(verilog, top, clock_ns, impl, part=PART):
    lines = [
        f"read_verilog {os.path.basename(verilog)}",
        f"synth_design -mode out_of_context -part {part} -top {top}",
        f"create_clock -name sys_clk -period {clock_ns} [get_ports sys_clk]",
    ]
    if impl:
        lines += [
            "opt_design", "place_design", "route_design",
            "report_timing_summary -file timing_summary.rpt",
            "report_timing -delay_type max -max_paths 10 -file timing_paths.rpt",
        ]
    lines += [
        "report_utilization -file util.rpt",
        'puts "WNS: [get_property SLACK [lindex [get_timing_paths -max_paths 1 -nworst 1 -setup] 0]]"',
        "exit",
    ]
    return "\n".join(lines) + "\n"

def _parse_util(path):
    with open(path) as f:
        text = f.read()
    def row(*labels):
        for lab in labels:
            m = re.search(rf"\|\s*{re.escape(lab)}\*?\s*\|\s*(\d+)\s*\|", text)
            if m:
                return int(m.group(1))
        return 0
    return {
        "lut":  row("Slice LUTs", "CLB LUTs"),
        "ff":   row("Slice Registers", "CLB Registers", "Register as Flip Flop"),
        "dsp":  row("DSPs"),
        "bram": row("Block RAM Tile"),
    }

def synth(verilog, top, build_dir, impl=False, clock_ns=10.0, timeout=1800, part=PART):
    """Run Vivado OOC synth (and impl if ``impl``); return a resource dict (+ pnr fmax if impl)."""
    tcl = os.path.join(build_dir, top + "_vivado.tcl")
    with open(tcl, "w") as f:
        f.write(_tcl(verilog, top, clock_ns, impl, part=part))
    log = os.path.join(build_dir, top + "_vivado.log")
    with open(log, "w") as f:
        subprocess.run(["vivado", "-mode", "batch", "-source", os.path.basename(tcl),
            "-nojournal", "-log", top + "_vivado.log"], cwd=build_dir,
            stdout=f, stderr=subprocess.STDOUT, check=True, timeout=timeout)
    res = _parse_util(os.path.join(build_dir, "util.rpt"))
    if impl:
        with open(log) as f:
            m = re.search(r"WNS:\s*(-?[\d.]+)", f.read())
        if m:
            wns = float(m.group(1))
            res["pnr"] = {"fmax_mhz": 1000.0/(clock_ns - wns)}
    return res
