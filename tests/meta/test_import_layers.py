"""Import-layer meta test: ``protokit`` has zero module-load import cycles (U21, KTD8).

Every Wave B unit of the 0.16.0 correctness programme hoists shared logic into
a layer-0 seam module (``_fieldview``, ``_extensions``, ``_records``,
``_trust``, ``_atomic``, ``schema/_git_cmd``) that the rest of the package
imports. That is safe only while the package's import graph stays acyclic at
module-load time and the seams themselves import nothing from ``protokit``.
This test commits both properties as a gate, so a seam PR is checked by CI
rather than by an audit-time script. (The 2026-08-30 audit's own count —
"exactly one cycle, in ``protokit.formatters``" — was wrong; measured under the
rules below, the tree has zero.)

What counts as an edge — the load-bearing rules:

* **Only imports executed at module load.** An import inside a function body
  is deferred, and in this codebase deferred imports exist precisely to break
  a load-time cycle (``schema/profiles.py`` imports ``schema.checker`` inside
  a method; ``message/pytest_plugin.py`` imports ``message.matchers`` inside a
  hook), so counting them would report the cycles they prevent. An import
  under ``if TYPE_CHECKING:`` never executes and is excluded; that block's
  ``else`` branch, a ``try``/``except`` arm, a plain ``if``, and a class body
  all run at import time and count.
* **``from <pkg> import <name>`` is an edge to the submodule ``<pkg>.<name>``
  when that is a module in the tree, and to ``<pkg>`` otherwise.** A package
  ``__init__`` that imports its own submodules, which in turn do ``from <pkg>
  import <sibling>``, is the ``protokit.formatters`` shape. Under the rule the
  interpreter follows (``<pkg>/__init__`` runs before ``<pkg>.<name>``) that
  shape is a five-module strongly connected component; it is a
  package-initialisation artefact, not a load-order hazard, and this rule
  excludes it. A ``from <pkg> import <attr>`` where ``<attr>`` is *not* a
  module is an edge to ``<pkg>``: it needs ``<pkg>/__init__`` to have bound
  the name, which is a genuine load-order dependency.
* **``import <mod>`` is an edge to exactly ``<mod>``**, whoever the importer's
  parent package is — a submodule importing its own package is not exempt.
* A module's import of itself is not an edge.

Acyclicity is decided by ``graphlib.TopologicalSorter.prepare()``; the
``CycleError`` it raises carries the cycle in ``args[1]``, which the failure
message renders in import order so both ends of the cycle are named. The lint
engine's private ``_tarjan_scc`` is deliberately not reused: a meta gate must
not depend on a module the 0.17.0 decomposition moves, and enumerating
strongly connected components is more than "is there a cycle" needs (see
``docs/solutions/best-practices/tarjan-scc-iterative-dfs-package-cycle-detection-2026-05-22.md``).

KTD3 proof: the self-tests below run the same walk over synthetic packages
with one violation injected each and assert the failure names it; a meta test
has no ``src`` anchor for ``scripts/mutation_check.py``.
"""

from __future__ import annotations

import ast
import graphlib
from collections.abc import Iterable, Iterator, Mapping
from itertools import pairwise
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src"
PACKAGE = "protokit"

# Layer-0 seam modules the 0.16.0 plan introduces (KTD8). Each is asserted to
# import nothing from ``protokit`` once it exists in the tree; a name absent
# from the tree is skipped, so the assertion grows as Wave B lands (U3, U5,
# U6, U7, U12, U13) instead of failing on modules that have not landed yet.
SEAM_MODULES = (
    "protokit._fieldview",
    "protokit._extensions",
    "protokit._records",
    "protokit._trust",
    "protokit._atomic",
    "protokit.schema._git_cmd",
)

# Function-level imports that exist to break a load-time cycle: the reverse
# direction is a top-level import, so hoisting either of these to module scope
# closes a cycle. Pinned so the top-level-only rule is proven on the real tree
# — each edge is absent from the load-time graph and present once deferred
# imports are counted — rather than only on synthetic packages.
DEFERRED_EDGES = (
    ("protokit.schema.profiles", "protokit.schema.checker"),
    ("protokit.message.pytest_plugin", "protokit.message.matchers"),
)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

# Scopes whose body runs when called, not when the module loads.
_DEFERRED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def discover_modules(src_root: Path, package: str) -> dict[str, Path]:
    """Dotted module name -> source file for every ``.py`` under ``src_root/package``."""
    modules: dict[str, Path] = {}
    for path in sorted((src_root / package).rglob("*.py")):
        parts = path.relative_to(src_root).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    return modules


def _in_package(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"


def _executed_imports(
    nodes: Iterable[ast.AST], *, include_deferred: bool
) -> Iterator[ast.Import | ast.ImportFrom]:
    """Import statements among ``nodes``, recursively, that run at module load.

    A function body is skipped unless ``include_deferred``. The body of an
    ``if TYPE_CHECKING:`` block is always skipped; its ``else`` branch runs.
    Every other compound statement (``if``, ``try``, ``with``, ``class``) is
    entered, because its body executes as the module loads.
    """
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, _DEFERRED_SCOPES) and not include_deferred:
            continue
        elif isinstance(node, ast.If) and _is_type_checking(node.test):
            yield from _executed_imports(node.orelse, include_deferred=include_deferred)
        else:
            yield from _executed_imports(
                ast.iter_child_nodes(node), include_deferred=include_deferred
            )


def _from_import_base(importer: str, is_package: bool, node: ast.ImportFrom) -> str:
    """The absolute module a ``from ... import`` names, resolving a relative level."""
    if not node.level:
        return node.module or ""
    parts = importer.split(".")
    if not is_package:
        parts = parts[:-1]
    parts = parts[: max(len(parts) - (node.level - 1), 0)]
    if node.module:
        parts.extend(node.module.split("."))
    return ".".join(parts)


def _import_targets(
    importer: str,
    is_package: bool,
    node: ast.Import | ast.ImportFrom,
    modules: Mapping[str, Path],
    package: str,
) -> set[str]:
    """The package modules ``node`` is an edge to, under the rules in the docstring."""
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names if _in_package(alias.name, package)}
    base = _from_import_base(importer, is_package, node)
    if not _in_package(base, package):
        return set()
    targets: set[str] = set()
    for alias in node.names:
        submodule = f"{base}.{alias.name}"
        targets.add(submodule if submodule in modules else base)
    return targets


def build_import_graph(
    src_root: Path, package: str, *, include_deferred: bool = False
) -> dict[str, set[str]]:
    """``importer -> {imported}`` over the package's own modules.

    Only imports executed at module load count unless ``include_deferred`` is
    set, in which case function-level imports count too (``TYPE_CHECKING``
    blocks never do). Every module of the tree is a key, even with no edges.
    """
    modules = discover_modules(src_root, package)
    graph: dict[str, set[str]] = {}
    for name, path in modules.items():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        is_package = path.name == "__init__.py"
        targets: set[str] = set()
        for node in _executed_imports(tree.body, include_deferred=include_deferred):
            targets |= _import_targets(name, is_package, node, modules, package)
        targets.discard(name)
        graph[name] = targets
    return graph


def find_cycle(graph: Mapping[str, set[str]]) -> list[str] | None:
    """One import cycle in ``graph`` rendered in import order, or ``None``.

    The path starts and ends on the same module, and each module imports the
    next: ``["a", "b", "a"]`` means ``a`` imports ``b`` imports ``a``.
    """
    try:
        graphlib.TopologicalSorter(graph).prepare()
    except graphlib.CycleError as exc:
        # graphlib reads ``graph[node]`` as the node's predecessors and lists
        # the cycle predecessor-first; reversed, it reads importer-first.
        return list(reversed(exc.args[1]))
    return None


def format_cycle(cycle: Iterable[str]) -> str:
    return " -> ".join(cycle)


def layer0_violations(graph: Mapping[str, set[str]], seams: Iterable[str]) -> dict[str, set[str]]:
    """``seam -> {package modules it imports}`` for every listed seam in ``graph``.

    A seam absent from the graph has not landed yet and is skipped.
    """
    return {seam: set(graph[seam]) for seam in seams if seam in graph and graph[seam]}


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def graph() -> dict[str, set[str]]:
    return build_import_graph(_SRC_ROOT, PACKAGE)


class TestImportLayers:
    def test_protokit_has_no_module_load_import_cycles(self, graph: dict[str, set[str]]) -> None:
        cycle = find_cycle(graph)
        assert cycle is None, (
            "protokit has a module-load import cycle (KTD8):\n"
            f"  {format_cycle(cycle or ())}\n"
            "(-> reads 'imports at module load'; a deferred, function-level import "
            "is the sanctioned way to break one — see this module's docstring)"
        )

    def test_graph_covers_every_module_and_every_edge_resolves_in_tree(
        self, graph: dict[str, set[str]]
    ) -> None:
        # Vacuity guard: a walker that skipped files, or a resolver that
        # produced names outside the tree, would make the cycle assertion
        # pass on a graph that is not the package's.
        modules = discover_modules(_SRC_ROOT, PACKAGE)
        assert set(graph) == set(modules)
        assert len(modules) == len(list((_SRC_ROOT / PACKAGE).rglob("*.py")))
        anchors = {PACKAGE, f"{PACKAGE}.formatters", f"{PACKAGE}.schema.lint.engine"}
        assert anchors <= set(modules), (
            f"expected the protokit tree; missing {anchors - set(modules)}"
        )
        dangling = {t for targets in graph.values() for t in targets if t not in graph}
        assert not dangling, f"edges to names that are not modules in the tree: {dangling}"

    def test_deferred_imports_are_the_cycle_prevention_mechanism(
        self, graph: dict[str, set[str]]
    ) -> None:
        with_deferred = build_import_graph(_SRC_ROOT, PACKAGE, include_deferred=True)
        assert find_cycle(with_deferred) is not None, (
            "counting function-level imports no longer produces a cycle; the "
            "top-level-only rule is not being exercised by this tree"
        )
        for importer, imported in DEFERRED_EDGES:
            assert importer in graph and imported in graph, (
                f"{importer} or {imported} is no longer in the tree; update DEFERRED_EDGES"
            )
            assert imported not in graph[importer], (
                f"{importer} now imports {imported} at module load; that closes a "
                "cycle with the top-level import in the other direction"
            )
            assert imported in with_deferred[importer], (
                f"{importer} no longer imports {imported} anywhere; update "
                "DEFERRED_EDGES if the deferred import was removed on purpose"
            )
            assert importer in graph[imported], (
                f"{imported} no longer imports {importer} at module load; the pair "
                "is no longer a would-be cycle, update DEFERRED_EDGES"
            )

    def test_formatters_package_init_shape_is_present_and_not_a_cycle(
        self, graph: dict[str, set[str]]
    ) -> None:
        # ``formatters/__init__`` imports its ``_builtin_*`` submodules at top
        # level and each of those does ``from protokit.formatters import
        # <sibling>``. That resolves to the sibling module, never to the
        # package, so the shape is acyclic *because of* the submodule rule.
        package = f"{PACKAGE}.formatters"
        builtins = sorted(m for m in graph if m.startswith(f"{package}._builtin_"))
        assert builtins, "expected protokit.formatters._builtin_* modules in the tree"
        assert graph[package] & set(builtins), (
            "protokit.formatters no longer imports its _builtin_* submodules at "
            "module load; the package-init shape this test documents has moved"
        )
        back_edges = [m for m in builtins if package in graph[m]]
        assert not back_edges, (
            f"{back_edges} import the protokit.formatters package itself at module "
            "load — that is the genuine back-edge the submodule rule does not excuse"
        )

    def test_layer0_seam_modules_import_nothing_from_protokit(
        self, graph: dict[str, set[str]]
    ) -> None:
        violations = layer0_violations(graph, SEAM_MODULES)
        listing = "\n".join(
            f"  {seam} imports {', '.join(sorted(targets))}"
            for seam, targets in sorted(violations.items())
        )
        assert not violations, (
            f"layer-0 seam modules must import nothing from protokit (KTD8):\n{listing}"
        )


# ---------------------------------------------------------------------------
# KTD3: injected-violation self-tests over synthetic packages
# ---------------------------------------------------------------------------

_PKG = "pkg"


def _write_package(tmp_path: Path, files: Mapping[str, str]) -> Path:
    """Write ``files`` (path relative to ``src/pkg`` -> source) and return ``src``."""
    src = tmp_path / "src"
    for rel, source in files.items():
        path = src / _PKG / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    (src / _PKG / "__init__.py").touch()
    return src


def _cycle_of(tmp_path: Path, files: Mapping[str, str], **kwargs: bool) -> list[str] | None:
    return find_cycle(build_import_graph(_write_package(tmp_path, files), _PKG, **kwargs))


class TestImportLayersSelfCheck:
    def test_two_module_top_level_cycle_is_reported_with_both_names(self, tmp_path: Path) -> None:
        cycle = _cycle_of(tmp_path, {"_a.py": "import pkg._b\n", "_b.py": "import pkg._a\n"})
        assert cycle is not None
        assert cycle[0] == cycle[-1]
        assert set(cycle) == {"pkg._a", "pkg._b"}
        rendered = format_cycle(cycle)
        assert "pkg._a" in rendered and "pkg._b" in rendered

    def test_cycle_is_rendered_in_import_order(self, tmp_path: Path) -> None:
        src = _write_package(
            tmp_path,
            {"_a.py": "import pkg._b\n", "_b.py": "import pkg._c\n", "_c.py": "import pkg._a\n"},
        )
        graph = build_import_graph(src, _PKG)
        cycle = find_cycle(graph)
        assert cycle is not None and len(cycle) == 4
        for importer, imported in pairwise(cycle):
            assert imported in graph[importer], f"{importer} does not import {imported}"

    def test_from_import_of_a_submodule_cycle_is_reported(self, tmp_path: Path) -> None:
        cycle = _cycle_of(
            tmp_path, {"_a.py": "from pkg import _b\n", "_b.py": "from pkg import _a\n"}
        )
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_from_module_import_name_cycle_is_reported(self, tmp_path: Path) -> None:
        cycle = _cycle_of(
            tmp_path,
            {"_a.py": "from pkg._b import y\nx = 1\n", "_b.py": "from pkg._a import x\ny = 2\n"},
        )
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_package_init_importing_its_own_submodules_is_not_a_cycle(self, tmp_path: Path) -> None:
        # The protokit.formatters shape: __init__ imports the submodules; a
        # submodule does ``from pkg import <sibling>``.
        assert (
            _cycle_of(
                tmp_path,
                {
                    "__init__.py": "from pkg import _a\nfrom pkg import _b\n",
                    "_a.py": "from pkg import _b as sibling\n",
                    "_b.py": "",
                },
            )
            is None
        )

    def test_submodule_importing_its_own_package_is_a_cycle(self, tmp_path: Path) -> None:
        # Same shape, with a genuine back-edge: ``import pkg`` from a submodule
        # that ``pkg/__init__`` imports at module load.
        cycle = _cycle_of(
            tmp_path,
            {"__init__.py": "from pkg import _a\n", "_a.py": "import pkg\n"},
        )
        assert cycle is not None and set(cycle) == {"pkg", "pkg._a"}

    def test_from_package_import_attribute_is_an_edge_to_the_package(self, tmp_path: Path) -> None:
        # ``from pkg import X`` where X is a name bound by ``pkg/__init__``, not
        # a module: that needs the package body to have run, so it is an edge
        # to the package — and here closes a cycle with the __init__ import.
        cycle = _cycle_of(
            tmp_path,
            {"__init__.py": "from pkg import _a\nX = 1\n", "_a.py": "from pkg import X\n"},
        )
        assert cycle is not None and set(cycle) == {"pkg", "pkg._a"}

    def test_siblings_importing_each_other_under_the_init_shape_is_a_cycle(
        self, tmp_path: Path
    ) -> None:
        cycle = _cycle_of(
            tmp_path,
            {
                "__init__.py": "from pkg import _a\nfrom pkg import _b\n",
                "_a.py": "from pkg import _b\n",
                "_b.py": "from pkg import _a\n",
            },
        )
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_function_level_import_is_not_an_edge(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": "def f():\n    import pkg._a\n"}
        assert _cycle_of(tmp_path, files) is None
        assert _cycle_of(tmp_path, files, include_deferred=True) is not None

    def test_method_body_import_is_not_an_edge(self, tmp_path: Path) -> None:
        files = {
            "_a.py": "import pkg._b\n",
            "_b.py": "class C:\n    def m(self):\n        import pkg._a\n",
        }
        assert _cycle_of(tmp_path, files) is None

    @pytest.mark.parametrize(
        "guard",
        [
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n",
            "import typing\nif typing.TYPE_CHECKING:\n",
            "import typing as t\nif t.TYPE_CHECKING:\n",
        ],
        ids=["name", "attribute", "aliased-attribute"],
    )
    def test_type_checking_import_is_not_an_edge(self, tmp_path: Path, guard: str) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": guard + "    from pkg._a import A\n"}
        assert _cycle_of(tmp_path, files) is None
        assert _cycle_of(tmp_path, files, include_deferred=True) is None

    def test_else_branch_of_a_type_checking_block_is_an_edge(self, tmp_path: Path) -> None:
        files = {
            "_a.py": "import pkg._b\n",
            "_b.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    pass\nelse:\n"
            "    import pkg._a\n",
        }
        cycle = _cycle_of(tmp_path, files)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_plain_if_block_import_is_an_edge(self, tmp_path: Path) -> None:
        files = {
            "_a.py": "import pkg._b\n",
            "_b.py": "import sys\nif sys.version_info >= (3, 10):\n    import pkg._a\n",
        }
        cycle = _cycle_of(tmp_path, files)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_try_block_import_is_an_edge(self, tmp_path: Path) -> None:
        files = {
            "_a.py": "import pkg._b\n",
            "_b.py": "try:\n    import pkg._a\nexcept ImportError:\n    pass\n",
        }
        cycle = _cycle_of(tmp_path, files)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_class_body_import_is_an_edge(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": "class C:\n    import pkg._a\n"}
        cycle = _cycle_of(tmp_path, files)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_relative_imports_resolve_against_the_importer_package(self, tmp_path: Path) -> None:
        files = {
            "_a.py": "from . import _b\n",
            "_b.py": "from .sub import _c\n",
            "sub/__init__.py": "",
            "sub/_c.py": "from .._a import x\n",
        }
        src = _write_package(tmp_path, files)
        graph = build_import_graph(src, _PKG)
        assert graph["pkg._a"] == {"pkg._b"}
        assert graph["pkg._b"] == {"pkg.sub._c"}
        assert graph["pkg.sub._c"] == {"pkg._a"}
        cycle = find_cycle(graph)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b", "pkg.sub._c"}

    def test_dotted_import_is_an_edge_to_exactly_that_module(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg.sub._c\n", "sub/__init__.py": "", "sub/_c.py": ""}
        graph = build_import_graph(_write_package(tmp_path, files), _PKG)
        assert graph["pkg._a"] == {"pkg.sub._c"}

    def test_self_import_is_not_an_edge(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg._a\nfrom pkg import _a\n"}
        graph = build_import_graph(_write_package(tmp_path, files), _PKG)
        assert graph["pkg._a"] == set()
        assert find_cycle(graph) is None

    def test_imports_outside_the_package_are_ignored(self, tmp_path: Path) -> None:
        # ``pkgutil`` shares the package's prefix: a startswith check without
        # the dot would count it.
        files = {"_a.py": "import os\nimport pkgutil\nfrom collections import abc\n"}
        graph = build_import_graph(_write_package(tmp_path, files), _PKG)
        assert graph["pkg._a"] == set()

    def test_every_module_in_the_tree_is_a_node(self, tmp_path: Path) -> None:
        files = {"_a.py": "", "sub/__init__.py": "", "sub/_c.py": ""}
        src = _write_package(tmp_path, files)
        assert set(discover_modules(src, _PKG)) == {"pkg", "pkg._a", "pkg.sub", "pkg.sub._c"}
        assert set(build_import_graph(src, _PKG)) == {"pkg", "pkg._a", "pkg.sub", "pkg.sub._c"}

    def test_layer0_violation_names_the_seam_and_what_it_imports(self, tmp_path: Path) -> None:
        files = {
            "_seam.py": "import os\nimport pkg._a\nfrom pkg import _b\n",
            "_a.py": "",
            "_b.py": "",
        }
        graph = build_import_graph(_write_package(tmp_path, files), _PKG)
        assert layer0_violations(graph, ["pkg._seam"]) == {"pkg._seam": {"pkg._a", "pkg._b"}}

    def test_layer0_passes_on_a_seam_importing_only_the_stdlib(self, tmp_path: Path) -> None:
        files = {"_seam.py": "import os\nfrom pathlib import Path\n", "_a.py": "import pkg._seam\n"}
        graph = build_import_graph(_write_package(tmp_path, files), _PKG)
        assert layer0_violations(graph, ["pkg._seam"]) == {}

    def test_layer0_passes_with_an_empty_seam_list(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": ""}
        graph = build_import_graph(_write_package(tmp_path, files), _PKG)
        assert layer0_violations(graph, []) == {}

    def test_layer0_skips_seams_absent_from_the_tree(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": ""}
        graph = build_import_graph(_write_package(tmp_path, files), _PKG)
        assert layer0_violations(graph, ["pkg._not_yet"]) == {}
