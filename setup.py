#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from setuptools import setup, find_packages

setup(
    name             = "litedsp",
    version          = "0.1.0",
    description      = "Portable RF DSP building blocks for LiteX.",
    long_description = open("README.md", encoding="utf-8").read(),
    long_description_content_type = "text/markdown",
    author           = "Florent Kermarrec",
    author_email     = "florent@enjoy-digital.fr",
    url              = "https://github.com/enjoy-digital/litedsp",
    license          = "BSD-2-Clause",
    python_requires  = ">=3.7",
    packages         = find_packages(include=("litedsp", "litedsp.*")),
    install_requires = ["migen", "litex", "pyyaml"],
    extras_require   = {
        "design": ["numpy"],      # Filter coefficient design (litedsp/filter/design.py).
        "gui":    ["dearpygui"],  # Flow-graph editor (litedsp/gui).
    },
    include_package_data = True,
    package_data     = {"litedsp.flow": ["examples/*.json"]},
    entry_points = {
        "console_scripts": [
            "litedsp_gen  = litedsp.gen:main",
            "litedsp_flow = litedsp.flow.generate:main",
            "litedsp_gui  = litedsp.gui.app:main",
        ],
    },
)
