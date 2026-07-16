#!/usr/bin/env python3

#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Per-block datasheet generator: reflection -> doc/blocks/<key>.md.

Iterates the flow registry (:mod:`litedsp.flow.registry`) and emits one markdown datasheet
per block (overview, parameter table, port table, latency, register map with field
descriptions, FPGA resources joined from ``impl/budgets.json``) plus an index/catalog page.
Nothing is hand-written: the same reflection that drives the GUI and code generation drives
the documentation, so it cannot drift from the code.

Usage::

    python3 -m litedsp.flow.docgen             # (Re)generate doc/blocks/.
    python3 -m litedsp.flow.docgen --check     # CI: fail if doc/blocks/ is stale.
"""

import os
import json
import argparse

from litedsp.flow import registry

# Helpers ------------------------------------------------------------------------------------------

CATEGORY_TITLES = {
    "generation": "Signal Generation",
    "mixing":     "Mixing / Frequency Translation",
    "filter":     "Filtering",
    "rate":       "Rate Conversion",
    "level":      "Level Control / Measurement",
    "correction": "Impairment Correction",
    "comm":       "Communications",
    "analysis":   "Analysis / Measurement",
    "stream":     "Stream Utilities",
}

def _root():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

def _budgets():
    path = os.path.join(_root(), "impl", "budgets.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def _fmt_default(p):
    if p.default is None:
        return "—"
    if isinstance(p.default, str):
        return f'`"{p.default}"`'
    return f"`{p.default!r}`"

def _latency_str(spec):
    if spec.latency is None:
        return "variable (data-dependent)"
    return f"{spec.latency} sample{'s' if spec.latency != 1 else ''}"

def _overview(doc_full):
    """Docstring prose without the numpydoc Parameters section (rendered as a table instead)."""
    lines = doc_full.splitlines()
    for i in range(len(lines) - 1):
        if lines[i].strip() == "Parameters" and set(lines[i + 1].strip()) == {"-"}:
            return "\n".join(lines[:i]).rstrip()
    return doc_full

# Datasheet ----------------------------------------------------------------------------------------

def block_page(spec, budgets):
    """Render one block's datasheet as markdown."""
    mod = spec.cls.__module__
    out = []
    out.append(f"# {spec.display_name}")
    out.append("")
    out.append(f"`{spec.cls.__name__}` — `{mod}` — category `{spec.category}`")
    out.append("")
    feats = [f"latency: {_latency_str(spec)}",
             f"CSR: {'yes' if spec.csrs else 'no'}",
             f"bypass: {'yes' if spec.has_bypass else 'no'}"]
    out.append(" · ".join(feats))
    out.append("")
    if spec.doc_full:
        out.append("## Overview")
        out.append("")
        out.append(_overview(spec.doc_full))
        out.append("")
    if spec.params:
        out.append("## Parameters")
        out.append("")
        out.append("| Parameter | Default | Type | Description |")
        out.append("|---|---|---|---|")
        for p in spec.params:
            desc = p.desc or ""
            if p.choices:
                desc = (desc + " " if desc else "") + f"Choices: {', '.join(f'`{c}`' for c in p.choices)}."
            out.append(f"| `{p.name}` | {_fmt_default(p)} | {p.kind} | {desc} |")
        out.append("")
    if spec.ports:
        out.append("## Ports")
        out.append("")
        out.append("| Port | Direction | Layout |")
        out.append("|---|---|---|")
        for p in spec.ports:
            out.append(f"| `{p.name}` | {p.direction} | {p.layout} |")
        out.append("")
        out.append("Streams follow the LiteX `valid`/`ready` contract (see `doc/interfaces.md`).")
        out.append("")
    if spec.csrs:
        out.append("## Register Map")
        out.append("")
        for c in spec.csrs:
            out.append(f"### `{c.name}` ({c.access}, {c.size} bit{'s' if c.size != 1 else ''}"
                       + (f", reset `0x{c.reset:x}`" if c.reset else "") + ")")
            out.append("")
            if c.description:
                out.append(c.description)
                out.append("")
            if c.fields:
                out.append("| Bits | Field | Reset | Description |")
                out.append("|---|---|---|---|")
                for f in c.fields:
                    bits = f"[{f.offset + f.size - 1}:{f.offset}]" if f.size > 1 else f"[{f.offset}]"
                    desc = f.description + (" (pulse)" if f.pulse else "")
                    if f.values:
                        desc += " " + "; ".join(f"{v}: {d}" for v, d in f.values)
                    out.append(f"| `{bits}` | `{f.name}` | `{f.reset}` | {desc} |")
                out.append("")
    b = budgets.get(spec.key)
    out.append("## FPGA Resources")
    out.append("")
    if b:
        out.append("| Device | LUT | FF | BRAM | DSP | Fmax floor (MHz) | Fmax target (MHz) |")
        out.append("|---|---|---|---|---|---|---|")
        for dev in ("ecp5", "xilinx"):
            d = b.get(dev)
            if not d:
                continue
            floor  = d.get("fmax_min")
            target = d.get("fmax_target")
            out.append(f"| {dev} | {d.get('lut', '—')} | {d.get('ff', '—')} | {d.get('bram', '—')} "
                       f"| {d.get('dsp', '—')} | {floor if floor is not None else '—'} "
                       f"| {target if target is not None else '—'} |")
        out.append("")
        out.append("Resources are measured by the `impl/` flows at the registry configuration; "
                   "the fmax floor is the regression guard (85% of baseline P&R); an optional "
                   "target is the independent engineering objective. "
                   "Regenerate with `python3 impl/report.py` (budget-gated in CI).")
    else:
        out.append("Not characterized yet (no `impl/budgets.json` entry).")
    out.append("")
    test_mod = f"test/test_{mod.rsplit('.', 1)[-1]}.py"
    if os.path.exists(os.path.join(_root(), test_mod)):
        out.append("## Verification")
        out.append("")
        out.append(f"Golden-model tests: `{test_mod}` (bit-exact/SNR under randomized backpressure).")
        out.append("")
    return "\n".join(out).rstrip() + "\n"

def index_page(by_category, budgets):
    """Render the catalog index."""
    out = ["# LiteDSP Block Catalog", ""]
    total = sum(len(v) for v in by_category.values())
    out.append(f"{total} blocks, generated from the block registry by `litedsp/flow/docgen.py` "
               "(do not edit by hand — regenerate with `python3 -m litedsp.flow.docgen`).")
    out.append("")
    for cat, specs in by_category.items():
        out.append(f"## {CATEGORY_TITLES.get(cat, cat)} (`{cat}/`)")
        out.append("")
        out.append("| Block | Class | Latency | DSP | Description |")
        out.append("|---|---|---|---|---|")
        for spec in specs:
            b   = budgets.get(spec.key, {}).get("ecp5", {})
            dsp = b.get("dsp", "—")
            lat = "var" if spec.latency is None else spec.latency
            out.append(f"| [{spec.display_name}]({spec.key}.md) | `{spec.cls.__name__}` "
                       f"| {lat} | {dsp} | {spec.doc} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"

# Generation ---------------------------------------------------------------------------------------

def generate(out_dir=None):
    """Generate all datasheets; returns ``{relpath: content}``."""
    budgets = _budgets()
    by_cat  = registry.by_category()
    pages   = {"index.md": index_page(by_cat, budgets)}
    for specs in by_cat.values():
        for spec in specs:
            pages[f"{spec.key}.md"] = block_page(spec, budgets)
    if out_dir is not None:
        os.makedirs(out_dir, exist_ok=True)
        for name, content in pages.items():
            with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
                f.write(content)
    return pages

def choose_check(out_dir, pages):
    """Return the list of stale/missing/extra files vs ``pages``."""
    stale = []
    for name, content in pages.items():
        path = os.path.join(out_dir, name)
        if not os.path.exists(path) or open(path, encoding="utf-8").read() != content:
            stale.append(name)
    for existing in sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []:
        if existing.endswith(".md") and existing not in pages:
            stale.append(f"{existing} (orphan)")
    return stale

def main():
    parser = argparse.ArgumentParser(description="LiteDSP per-block datasheet generator.")
    parser.add_argument("--out",    default=None,         help="Output directory (default: doc/blocks/).")
    parser.add_argument("--check",  action="store_true",  help="Fail if generated docs are stale (CI).")
    args = parser.parse_args()

    out_dir = args.out or os.path.join(_root(), "doc", "blocks")
    if args.check:
        stale = choose_check(out_dir, generate(out_dir=None))
        if stale:
            print(f"doc/blocks/ is stale ({len(stale)} files) — regenerate with "
                  "python3 -m litedsp.flow.docgen:")
            for name in stale[:20]:
                print(f"  {name}")
            return 1
        print("doc/blocks/ is up to date.")
        return 0
    pages = generate(out_dir=out_dir)
    print(f"Generated {len(pages)} pages in {out_dir}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
