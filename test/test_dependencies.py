#
# This file is part of LiteDSP.
#
# Copyright (c) 2026 Florent Kermarrec <florent@enjoy-digital.fr>
# SPDX-License-Identifier: BSD-2-Clause

"""Dependencies: what the block registry imports at load time is in setup.py install_requires."""

import os
import ast
import sys
import json
import unittest
import subprocess
import importlib.util
from unittest import mock

import setuptools

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Distribution name -> import name, where they differ.
IMPORT_NAMES = {"pyyaml": "yaml"}

# Helpers ------------------------------------------------------------------------------------------

def setup_kwargs():
    """Run setup.py with setuptools.setup mocked and return the arguments it was given."""
    cwd = os.getcwd()
    os.chdir(ROOT)
    try:
        with mock.patch.object(setuptools, "setup") as setup:
            with open("setup.py", encoding="utf-8") as f:
                exec(compile(f.read(), "setup.py", "exec"), {"__name__": "__main__"})
    finally:
        os.chdir(cwd)
    return setup.call_args.kwargs

LOAD_REGISTRY = """
import sys, json
import litedsp
from litedsp.flow.registry import registry
n = len(registry())
files = sorted({m.__file__ for k, m in list(sys.modules.items())
    if (k == "litedsp" or k.startswith("litedsp.")) and getattr(m, "__file__", None)})
print(json.dumps({"blocks": n, "files": files}))
"""

def load_registry():
    """Load the registry in a fresh interpreter, return the block count and litedsp files loaded."""
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([ROOT] + [p for p in [env.get("PYTHONPATH")] if p])
    out = subprocess.run([sys.executable, "-c", LOAD_REGISTRY], cwd=ROOT, env=env, check=True,
        capture_output=True, text=True).stdout
    return json.loads(out.strip().splitlines()[-1])

def module_level_imports(path):
    """Top-level names imported by the module-level statements of a Python file."""
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names

def is_third_party(name):
    if name in getattr(sys, "stdlib_module_names", ()):
        return False
    spec = importlib.util.find_spec(name)
    if spec is None or spec.origin in (None, "built-in", "frozen"):
        return spec is None
    return any(d in spec.origin for d in ("site-packages", "dist-packages"))

# Test Dependencies --------------------------------------------------------------------------------

class TestDependencies(unittest.TestCase):
    def test_registry_loads(self):
        self.assertGreater(load_registry()["blocks"], 0)

    def test_registry_imports_are_install_requires(self):
        required = {IMPORT_NAMES.get(r, r) for r in setup_kwargs()["install_requires"]}
        imported = set()
        for path in load_registry()["files"]:
            imported |= module_level_imports(path)
        imported.discard("litedsp")
        missing = sorted(n for n in imported if n not in required and is_third_party(n))
        self.assertEqual(missing, [])

if __name__ == "__main__":
    unittest.main()
