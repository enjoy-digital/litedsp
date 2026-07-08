#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""DearPyGui flow-graph editor for LiteDSP (GNU-Radio-Companion style).

This package is a thin front-end: it only produces/consumes the tool-agnostic netlist JSON
(:mod:`litedsp.flow.netlist`) and calls the headless code generators (:mod:`litedsp.flow.generate`,
:mod:`litedsp.flow.ipcore`). All graph<->netlist logic lives in :mod:`litedsp.gui.graph` (pure, tested);
:mod:`litedsp.gui.app` is the DearPyGui rendering. Run with ``litedsp_gui``.
"""
