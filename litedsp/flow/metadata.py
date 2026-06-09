#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Machine-readable block metadata, derived by reflection.

A :class:`BlockSpec` describes one DSP block well enough to drive both a GUI palette and code
generation: its constructor parameters (from the signature), its stream ports + payload layouts
(from a built instance's endpoints), and its CSRs (from ``get_csrs()`` with ``with_csr=True`` —
LiteX recurses into sub-blocks and name-prefixes them automatically). Nothing is hand-duplicated;
the registry only supplies construction kwargs + cosmetic overrides (see :mod:`litedsp.flow.registry`).
"""

import inspect

from dataclasses import dataclass, field

from litex.soc.interconnect import stream

# Specs --------------------------------------------------------------------------------------------

@dataclass
class ParamSpec:
    name: str
    default: object
    kind: str                       # int | float | str | bool | list | none
    choices: list = None            # Enumerated string choices (for GUI dropdowns), if any.
    desc: str = ""

@dataclass
class PortSpec:
    name: str                       # Endpoint attribute, e.g. "sink", "source", "sinks[0]", "sink_a".
    direction: str                  # "sink" (input) or "source" (output).
    layout: str                     # iq | real | raw

@dataclass
class CsrSpec:
    name: str
    size: int

@dataclass
class BlockSpec:
    key: str
    cls: type
    display_name: str
    category: str
    params: list = field(default_factory=list)   # [ParamSpec]
    ports: list  = field(default_factory=list)   # [PortSpec]
    csrs: list   = field(default_factory=list)   # [CsrSpec]
    latency: object = None
    doc: str = ""

    def port(self, name):
        for p in self.ports:
            if p.name == name:
                return p
        return None

    @property
    def sinks(self):
        return [p for p in self.ports if p.direction == "sink"]

    @property
    def sources(self):
        return [p for p in self.ports if p.direction == "source"]

# Reflection helpers -------------------------------------------------------------------------------

def _real_init(cls):
    """The block's own ``__init__``, skipping migen's ``@ResetInserter`` (ModuleTransformer) wrap."""
    for c in cls.__mro__:
        init = c.__dict__.get("__init__")
        if init is None:
            continue
        if init.__qualname__.startswith("ModuleTransformer"):
            continue
        return init
    return cls.__init__

def _kind(value):
    if isinstance(value, bool):              # bool before int (bool subclasses int).
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, (list, tuple)):
        return "list"
    return "none"

def _accepts_with_csr(cls):
    return "with_csr" in inspect.signature(_real_init(cls)).parameters

def _params(cls, kwargs, choices):
    """ParamSpec list from the constructor signature; ``kwargs`` override defaults shown in the GUI."""
    specs = []
    for name, p in inspect.signature(_real_init(cls)).parameters.items():
        if name in ("self", "with_csr") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        default = kwargs[name] if name in kwargs else (None if p.default is p.empty else p.default)
        ch      = choices.get(name)
        kind    = _kind(default) if default is not None else ("str" if ch else "none")
        specs.append(ParamSpec(name=name, default=default, kind=kind, choices=ch))
    return specs

def _layout(ep):
    fields = [n for n, *_ in ep.description.payload_layout]
    if set(fields) >= {"i", "q"}:
        return "iq"
    if fields == ["data"]:
        return "real"
    return "raw"

def _ports(dut):
    """Discover every stream Endpoint on a built instance (singular, list, and named like sink_a)."""
    found = {}
    for attr in dir(dut):
        if attr.startswith("__"):
            continue
        try:
            v = getattr(dut, attr)
        except Exception:
            continue
        if isinstance(v, stream.Endpoint):
            found[attr] = v
        elif isinstance(v, (list, tuple)) and v and all(isinstance(e, stream.Endpoint) for e in v):
            for k, e in enumerate(v):
                found[f"{attr}[{k}]"] = e
    ports = []
    for name in sorted(found):
        base = name.split("[")[0]
        direction = "source" if base.startswith("source") else "sink"
        ports.append(PortSpec(name=name, direction=direction, layout=_layout(found[name])))
    return ports

# Public reflection entrypoint ---------------------------------------------------------------------

def reflect(key, cls, kwargs=None, category="misc", display_name=None, choices=None, doc=None):
    """Build a :class:`BlockSpec` for ``cls`` constructed with ``kwargs`` (with ``with_csr=True``)."""
    kwargs  = dict(kwargs or {})
    choices = choices or {}
    params  = _params(cls, kwargs, choices)

    build = dict(kwargs)
    if _accepts_with_csr(cls):
        build["with_csr"] = True
    dut = cls(**build)

    ports   = _ports(dut)
    csrs    = [CsrSpec(c.name, c.size) for c in dut.get_csrs()]
    latency = getattr(dut, "latency", None)
    doc     = doc or (cls.__doc__ or "").strip().split("\n")[0]
    return BlockSpec(key=key, cls=cls, display_name=display_name or key, category=category,
        params=params, ports=ports, csrs=csrs, latency=latency, doc=doc)
