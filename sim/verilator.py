#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Minimal Verilator build/run helpers (real HDL simulation of LiteDSP blocks)."""

import os
import shutil
import subprocess

# Migen's Verilog emitter is deliberately explicit about implicit extension/truncation and
# emits non-blocking assignments in generated combinational/initial blocks. Those constructs
# are already checked by the Python fixed-width tests and create thousands of diagnostics on
# recent Verilator releases. Waive only the two generated size-conversion classes rather than
# the umbrella WIDTH group, so other width diagnostics remain visible. Structural warnings
# (latches, combinational loops, multiple drivers, undriven signals, etc.) also remain enabled.
CODEGEN_WARNING_WAIVERS = [
    "-Wno-DECLFILENAME", "-Wno-UNUSED", "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC",
    "-Wno-INITIALDLY",
    "-Wno-COMBDLY", "-Wno-CASEINCOMPLETE", "-Wno-VARHIDDEN",
]

def have_verilator():
    return shutil.which("verilator") is not None

def build(verilog, tb_cpp, top, build_dir, cflags=None, coverage=False):
    """Build a Verilator sim from a Verilog file + a C++ testbench. Returns the binary path.

    ``coverage`` adds line-coverage instrumentation (``--coverage-line``); the testbench then
    dumps ``coverage.dat`` in its cwd on exit (see ``stream_tb.cpp``, ``run_coverage.py``).
    """
    obj = os.path.join(build_dir, "obj_" + top)
    cmd = [
        "verilator", "--cc", "--exe", "--build", "-j", "0",
        "-Wno-fatal", "-Mdir", obj, "-o", "V" + top, "--top-module", top,
    ] + CODEGEN_WARNING_WAIVERS
    if coverage:
        cmd += ["--coverage-line"]
    if cflags:
        cmd += ["-CFLAGS", cflags]
    cmd += [os.path.abspath(verilog), os.path.abspath(tb_cpp)]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL)
    return os.path.join(obj, "V" + top)

def run(binary, args, cwd=None):
    """Run a built Verilator binary with string-ified args (``cwd``: where $readmem files live)."""
    subprocess.check_call([os.path.abspath(binary)] + [str(a) for a in args], cwd=cwd)

def lint(verilog, top):
    """Lint a Verilog file with Verilator (catches width/latch/comb-loop issues). Returns ok."""
    try:
        # Waived classes are Migen codegen idioms, not design issues: INITIALDLY (reset values
        # as `initial x <= ...`), COMBDLY (non-blocking in comb always), CASEINCOMPLETE (Migen
        # assigns defaults at the top of each comb block, so no latch), VARHIDDEN (namespacing).
        # LATCH/UNOPTFLAT/MULTIDRIVEN/UNDRIVEN & co stay fatal.
        subprocess.check_call(["verilator", "--lint-only", "-Wall", *CODEGEN_WARNING_WAIVERS,
            "--top-module", top, os.path.abspath(verilog)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False
