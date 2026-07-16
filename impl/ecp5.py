#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""ECP5 implementation flow: Yosys out-of-context synthesis + (subset) nextpnr-ecp5 P&R."""

import os
import re
import shutil
import subprocess

DEVICE  = "LFE5UM5G-85F"
NEXTPNR = "--um5g-85k"
PACKAGE = "CABGA381"

def have_yosys():   return shutil.which("yosys") is not None
def have_nextpnr(): return shutil.which("nextpnr-ecp5") is not None

# Synthesis (out of context) -----------------------------------------------------------------------

def _parse_stat(text):
    """Parse the cell counts from the last yosys ``stat`` table."""
    chunks = text.split("Number of cells:")
    cells  = {}
    if len(chunks) > 1:
        for line in chunks[-1].splitlines()[1:]:
            m = re.match(r"\s+(\S+)\s+(\d+)\s*$", line)
            if m:
                cells[m.group(1)] = int(m.group(2))
            elif line.strip() == "" and cells:
                break
    return {
        "lut":   cells.get("LUT4", 0) + 2*cells.get("CCU2C", 0),   # carry uses 2 LUT4 slots.
        "lut4":  cells.get("LUT4", 0),
        "carry": cells.get("CCU2C", 0),
        "ff":    cells.get("TRELLIS_FF", 0),
        "bram":  cells.get("DP16KD", 0),
        "dsp":   cells.get("MULT18X18D", 0),
    }

def synth(verilog, top, build_dir, json_out=None):
    """Run ``synth_ecp5`` on ``verilog``; return a resource dict. Optionally emit JSON for P&R."""
    log = os.path.join(build_dir, top + "_ecp5_synth.log")
    json_cmd = f"write_json {os.path.basename(json_out)}; " if json_out else ""
    script = (f"read_verilog {os.path.basename(verilog)}; "
              f"synth_ecp5 -top {top}; {json_cmd}stat")
    with open(log, "w") as f:
        subprocess.run(["yosys", "-p", script], cwd=build_dir,
            stdout=f, stderr=subprocess.STDOUT, check=True)
    with open(log) as f:
        return _parse_stat(f.read())

# Place & route (subset) ---------------------------------------------------------------------------

class PNRTimeout(RuntimeError):
    pass

def pnr(json_in, top, build_dir, clock_ns, seed=None, timeout=1800):
    """Run nextpnr-ecp5 on a synthesized JSON; return {fmax_mhz, util cells}."""
    suffix = "" if seed is None else f"_seed{seed}"
    log = os.path.join(build_dir, top + f"_ecp5_pnr{suffix}.log")
    cfg = os.path.join(build_dir, top + suffix + ".cfg")
    freq = 1000.0/clock_ns
    cmd = ["nextpnr-ecp5", NEXTPNR, "--package", PACKAGE,
           "--json", os.path.basename(json_in), "--textcfg", os.path.basename(cfg),
           "--freq", f"{freq:.1f}"]
    if seed is not None:
        cmd += ["--seed", str(seed)]
    # nextpnr exits nonzero when it misses the target frequency, but still routes and reports the
    # achieved fmax -- which is exactly what we want -- so don't treat a timing miss as fatal.
    with open(log, "w") as f:
        try:
            subprocess.run(cmd, cwd=build_dir, stdout=f, stderr=subprocess.STDOUT, check=False,
                timeout=timeout)
        except subprocess.TimeoutExpired as e:
            raise PNRTimeout(
                f"nextpnr-ecp5 timed out after {timeout}s (seed={seed}, log={log})") from e
    with open(log) as f:
        text = f.read()
    fmax = None
    for m in re.finditer(r"Max frequency for clock\s+'[^']*':\s+([\d.]+)\s*MHz", text):
        fmax = float(m.group(1))                                   # Last reported (post-route).
    if fmax is None:
        # Pass-through-ish blocks have no interior register-to-register paths at their default
        # parameters -- routed fine, just nothing to time.
        if "no interior timing paths found" not in text:
            raise RuntimeError(f"nextpnr-ecp5 failed (no fmax) - see {log}")
    util = {}
    for cell, key in [("TRELLIS_COMB", "lut"), ("TRELLIS_FF", "ff"),
                      ("DP16KD", "bram"), ("MULT18X18D", "dsp")]:
        m = re.search(rf"{cell}:\s+(\d+)/", text)
        if m:
            util[key] = int(m.group(1))
    util["fmax_mhz"] = fmax
    return util
