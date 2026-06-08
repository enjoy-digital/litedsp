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
    license          = "BSD-2-Clause",
    python_requires  = ">=3.7",
    packages         = find_packages(exclude=("test*", "examples*")),
    install_requires = ["migen", "litex"],
    include_package_data = True,
)
