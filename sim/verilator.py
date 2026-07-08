#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Minimal Verilator build/run helpers (real HDL simulation of LiteDSP blocks)."""

import os
import shutil
import subprocess

def have_verilator():
    return shutil.which("verilator") is not None

def build(verilog, tb_cpp, top, build_dir, cflags=None):
    """Build a Verilator sim from a Verilog file + a C++ testbench. Returns the binary path."""
    obj = os.path.join(build_dir, "obj_" + top)
    cmd = [
        "verilator", "--cc", "--exe", "--build", "-j", "0",
        "-Wno-fatal", "-Mdir", obj, "-o", "V" + top, "--top-module", top,
    ]
    if cflags:
        cmd += ["-CFLAGS", cflags]
    cmd += [os.path.abspath(verilog), os.path.abspath(tb_cpp)]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
    return os.path.join(obj, "V" + top)

def run(binary, args):
    """Run a built Verilator binary with string-ified args."""
    subprocess.check_call([binary] + [str(a) for a in args])

def lint(verilog, top):
    """Lint a Verilog file with Verilator (catches width/latch/comb-loop issues). Returns ok."""
    try:
        # Waived classes are Migen codegen idioms, not design issues: INITIALDLY (reset values
        # as `initial x <= ...`), COMBDLY (non-blocking in comb always), CASEINCOMPLETE (Migen
        # assigns defaults at the top of each comb block, so no latch), VARHIDDEN (namespacing).
        # LATCH/UNOPTFLAT/MULTIDRIVEN/UNDRIVEN & co stay fatal.
        subprocess.check_call(["verilator", "--lint-only", "-Wall", "-Wno-DECLFILENAME",
            "-Wno-UNUSED", "-Wno-WIDTH", "-Wno-INITIALDLY", "-Wno-COMBDLY",
            "-Wno-CASEINCOMPLETE", "-Wno-VARHIDDEN",
            "--top-module", top, os.path.abspath(verilog)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False
