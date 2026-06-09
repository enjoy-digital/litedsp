#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""The editor's block palette, derived from the flow registry (pure / testable)."""

from litedsp.flow import registry

def categories():
    """Return ``{category: [BlockSpec sorted by display_name]}`` for the palette."""
    cats = registry.by_category()
    return {c: sorted(cats[c], key=lambda s: s.display_name) for c in sorted(cats)}
