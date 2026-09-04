#!/usr/bin/env python3
#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Check that formatting-only edits kept the Python AST (docstrings excepted)::

    python3 tools/ast_equal.py <file>...          # working tree vs git HEAD
    python3 tools/ast_equal.py --ref <rev> <file>...

Adjacent string literals fold at parse time and line numbers are not compared, so wrapping
lines, splitting strings, re-aligning assignments and rewording comments / docstrings all pass;
any change of behaviour fails.
"""

import ast
import sys
import argparse
import subprocess

def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr) and \
               isinstance(getattr(node.body[0], "value", None), ast.Constant) and \
               isinstance(node.body[0].value.value, str):
                node.body = node.body[1:] or [ast.Pass()]
    return tree

def dump(source):
    return ast.dump(_strip_docstrings(ast.parse(source)))

def main():
    parser = argparse.ArgumentParser(description="AST equality of formatting-only edits.")
    parser.add_argument("files", nargs="+", help="Files to compare.")
    parser.add_argument("--ref", default="HEAD", help="Git revision holding the reference (default: HEAD).")
    args = parser.parse_args()
    failed = 0
    for f in args.files:
        try:
            old = subprocess.run(["git", "show", f"{args.ref}:{f}"], capture_output=True, text=True, check=True).stdout
        except subprocess.CalledProcessError:
            print(f"{f}: not in {args.ref} (new file, skipped)")
            continue
        with open(f, encoding="utf-8") as fp:
            new = fp.read()
        if dump(old) != dump(new):
            print(f"{f}: AST DIFFERS")
            failed += 1
        else:
            print(f"{f}: same AST")
    return 1 if failed else 0

if __name__ == "__main__":
    sys.exit(main())
