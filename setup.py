#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

from setuptools import setup, find_packages

setup(
    name                          = "litedsp",
    version = "2026.07",
    description                   = "Portable RF/DSP building blocks for LiteX",
    long_description              = open("README.md", encoding="utf-8").read(),
    long_description_content_type = "text/markdown",
    author                        = "Florent Kermarrec",
    author_email                  = "florent@enjoy-digital.fr",
    url                           = "http://enjoy-digital.fr",
    download_url                  = "https://github.com/enjoy-digital/litedsp",
    test_suite                    = "test",
    license                       = "BSD",
    python_requires               = "~=3.7",
    install_requires              = ["migen", "litex", "pyyaml"],
    extras_require                = {
        "develop": ["setuptools"],
        "design":  ["numpy"],      # Filter coefficient design (litedsp/filter/design.py).
        "gui":     ["dearpygui"],  # Flow-graph editor (litedsp/gui).
    },
    packages                      = find_packages(exclude=("test*", "sim*", "impl*", "bench*", "doc*", "examples*")),
    include_package_data          = True,
    package_data                  = {"litedsp.flow": ["examples/*.json"]},
    keywords                      = "HDL ASIC FPGA hardware design",
    classifiers                   = [
        "Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)",
        "Environment :: Console",
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
    ],
    entry_points = {
        "console_scripts": [
            "litedsp_gen  = litedsp.gen:main",
            "litedsp_flow = litedsp.flow.generate:main",
            "litedsp_gui  = litedsp.gui.app:main",
            "litedsp_cli  = litedsp.software.cli:main",
        ],
    },
)
