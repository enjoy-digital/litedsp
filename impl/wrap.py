#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Generate per-module Verilog for the FPGA implementation flows (reuses litedsp/verilog.py)."""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from litedsp.verilog import to_verilog

def gen(name, dut, ios, build_dir):
    """Write ``build_dir/name.v`` (+ memory .init files) for ``dut``. Returns the .v path.

    Migen writes ``<mem>.init`` files into the cwd, so we convert from inside ``build_dir`` to
    keep them next to the Verilog (where yosys/Vivado expect them).
    """
    build_dir = os.path.abspath(build_dir)
    os.makedirs(build_dir, exist_ok=True)
    cwd = os.getcwd()
    os.chdir(build_dir)
    try:
        to_verilog(dut, ios, name, ".")
    finally:
        os.chdir(cwd)
    return os.path.join(build_dir, name + ".v")
