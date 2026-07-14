#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""
LiteDSP standalone core generator.

LiteDSP aims to be directly used as a python package when the SoC is created using LiteX. However,
for some use cases it could be interesting to generate a standalone verilog file of the core:
- integration of a DSP chain in a SoC using a more traditional flow.
- need to version/package the core.
- avoid Migen/LiteX dependencies.
- etc...

The standalone core is generated from a YAML configuration file that describes the DSP flow
(inline, or as a reference to a flow netlist JSON) and the core options. It produces the core
Verilog — AXI-Stream data ports + AXI-Lite control port — and the register map artifacts
(``csr.csv`` / ``csr.json`` / ``csr.h``) needed to drive the core from software.

Config example (see ``examples/ddc_core.yml``)::

    # Core -------------------------------------------------------------------
    name     : ddc_core
    csr_base : 0x0

    # Flow -------------------------------------------------------------------
    netlist  : ddc.json     # ...or an inline "flow:" section (same schema).

Usage::

    litedsp_gen config.yml [--output-dir build] [--name core_name]
"""

import os
import argparse

import yaml

from litedsp.flow import netlist as netlist_mod
from litedsp.flow.ipcore import generate_ip

# Config -------------------------------------------------------------------------------------------

def parse_config(path):
    """Load the YAML config and return ``(netlist, core_config)``."""
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f.read())
    if not isinstance(config, dict):
        raise ValueError(f"Invalid config file: {path}")

    # Flow: inline section or reference to a netlist JSON (relative to the config file).
    flow      = config.get("flow",    None)
    json_path = config.get("netlist", None)
    if (flow is None) == (json_path is None):
        raise ValueError("Config must provide exactly one of 'flow' (inline) or 'netlist' (path).")
    if flow is not None:
        nl = netlist_mod.from_dict(flow)
    else:
        if not os.path.isabs(json_path):
            json_path = os.path.join(os.path.dirname(os.path.abspath(path)), json_path)
        nl = netlist_mod.load(json_path)

    # Core options.
    core_config = {}
    if "name" in config:
        core_config["name"] = config["name"]
    for key in ("csr_base", "axil_address_width", "csr_data_width"):
        if key in config:
            core_config[key] = int(config[key], 0) if isinstance(config[key], str) else int(config[key])
    return nl, core_config

# Core generation ----------------------------------------------------------------------------------

def generate_core(config_path, output_dir="build", name=None):
    """Generate the standalone core from a YAML config. Returns ``(verilog_path, ip)``."""
    nl, core_config = parse_config(config_path)
    name = name or core_config.pop("name", None) or (nl.name + "_core")
    core_config.pop("name", None)
    path, ip = generate_ip(nl, output_dir, name=name, **core_config)
    return path, ip

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteDSP standalone core generator.")
    parser.add_argument("config",                        help="YAML config file.")
    parser.add_argument("--name",       default=None,    help="Standalone core/module name (default: from config).")
    parser.add_argument("--output-dir", default="build", help="Output directory.")
    args = parser.parse_args()

    path, ip = generate_core(args.config, output_dir=args.output_dir, name=args.name)

    # Report generated artifacts + register map.
    build_dir = os.path.dirname(path)
    print(f"Generated: {path}")
    for f in ("csr.csv", "csr.json", "csr.h"):
        print(f"           {os.path.join(build_dir, f)}")
    if ip.chain.flow_inserted:
        print(f"Inserted glue: {', '.join(ip.chain.flow_inserted)}")
    for w in ip.chain.flow_warnings:
        print(f"Warning: {w}")
    print("CSR banks:")
    for bank_name, region in sorted(ip.csr_regions().items(), key=lambda kv: kv[1].origin):
        print(f"  0x{region.origin:08x}: {bank_name}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
