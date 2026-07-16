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
class CsrFieldSpec:
    name: str
    size: int
    offset: int
    description: str = ""
    values: list = None             # [(value, description)] enumerations, if any.
    reset: int = 0
    pulse: bool = False

@dataclass
class CsrSpec:
    name: str
    size: int
    access: str = ""                # "read-write" (CSRStorage) or "read-only" (CSRStatus).
    reset: int = 0
    description: str = ""
    fields: list = field(default_factory=list)  # [CsrFieldSpec]

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
    doc_full: str = ""                           # Whole cleaned class docstring.
    kwargs: dict = field(default_factory=dict)   # Construction defaults (registry-supplied).
    has_csr: bool = False                        # Accepts a with_csr constructor flag.
    has_bypass: bool = False                     # Exposes a boolean bypass control.

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

# Parameter Glossary -------------------------------------------------------------------------------
#
# Descriptions for the ubiquitous constructor parameters, so block docstrings only need to
# document their block-specific parameters (a numpydoc "Parameters" section, parsed below).

PARAM_GLOSSARY = {
    "data_width":    "Sample width in bits (signed Qm.n; default Q1.15).",
    "n_samples":     "Samples per beat (multi-sample-per-cycle parallel datapaths).",
    "n_taps":        "Number of FIR taps.",
    "coefficients":  "Coefficient list (signed integers, quantized via litedsp.filter.design).",
    "decimation":    "Integer decimation factor.",
    "interpolation": "Integer interpolation factor.",
    "n_stages":      "Number of CIC integrator/comb stages (N in the literature).",
    "diff_delay":    "CIC comb differential delay (M in the literature).",
    "staged":        "Select the elastic registered-stage CIC architecture (higher latency, one sample per clock).",
    "delayed_feedback": "Apply AGC magnitude feedback on the following accepted sample.",
    "frac_bits":     "Fractional bits of the coefficient/control fixed-point format.",
    "frac":          "Fractional bits of the control fixed-point format.",
    "phase_bits":    "Phase accumulator width in bits.",
    "shift":         "Output rescale shift (defaults to data_width - 1).",
    "window":        "Window function (rect/hann/hamming/blackman).",
    "N":             "Transform size (power of two).",
    "method":        "Core implementation selector.",
    "with_irq":      "Add a LiteX EventManager interrupt on the block's trigger event.",
}

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

def _doc_params(doc):
    """Parse a numpydoc-style ``Parameters`` section into ``{name: description}``."""
    out   = {}
    lines = (doc or "").splitlines()
    try:
        start = next(i for i, l in enumerate(lines)
                     if l.strip() == "Parameters" and i + 1 < len(lines)
                     and set(lines[i + 1].strip()) == {"-"})
    except StopIteration:
        return out
    name = None
    for l in lines[start + 2:]:
        s = l.strip()
        if not s:
            continue
        if not l.startswith((" ", "\t")) or set(s) == {"-"}:
            if set(s) == {"-"}:
                break  # Next underlined section.
        if " : " in s or (s.replace("_", "").isalnum() and not l.startswith("        ")):
            name = s.split(" : ")[0].strip()
            out[name] = ""
        elif name:
            out[name] = (out[name] + " " + s).strip()
    return out

def _params(cls, kwargs, choices):
    """ParamSpec list from the constructor signature; ``kwargs`` override defaults shown in the GUI."""
    specs = []
    doc   = inspect.getdoc(cls) or ""
    descs = _doc_params(doc)
    for name, p in inspect.signature(_real_init(cls)).parameters.items():
        if name in ("self", "with_csr") or p.kind in (p.VAR_POSITIONAL, p.VAR_KEYWORD):
            continue
        default = kwargs[name] if name in kwargs else (None if p.default is p.empty else p.default)
        ch      = choices.get(name)
        kind    = _kind(default) if default is not None else ("str" if ch else "none")
        desc    = descs.get(name) or PARAM_GLOSSARY.get(name, "")
        specs.append(ParamSpec(name=name, default=default, kind=kind, choices=ch, desc=desc))
    return specs

def _csr_fields(csr):
    """CsrFieldSpec list from a LiteX CSRStorage/CSRStatus with named CSRFields."""
    agg = getattr(csr, "fields", None)
    out = []
    for f in getattr(agg, "fields", []) or []:
        values = [(str(v), d) for v, d in (f.values or [])] if getattr(f, "values", None) else None
        reset  = getattr(f, "reset", 0)
        reset  = getattr(reset, "value", reset)  # Migen Constant -> int.
        out.append(CsrFieldSpec(name=f.name, size=f.size, offset=f.offset,
            description=f.description or "", values=values,
            reset=int(reset or 0), pulse=bool(getattr(f, "pulse", False) is True)))
    return out

def _csr_spec(csr):
    """CsrSpec (incl. access/reset/description/fields) from a LiteX CSR object."""
    kind   = type(csr).__name__
    access = {"CSRStorage": "read-write", "CSRStatus": "read-only"}.get(kind, "")
    reset  = 0
    for attr in ("storage", "status"):
        sig = getattr(csr, attr, None)
        if sig is not None:
            reset = getattr(getattr(sig, "reset", None), "value", 0) or 0
            break
    return CsrSpec(name=csr.name, size=csr.size, access=access, reset=reset,
        description=getattr(csr, "description", "") or "", fields=_csr_fields(csr))

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

    ports    = _ports(dut)
    csrs     = [_csr_spec(c) for c in dut.get_csrs()]
    latency  = getattr(dut, "latency", None)
    doc_full = inspect.getdoc(cls) or ""
    doc      = doc or doc_full.split("\n")[0]
    return BlockSpec(key=key, cls=cls, display_name=display_name or key, category=category,
        params=params, ports=ports, csrs=csrs, latency=latency, doc=doc, doc_full=doc_full,
        kwargs=dict(kwargs), has_csr=_accepts_with_csr(cls),
        has_bypass=hasattr(dut, "bypass"))
