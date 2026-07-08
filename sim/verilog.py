#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Compatibility shim: the Verilog emission helper now lives in :mod:`litedsp.verilog`."""

from litedsp.verilog import _Top, to_verilog  # noqa: F401
