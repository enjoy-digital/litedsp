#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Convert a LiteDSP module to standalone Verilog.

Wraps the block in a top with a ``sys`` clock domain (so ``sys_clk``/``sys_rst`` become ports),
wires the ``@ResetInserter`` reset to ``sys_rst``, and exposes the given port signals as
top-level IOs (named like ``source_payload_i``, ``sink_valid``, ... by Migen's Record flattening).

Used by the Verilator co-simulation (``sim/``), the FPGA implementation flows (``impl/``) and the
flow generator (``litedsp.flow.generate`` / ``litedsp.gen``).
"""

import os

from migen import Module, ClockDomain
from migen.fhdl.verilog import convert

# Helpers ------------------------------------------------------------------------------------------

class _Top(Module):
    def __init__(self, dut):
        self.clock_domains.cd_sys = ClockDomain()
        self.submodules.dut = dut
        if hasattr(dut, "reset"):                         # @ResetInserter reset.
            self.comb += dut.reset.eq(self.cd_sys.rst)

def to_verilog(dut, ios, name, build_dir):
    """Convert ``dut`` to ``build_dir/name.v``; ``ios`` is the set of port signals to expose."""
    top = _Top(dut)
    full = {top.cd_sys.clk, top.cd_sys.rst} | set(ios)
    os.makedirs(build_dir, exist_ok=True)
    path = os.path.join(build_dir, name + ".v")
    convert(top, ios=full, name=name).write(path)
    return path
