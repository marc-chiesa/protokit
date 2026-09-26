"""The installed-version lookup has one owner, and callers import it from there.

``protokit._cli_utils._get_protokit_version`` is the only place that asks
``importlib.metadata`` for protokit's version. It once had two byte-identical
``_protokit_version`` wrappers, in ``formatters/_builtin_lint.py`` and
``formatters/_builtin_compat.py``, each claiming a collapse that had not
happened, and ``_builtin_history`` and ``_builtin_bisect`` imported the compat
copy, so three sibling formatters were coupled for a version string (audit
V3, closed in 0.16.0 U17a).

A deletion has no branch to mutate, so this is the presence ratchet that
proves it (KTD3). Each predicate is decided from the syntax tree alone:

* only ``_cli_utils`` imports ``importlib.metadata`` (by either import form)
  or reaches it as ``importlib.metadata``;
* every import of ``_get_protokit_version`` names ``protokit._cli_utils``;
* no function outside the owner is a wrapper, meaning a body that, past its
  docstring and imports, is just ``return _get_protokit_version()``.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "protokit"
_OWNER_MODULE = "protokit._cli_utils"
_OWNER_PATH = _SRC / "_cli_utils.py"
_LOOKUP = "_get_protokit_version"


def _violations(source: str, *, is_owner: bool) -> list[str]:
    """Return a description of each single-owner violation in ``source``."""
    tree = ast.parse(source)
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            if not is_owner and (
                node.module == "importlib.metadata"
                or (node.module == "importlib" and "metadata" in names)
            ):
                found.append(f"line {node.lineno}: imports importlib.metadata")
            if _LOOKUP in names and node.module != _OWNER_MODULE:
                found.append(
                    f"line {node.lineno}: imports {_LOOKUP} from {node.module!r}, "
                    f"not {_OWNER_MODULE!r}"
                )
        elif isinstance(node, ast.Import):
            if not is_owner and any(
                alias.name == "importlib.metadata" for alias in node.names
            ):
                found.append(f"line {node.lineno}: imports importlib.metadata")
        elif isinstance(node, ast.Attribute):
            if (
                not is_owner
                and node.attr == "metadata"
                and isinstance(node.value, ast.Name)
                and node.value.id == "importlib"
            ):
                found.append(f"line {node.lineno}: reaches importlib.metadata")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == _LOOKUP:
                if not is_owner:
                    found.append(f"line {node.lineno}: defines {_LOOKUP}")
                continue
            body = [
                stmt
                for stmt in node.body
                if not isinstance(stmt, (ast.Import, ast.ImportFrom))
                and not (
                    isinstance(stmt, ast.Expr)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                )
            ]
            if (
                len(body) == 1
                and isinstance(body[0], ast.Return)
                and isinstance(body[0].value, ast.Call)
                and isinstance(body[0].value.func, ast.Name)
                and body[0].value.func.id == _LOOKUP
            ):
                found.append(f"line {node.lineno}: {node.name}() wraps {_LOOKUP}")
    return found


class TestVersionLookupSingleOwner:
    def test_the_owner_defines_the_lookup(self) -> None:
        # Vacuity guard: if the owner moved, every predicate below would pass
        # on a tree with no lookup to protect.
        tree = ast.parse(_OWNER_PATH.read_text())
        defined = {
            node.name for node in tree.body if isinstance(node, ast.FunctionDef)
        }
        assert _LOOKUP in defined, f"{_OWNER_MODULE} no longer defines {_LOOKUP}"

    def test_no_module_duplicates_wraps_or_reroutes_the_lookup(self) -> None:
        modules = sorted(_SRC.rglob("*.py"))
        assert _OWNER_PATH in modules
        report = {
            str(path.relative_to(_SRC.parent)): found
            for path in modules
            if (found := _violations(path.read_text(), is_owner=path == _OWNER_PATH))
        }
        assert not report, (
            "the protokit version lookup must have one owner "
            f"({_OWNER_MODULE}.{_LOOKUP}), imported from there directly:\n"
            + "\n".join(f"  {path}: {'; '.join(items)}" for path, items in report.items())
        )


class TestViolationDetector:
    """Each rule fires on the shape it names, and the clean shape passes."""

    def test_a_clean_caller_passes(self) -> None:
        source = (
            "def render():\n"
            f"    from {_OWNER_MODULE} import {_LOOKUP}\n"
            f"    return {{'version': {_LOOKUP}()}}\n"
        )
        assert _violations(source, is_owner=False) == []

    def test_the_removed_wrapper_shape_is_named(self) -> None:
        source = (
            "def _protokit_version() -> str:\n"
            '    """Thin wrapper."""\n'
            f"    from {_OWNER_MODULE} import {_LOOKUP}\n"
            f"    return {_LOOKUP}()\n"
        )
        assert _violations(source, is_owner=False) == [
            f"line 1: _protokit_version() wraps {_LOOKUP}"
        ]

    def test_import_from_a_sibling_is_named(self) -> None:
        source = f"from protokit.formatters._builtin_compat import {_LOOKUP}\n"
        assert len(_violations(source, is_owner=False)) == 1

    def test_every_route_to_importlib_metadata_is_named(self) -> None:
        for source in (
            "from importlib.metadata import version\n",
            "from importlib import metadata\n",
            "import importlib.metadata\n",
            "import importlib\nv = importlib.metadata.version('protokit')\n",
        ):
            assert _violations(source, is_owner=False), source
            assert _violations(source, is_owner=True) == [], source

    def test_a_second_definition_is_named(self) -> None:
        source = f"def {_LOOKUP}() -> str:\n    return '0'\n"
        assert _violations(source, is_owner=False) == [f"line 1: defines {_LOOKUP}"]
