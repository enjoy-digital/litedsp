#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Coerce GUI text-field values to typed block parameters (per ParamSpec). Pure / testable."""

import json

def coerce(param, raw):
    """Convert a raw widget value/string to the type implied by ``param`` (a ParamSpec)."""
    if raw is None or (isinstance(raw, str) and raw.strip() == ""):
        return param.default
    if isinstance(raw, str) and raw.strip() == "None":  # Untouched widget for a None default.
        return None
    if param.kind == "int":
        return int(raw, 0) if isinstance(raw, str) else int(raw)
    if param.kind == "float":
        return float(raw)
    if param.kind == "bool":
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    if param.kind == "list":
        return json.loads(raw) if isinstance(raw, str) else list(raw)
    return raw          # str / none -> pass through.

def coerce_params(spec, values):
    """Coerce a ``{name: raw}`` dict against a BlockSpec, dropping values equal to defaults."""
    out = {}
    by_name = {p.name: p for p in spec.params}
    for name, raw in values.items():
        if name not in by_name:
            continue
        val = coerce(by_name[name], raw)
        if val != by_name[name].default:
            out[name] = val
    return out
