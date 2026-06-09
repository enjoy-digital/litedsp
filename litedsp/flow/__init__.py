#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteDSP flow: assemble block graphs into processing chains and generate gateware.

This package turns a tool-agnostic JSON *netlist* of LiteDSP blocks into a connected LiteX
module, then into Verilog (and, in Phase 2, an AXI-Stream/AXI-Lite IP core with a CSR register
map). It is GUI-independent: the DearPyGui editor only produces/consumes the netlist.
"""
