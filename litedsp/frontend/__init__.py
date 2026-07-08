#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Boundary adapters: converters (ADC/DAC) on one side, host links (UDP/DMA) on the other.

- :mod:`litedsp.frontend.converter`: raw converter samples <-> Q1.(N-1) I/Q streams
  (format + width alignment at the ADC/DAC boundary).
- :mod:`litedsp.frontend.packet`: I/Q streams <-> framed wide-word streams (the generic glue
  toward UDP payloads, PCIe/host DMA word streams, ...).
- :mod:`litedsp.frontend.udp`: I/Q streams over LiteEth UDP (fixed-size sample packets).
"""
