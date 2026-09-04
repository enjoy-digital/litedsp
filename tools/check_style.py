#!/usr/bin/env python3
#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""LiteX coding-style checker for the LiteDSP sources.

Enforces the mechanical part of ``doc/coding_style.md`` of LiteX (header, 100-column section
separators, the ``# # #`` hardware separator, import grouping, CSR declaration style, script
hygiene and a soft 100-column line length that only aligned tables may exceed)::

    python3 tools/check_style.py            # whole repository
    python3 tools/check_style.py <paths>    # files or directories

Exit status is 1 when a rule is violated; ``test/test_style.py`` runs it in the unit suite.
"""

import re
import sys
import argparse
from pathlib import Path

# Rules --------------------------------------------------------------------------------------------

HEADER = ("#\n"
          "# This file is part of LiteDSP.\n"
          "#\n"
          "# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>\n"
          "# SPDX-License-Identifier: BSD-2-Clause\n")
SHEBANG    = "#!/usr/bin/env python3\n"
MAX_COLS   = 100
SKIP_DIRS  = {".git", "build", "__pycache__", ".eggs", "dist"}
HDL_ORDER  = ["from migen import", "from litex.gen import", "from litex.build",
              "from litex.soc.interconnect", "from litex.soc", "from litedsp"]

# Lines that are part of an aligned table may exceed the soft limit (LiteX style keeps register
# maps, argparse declarations and lookup tables compact); everything else wraps at 100 columns.
TABLE_LINE = re.compile(
    r"CSRField\(|\.add_argument\(|"                # Register maps and argparse declarations.
    r"^\s*\(\"[\w.]+\",|"                          # Registry / spec table rows.
    r"^\s*\"[\w./-]+\"\s*:|"                       # Dict table rows.
    r"^\s*'[\w./-]+'\s*:|"
    r"^\s*\"[\w]+\":\s*_v\(|"                      # Verification-spec rows.
    r"https?://")                                  # URLs cannot wrap.

def _iter_files(paths):
    for path in paths:
        path = Path(path)
        if path.is_dir():
            for p in sorted(path.rglob("*.py")):
                if not SKIP_DIRS & set(p.parts):
                    yield p
        elif path.suffix == ".py":
            yield path

def check_file(path):
    """Return the list of ``(line, rule, message)`` violations of one file."""
    text  = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    out   = []
    body  = text
    if body.startswith(SHEBANG):                   # Scripts: shebang, blank line, header.
        body = body[len(SHEBANG):].lstrip("\n")
    if text.strip() and not body.startswith(HEADER):
        out.append((1, "header", "missing or non-standard LiteDSP header"))
    if "\r" in text:
        out.append((1, "whitespace", "CRLF line ending"))
    if text and not text.endswith("\n"):
        out.append((len(lines), "whitespace", "no final newline"))
    is_hdl = path.parts[0] == "litedsp" if path.parts else False
    stdlib_block = []
    seen_order   = []
    for n, line in enumerate(lines, 1):
        if "\t" in line:
            out.append((n, "whitespace", "tab character"))
        if line.rstrip() != line:
            out.append((n, "whitespace", "trailing whitespace"))
        m = re.match(r"^# (.+?) (-{3,})$", line)
        if m and len(line) != MAX_COLS:
            out.append(
                (n, "banner", f"section separator is {len(line)} columns, expected {MAX_COLS}"))
        if len(line) > MAX_COLS and not TABLE_LINE.search(line):
            out.append((n, "length", f"{len(line)} columns"))
        if re.match(r"^\s*except\s*:", line):
            out.append((n, "except", "bare except"))
        if re.search(r"\bopen\(", line) and not re.search(r"\.open\(|encoding=|[\"']\w*b\w*[\"']",
                                                          line):
            out.append((n, "encoding", "text-mode open() without encoding=\"utf-8\""))
        if re.search(r"CSR(Field|Storage|Status)\(\s", line):
            out.append((n, "csr", "padding after the opening parenthesis of a CSR declaration"))
        if re.match(r"^import \w+$", line):
            stdlib_block.append((n, line))
        else:
            _check_stdlib_block(stdlib_block, out)
            stdlib_block = []
        if is_hdl:
            for i, prefix in enumerate(HDL_ORDER):
                if line.startswith(prefix):
                    if seen_order and i < seen_order[-1]:
                        out.append((n, "imports", f"'{prefix}' after a later import group"))
                    seen_order.append(i)
                    break
    _check_stdlib_block(stdlib_block, out)
    # CSRField declarations document their field.
    for m in re.finditer(r"CSRField\(", text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            if depth == 0:
                break
            i += 1
        if "description" not in text[m.start():i]:
            out.append((text.count("\n", 0, m.start()) + 1, "csr", "CSRField without description"))
    # Hardware modules separate their interface from the implementation.
    if is_hdl and re.search(r"class \w+\(.*LiteXModule\)", text) and \
       re.search(r"self\.(comb|sync|specials)\s*\+=", text) and "# # #" not in text:
        out.append((1, "separator", "LiteXModule without the '# # #' hardware separator"))
    return out

def _check_stdlib_block(block, out):
    if len(block) < 2:
        return
    names = [l.split()[1] for _, l in block]
    if names != sorted(names, key=lambda s: (len(s), s)):
        out.append((block[0][0], "imports", "stdlib imports not ordered by length then name"))

# Run ----------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteX coding-style checker for LiteDSP.")
    parser.add_argument("paths",   nargs="*", default=["."], help="Files or directories (default: repository).")
    parser.add_argument("--rules", default=None,             help="Comma-separated rule subset to report.")
    parser.add_argument("--summary", action="store_true",    help="Print counts per rule only.")
    args  = parser.parse_args()
    rules = set(args.rules.split(",")) if args.rules else None
    total = {}
    for path in _iter_files(args.paths):
        for n, rule, msg in check_file(path):
            if rules and rule not in rules:
                continue
            total[rule] = total.get(rule, 0) + 1
            if not args.summary:
                print(f"{path}:{n}: [{rule}] {msg}")
    for rule, count in sorted(total.items()):
        print(f"[{rule}] {count}", file=sys.stderr)
    return 1 if total else 0

if __name__ == "__main__":
    sys.exit(main())
