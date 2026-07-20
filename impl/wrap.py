#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Generate per-module Verilog for the FPGA implementation flows (reuses litedsp/verilog.py)."""

import os
import sys
import threading

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from litedsp.verilog import to_verilog

# ``os.chdir`` is process-wide. Keep only the Migen conversion section serialized when
# ``impl/run.py --jobs`` builds independent modules in worker threads; synthesis and P&R still
# run concurrently after each worker has returned to its original directory.
_CONVERT_LOCK = threading.Lock()

def gen(name, dut, ios, build_dir):
    """Write ``build_dir/name.v`` (+ memory .init files) for ``dut``. Returns the .v path.

    Migen writes ``<mem>.init`` files into the cwd, so we convert from inside ``build_dir`` to
    keep them next to the Verilog (where yosys/Vivado expect them).
    """
    build_dir = os.path.abspath(build_dir)
    os.makedirs(build_dir, exist_ok=True)
    with _CONVERT_LOCK:
        cwd = os.getcwd()
        os.chdir(build_dir)
        try:
            to_verilog(dut, ios, name, ".")
        finally:
            os.chdir(cwd)
    return os.path.join(build_dir, name + ".v")
