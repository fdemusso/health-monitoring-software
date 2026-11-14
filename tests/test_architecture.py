"""Layering: plugin authors must be able to work against the SDK alone, and nothing may import the core
from below it. A new package must be added to LAYERS (same rule as ambientmonitor)."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ares3"

# package -> ares3 packages it may import (``ares3.core.constants`` is the one leaf the SDK may use)
LAYERS = {
    "schemas": set(),
    "sdk": {"schemas"},
    "core": {"schemas", "sdk"},
    "plugins": {"schemas", "sdk"},
    "export": {"schemas", "sdk", "core"},
}
LEAVES = {"ares3.core.constants", "ares3.core.rng", "ares3.core.clock"}


def _imports(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("ares3"):
            yield node.module
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("ares3"):
                    yield a.name


def test_layering():
    errors = []
    for pkg, allowed in LAYERS.items():
        for f in (SRC / pkg).rglob("*.py"):
            for mod in _imports(f):
                target = mod.split(".")[1] if "." in mod else ""
                if target in (pkg, "") or target in allowed or any(mod.startswith(leaf) for leaf in LEAVES):
                    continue
                errors.append(f"{f.relative_to(SRC)} imports {mod}")
    assert not errors, "\n".join(errors)
