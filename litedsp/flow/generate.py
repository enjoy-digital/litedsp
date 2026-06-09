#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Headless code generation: netlist JSON -> chain Verilog.

This is the Phase-1 path (datapath Verilog via the existing ``sim/verilog.py``). Phase 2's
``ipcore`` adds the AXI-Stream/AXI-Lite wrapper + CSR register-map artifacts. Used identically by
the CLI, by tests, and (later) by the GUI's "Generate" button.

CLI::

    python -m litedsp.flow.generate flow.json --out build/ [--name foo] [--csr]
"""

import os
import sys
import argparse

from litedsp.flow import netlist as netlist_mod
from litedsp.flow.builder import FlowChain

# Code generation ----------------------------------------------------------------------------------

def build_chain(source, with_csr=False):
    """Return a :class:`FlowChain` from a Netlist object or a netlist JSON path."""
    nl = source if isinstance(source, netlist_mod.Netlist) else netlist_mod.load(source)
    return FlowChain(nl, with_csr=with_csr)

def generate(source, build_dir, name=None, with_csr=False):
    """Assemble ``source`` and emit chain Verilog into ``build_dir``. Returns ``(path, chain)``."""
    from sim.verilog import to_verilog                      # Imported lazily (repo-local helper).
    nl    = source if isinstance(source, netlist_mod.Netlist) else netlist_mod.load(source)
    chain = FlowChain(nl, with_csr=with_csr)
    name  = name or nl.name
    ios   = chain.io_signals()
    path  = to_verilog(chain, ios, name, build_dir)
    return path, chain

# CLI ----------------------------------------------------------------------------------------------

def main(argv=None):
    p = argparse.ArgumentParser(description="Generate chain Verilog from a LiteDSP flow netlist.")
    p.add_argument("netlist", help="Path to the netlist JSON.")
    p.add_argument("--out",  default="build", help="Output build directory.")
    p.add_argument("--name", default=None,    help="Top module name (default: netlist name).")
    p.add_argument("--csr",  action="store_true", help="Build sub-blocks with CSRs (with_csr=True).")
    args = p.parse_args(argv)

    # Make the repo root importable so `sim.verilog` resolves when run from anywhere.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    path, chain = generate(args.netlist, args.out, name=args.name, with_csr=args.csr)
    print(f"Generated: {path}")
    if chain.flow_inserted:
        print(f"  inserted glue: {', '.join(chain.flow_inserted)}")
    for w in chain.flow_warnings:
        print(f"  warning: {w}")
    if args.csr:
        print(f"  CSRs: {len(chain.get_csrs())}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
