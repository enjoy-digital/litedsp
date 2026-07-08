#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Host-side control of LiteDSP blocks over litex_server (UART/Ethernet/PCIe bridges).

:mod:`litedsp.software.drivers` maps each block's CSR register set to a small Python driver
(tune an NCO in Hz, reload FIR taps, drain a Capture buffer to NumPy, run a DMA window...), and
can auto-discover the blocks present in a SoC from its register map. The ``litedsp_cli`` entry
point exposes the common operations from the shell.
"""
