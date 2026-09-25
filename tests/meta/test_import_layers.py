"""Import-layer meta test: ``protokit`` has zero module-load import cycles (U21, KTD8).

Every Wave B unit of the 0.16.0 correctness programme hoists shared logic into
a layer-0 seam module (``_fieldview``, ``_extensions``, ``_records``,
``_trust``, ``_atomic``, ``schema/_git_cmd``) that the rest of the package
imports. That is safe only while the package's import graph stays acyclic at
module-load time and the seams themselves import nothing from ``protokit``.
This test commits both properties as a gate, so a seam PR is checked by CI
rather than by an audit-time script. Zero is the measured count under the
rules below; the one cycle an earlier audit reported in ``protokit.formatters``
is the package-initialisation shape the second rule excludes.

What counts as an edge — the load-bearing rules:

* **Only imports executed at module load.** An import inside a function body
  is deferred, and in this codebase deferred imports exist precisely to break
  a load-time cycle (``schema/profiles.py`` imports ``schema.checker`` inside
  a method; ``message/pytest_plugin.py`` imports ``message.matchers`` inside a
  method, ``ProtoMatcherFactory.__call__``), so counting them would report
  the cycles they prevent. An import under ``if TYPE_CHECKING:`` never
  executes and is excluded; that block's ``else`` branch, a ``try``/``except``
  arm, a plain ``if``, and a class body all run at import time and count. The
  guard is recognised by its ``typing`` binding, not its spelling: a name
  bound by ``from typing import TYPE_CHECKING [as X]`` (``typing_extensions``
  counts too), or the ``TYPE_CHECKING`` attribute of a name bound by ``import
  typing [as T]``. Both bindings are read off module-scope statements only,
  and a name the module rebinds or deletes at module scope — or binds only
  inside a function — is not a guard, because the flag the ``if`` tests is
  then not ``typing``'s. The negated form ``if not TYPE_CHECKING:`` counts
  its body and skips its ``else``. Any other test — a compound one such as
  ``TYPE_CHECKING or X``, or ``TYPE_CHECKING`` on some other receiver — is a
  plain ``if`` and both arms are entered: at worst a false positive, never a
  missed edge.
* **``from <pkg> import <name>`` is an edge to the submodule ``<pkg>.<name>``
  when that is a module in the tree, and to ``<pkg>`` otherwise.** A package
  ``__init__`` that imports its own submodules, which in turn do ``from <pkg>
  import <sibling>``, is the ``protokit.formatters`` shape. Under the rule the
  interpreter follows (``<pkg>/__init__`` runs before ``<pkg>.<name>``) that
  shape is a five-module strongly connected component; it is a
  package-initialisation artefact, not a load-order hazard, and this rule
  excludes it. A ``from <pkg> import <attr>`` where ``<attr>`` is *not* a
  module is treated as a load-order dependency on ``<pkg>`` regardless of
  where ``<pkg>/__init__`` binds the name.
* **``import <mod>`` is an edge to exactly ``<mod>``**, whoever the importer's
  parent package is — a submodule importing its own package is not exempt.
* **An import of ``a.b.c`` also depends on every package on that path the
  importer does not itself live under** — CPython initialises ``a`` and
  ``a.b`` before ``a.b.c``, so the importer's load can trigger those
  ``__init__`` modules, and the edge is counted like a plain import of each.
  That over-approximates on purpose: ``import a.b`` needs ``a`` only to have
  *started* initialising, so the rule also reports a cycle through a
  package's ``__init__`` where the interpreter would tolerate the partially
  initialised package — a self-test pins one such call as deliberate. The
  rule stays because the failures it does catch are real load-order
  failures, and dropping it reopens them. Packages the importer lives under
  are already initialising or initialised; those are the
  package-initialisation artefact the ``from <pkg> import <name>`` rule
  excludes.
* A module's import of itself is not an edge.

Outside the edge model: an import executed through a call at module load
(a ``register()`` whose body imports), ``importlib.import_module`` /
``__import__`` strings, module ``__getattr__``, compiled extension modules,
and whatever a ``from <pkg> import *`` pulls in through ``<pkg>.__all__``
(the star itself is an edge to the module named, but a submodule that
``__all__`` re-exports is invisible). None of these occurs *at module load*
in the tree: the three ``importlib.import_module`` call sites
(``_cli_utils.py``, ``schema/cli.py``, ``schema/lint/_cli_utils.py``) are
deferred plugin loading inside function bodies, and there are no star
imports at all. The fresh-interpreter sweep
(``test_every_module_imports_in_a_fresh_interpreter``) is the runtime
complement.

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
import importlib.util
import os
import subprocess
import sys
from collections.abc import Iterable, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_ROOT = _REPO_ROOT / "src"
PACKAGE = "protokit"

# Layer-0 seam modules the 0.16.0 plan introduces (KTD8). Each is asserted to
# import nothing from ``protokit`` at any scope once it exists in the tree:
# function-level imports count too, because a seam is cycle-free by depending
# on nothing above it, not by deferring the dependency. An import under
# ``if TYPE_CHECKING:`` is exempt because it never executes, and a seam's
# import of itself is discarded with every other self-import. A seam that
# lands as a package is checked with every module under it. A name absent
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

# The seams that have landed. Each Wave B unit adds its seam here when it
# lands: the pin makes every landing a deliberate one-line update, so a seam
# that landed cannot sit in the tree while this list says it has not — the
# absent-is-skipped rule above would otherwise pass over a typo'd seam name
# silently. It compares names already in SEAM_MODULES, so a seam that lands
# under a spelling SEAM_MODULES does not list goes into SEAM_MODULES first.
LANDED_SEAMS: frozenset[str] = frozenset({
    "protokit._extensions",
    "protokit._fieldview",
    "protokit._records",
    "protokit._trust",
})

# Function-level imports that exist to break a load-time cycle: the named
# importer's *runtime* imports of the named module occur only inside function
# bodies (a typing-only import of the same module may also exist), while the
# reverse direction is a top-level import, so hoisting either of these to
# module scope closes a cycle. Pinned so the top-level-only rule is proven on
# the real tree — each edge is absent from the load-time graph and present
# once deferred imports are counted — rather than only on synthetic packages.
DEFERRED_EDGES = (
    ("protokit.schema.profiles", "protokit.schema.checker"),
    ("protokit.message.pytest_plugin", "protokit.message.matchers"),
)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

# Scopes whose body runs when called, not when the module loads.
_DEFERRED_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef)

# Modules whose ``TYPE_CHECKING`` is the type checker's flag.
_TYPING_MODULES = frozenset({"typing", "typing_extensions"})


def discover_modules(src_root: Path, package: str) -> dict[str, Path]:
    """Dotted module name -> source file for every ``.py`` under ``src_root/package``."""
    modules: dict[str, Path] = {}
    for path in sorted((src_root / package).rglob("*.py")):
        parts = path.relative_to(src_root).with_suffix("").parts
        if path.stem == "__init__":
            parts = parts[:-1]
        modules[".".join(parts)] = path
    return modules


def directories_without_an_init(package_root: Path) -> list[str]:
    """Directories of the package tree, ``package_root`` included, that are not packages.

    Every directory is examined, not only the parents of ``.py`` files: a
    directory holding nothing but subdirectories is still resolved on the way
    to what is under it, so it is a namespace package just the same.
    """
    directories = [package_root]
    directories.extend(
        path
        for path in package_root.rglob("*")
        if path.is_dir() and "__pycache__" not in path.relative_to(package_root).parts
    )
    return sorted(
        str(directory.relative_to(package_root.parent))
        for directory in directories
        if not (directory / "__init__.py").is_file()
    )


def _in_package(name: str, package: str) -> bool:
    return name == package or name.startswith(package + ".")


def _prefixes(dotted: str) -> list[str]:
    """``"a.b.c"`` -> ``["a", "a.b", "a.b.c"]``."""
    parts = dotted.split(".")
    return [".".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _module_scope_nodes(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    """``nodes`` and every descendant that belongs to the module's own namespace.

    A compound statement is entered, because its body runs as the module
    loads. A ``def``, ``async def``, ``class`` or ``lambda`` is yielded but
    not entered: it is a namespace of its own, so what its body binds is
    invisible at module scope — which is why a ``TYPE_CHECKING`` imported
    inside a function is not this module's guard.
    """
    for node in nodes:
        yield node
        if isinstance(node, (*_DEFERRED_SCOPES, ast.ClassDef, ast.Lambda)):
            continue
        yield from _module_scope_nodes(ast.iter_child_nodes(node))


def _rebound_at_module_scope(tree: ast.Module) -> set[str]:
    """Names the module binds or deletes at module scope other than by a typing import.

    Every binding form is covered by the store/delete contexts the walk sees
    (assignment, unpacking, augmented and annotated targets, ``for``,
    ``with``, ``:=``) plus the ones that spell the name as a string (``def``,
    ``class``, ``except ... as``, a ``match`` capture, an import alias). Only
    the ``TYPE_CHECKING`` an import binds *from a typing module* is left out,
    because that is the binding the guard is read from.

    The set is allowed to be too large — a comprehension target does not
    really leak into module scope, and ``global`` is counted wherever it is
    declared — because dropping a guard name only ever costs a false
    positive, while keeping one that is no longer typing's flag would skip an
    import CPython executes.
    """
    rebound: set[str] = set()
    for node in _module_scope_nodes(tree.body):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            rebound.add(node.id)
        elif isinstance(node, (*_DEFERRED_SCOPES, ast.ClassDef)):
            rebound.add(node.name)
        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            if node.name is not None:
                rebound.add(node.name)
        elif isinstance(node, ast.MatchMapping):
            if node.rest is not None:
                rebound.add(node.rest)
        elif isinstance(node, ast.Import):
            rebound.update(
                alias.asname or alias.name.partition(".")[0]
                for alias in node.names
                if alias.name not in _TYPING_MODULES
            )
        elif isinstance(node, ast.ImportFrom):
            from_typing = node.level == 0 and node.module in _TYPING_MODULES
            rebound.update(
                alias.asname or alias.name
                for alias in node.names
                if not (from_typing and alias.name == "TYPE_CHECKING")
            )
    # ``global X`` binds a module-level name from inside a body the walk
    # above does not enter, and a module-load call can run that body.
    for node in ast.walk(tree):
        if isinstance(node, ast.Global):
            rebound.update(node.names)
    return rebound


@dataclass(frozen=True)
class _TypeCheckingGuards:
    """How one module spells ``typing.TYPE_CHECKING``, read off its own bindings.

    ``names`` are bound by ``from typing import TYPE_CHECKING [as X]`` and
    ``typing_modules`` by ``import typing [as T]`` (``typing_extensions``
    counts for both). Recognising the guard by binding rather than by
    spelling means ``Flags.TYPE_CHECKING`` on some other receiver is a plain
    ``if`` — entered, so at worst a false positive.

    Only module-scope bindings register, and a name the module rebinds or
    deletes is dropped: ``TYPE_CHECKING = True`` after the import, or a
    ``TYPE_CHECKING`` imported inside a function, leaves an ``if`` whose body
    CPython executes, and skipping that body would be a missed edge rather
    than a false positive.
    """

    names: frozenset[str]
    typing_modules: frozenset[str]

    @classmethod
    def from_module(cls, tree: ast.Module) -> _TypeCheckingGuards:
        names: set[str] = set()
        typing_modules: set[str] = set()
        for node in _module_scope_nodes(tree.body):
            if isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module in _TYPING_MODULES:
                    names.update(
                        alias.asname or alias.name
                        for alias in node.names
                        if alias.name == "TYPE_CHECKING"
                    )
            elif isinstance(node, ast.Import):
                typing_modules.update(
                    alias.asname or alias.name
                    for alias in node.names
                    if alias.name in _TYPING_MODULES
                )
        rebound = _rebound_at_module_scope(tree)
        return cls(
            names=frozenset(names - rebound),
            typing_modules=frozenset(typing_modules - rebound),
        )

    def is_guard(self, test: ast.expr) -> bool:
        """``TYPE_CHECKING`` or ``typing.TYPE_CHECKING`` under this module's bindings."""
        if isinstance(test, ast.Name):
            return test.id in self.names
        return (
            isinstance(test, ast.Attribute)
            and test.attr == "TYPE_CHECKING"
            and isinstance(test.value, ast.Name)
            and test.value.id in self.typing_modules
        )

    def is_negated_guard(self, test: ast.expr) -> bool:
        """``not <guard>``: the body runs at module load and the ``else`` never does."""
        return (
            isinstance(test, ast.UnaryOp)
            and isinstance(test.op, ast.Not)
            and self.is_guard(test.operand)
        )


def _executed_imports(
    nodes: Iterable[ast.AST], guards: _TypeCheckingGuards, *, include_deferred: bool
) -> Iterator[ast.Import | ast.ImportFrom]:
    """Import statements among ``nodes``, recursively, that run at module load.

    A function body is skipped unless ``include_deferred``. The body of an
    ``if TYPE_CHECKING:`` block is always skipped and its ``else`` branch
    walked; ``if not TYPE_CHECKING:`` is the mirror image. Every other
    compound statement (``if``, ``try``, ``with``, ``for``, ``match``,
    ``class``) is entered, because its body executes as the module loads.
    """
    for node in nodes:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            yield node
        elif isinstance(node, _DEFERRED_SCOPES) and not include_deferred:
            continue
        elif isinstance(node, ast.If) and guards.is_guard(node.test):
            yield from _executed_imports(node.orelse, guards, include_deferred=include_deferred)
        elif isinstance(node, ast.If) and guards.is_negated_guard(node.test):
            yield from _executed_imports(node.body, guards, include_deferred=include_deferred)
        else:
            yield from _executed_imports(
                ast.iter_child_nodes(node), guards, include_deferred=include_deferred
            )


def _import_targets(
    importer_package: str,
    node: ast.Import | ast.ImportFrom,
    modules: Mapping[str, Path],
    package: str,
    *,
    importer: str,
    path: Path,
) -> set[str]:
    """The package modules ``node`` is an edge to, under the rules in the docstring.

    ``importer_package`` is the importer's ``__package__`` — the module itself
    for a package ``__init__``, its parent otherwise — which is what a relative
    ``from`` level resolves against. ``importer`` and ``path`` name the source
    only in the error below.
    """
    if isinstance(node, ast.Import):
        return {alias.name for alias in node.names if _in_package(alias.name, package)}
    relative = "." * node.level + (node.module or "")
    try:
        base = importlib.util.resolve_name(relative, importer_package)
    except ImportError as exc:
        # A ``from`` that climbs past the top-level package: ``resolve_name``
        # raises, and an uncaught raise out of the graph build errors every
        # gate test with a traceback that names no source file. The
        # fresh-interpreter sweep owns the verdict on whether such a module
        # loads; the gate only has to say which one it is.
        raise ImportError(
            f"{importer} ({path}): `from {relative} import ...` does not resolve "
            f"inside package {importer_package!r} ({exc})"
        ) from exc
    if not _in_package(base, package):
        return set()
    targets: set[str] = set()
    for alias in node.names:
        submodule = f"{base}.{alias.name}"
        targets.add(submodule if submodule in modules else base)
    return targets


def _packages_on_path(target: str, importer_package: str, modules: Mapping[str, Path]) -> set[str]:
    """Packages initialised on the way to ``target`` that the importer does not live under.

    ``import a.b.c`` runs ``a/__init__`` and ``a/b/__init__`` before ``a/b/c``,
    so each package on the path is a load-order dependency of the importer —
    except the importer's own package and its ancestors, which are already
    initialising or initialised by the time the importer runs.
    """
    own_packages = set(_prefixes(importer_package))
    return {
        prefix
        for prefix in _prefixes(target)[:-1]
        if prefix in modules and prefix not in own_packages
    }


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
        # Parsed from bytes so a BOM or a PEP 263 coding cookie the
        # interpreter accepts does not error the gate.
        tree = ast.parse(path.read_bytes(), filename=str(path))
        guards = _TypeCheckingGuards.from_module(tree)
        importer_package = name if path.stem == "__init__" else name.rpartition(".")[0]
        targets: set[str] = set()
        for node in _executed_imports(tree.body, guards, include_deferred=include_deferred):
            for target in _import_targets(
                importer_package, node, modules, package, importer=name, path=path
            ):
                targets.add(target)
                targets |= _packages_on_path(target, importer_package, modules)
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


def _under_seam(module: str, seams: Iterable[str]) -> bool:
    return any(module == seam or module.startswith(seam + ".") for seam in seams)


def layer0_violations(graph: Mapping[str, set[str]], seams: Iterable[str]) -> dict[str, set[str]]:
    """``module -> {package modules it imports}`` for every seam module in ``graph``.

    A seam that landed as a package is checked with every module under it. A
    seam absent from the graph has not landed yet and is skipped.
    """
    seams = tuple(seams)
    return {
        module: set(targets)
        for module, targets in graph.items()
        if targets and _under_seam(module, seams)
    }


# ---------------------------------------------------------------------------
# Runtime complement
# ---------------------------------------------------------------------------


# One import of one module, generously: the whole sweep of the tree runs in
# about a second locally, so anything near this is a module that blocks (an
# input read, a socket) rather than a slow machine. Without the bound a
# blocked import stalls the suite until the CI job cap, naming no module.
FRESH_IMPORT_TIMEOUT_SECONDS = 120.0


def import_in_fresh_interpreter(
    module: str, *, src_root: Path, cwd: Path, timeout: float = FRESH_IMPORT_TIMEOUT_SECONDS
) -> subprocess.CompletedProcess[str]:
    """``import <module>`` in a fresh interpreter that finds it through ``src_root`` alone.

    ``PYTHONSAFEPATH`` keeps ``cwd`` off ``sys.path`` (3.11+; an older
    interpreter ignores it). The caller reads ``returncode`` and ``stderr``,
    and handles the ``TimeoutExpired`` an import that never returns raises.
    """
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        cwd=cwd,
        env={**os.environ, "PYTHONPATH": str(src_root), "PYTHONSAFEPATH": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _timed_out(module: str, exc: subprocess.TimeoutExpired) -> subprocess.CompletedProcess[str]:
    """A failure record standing in for an import that never returned.

    The sweep reports it like any other failing module, so the timeout stays
    inside pytest's report instead of taking the job down with it.
    """
    return subprocess.CompletedProcess(
        args=exc.cmd,
        returncode=1,
        stdout="",
        stderr=(
            f"`import {module}` did not finish within {exc.timeout:.0f}s and was "
            "killed, so there is no traceback: the import blocks"
        ),
    )


def _stderr_tail(result: subprocess.CompletedProcess[str], lines: int = 3) -> str:
    return "\n".join(f"    {line}" for line in result.stderr.strip().splitlines()[-lines:])


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def graph() -> dict[str, set[str]]:
    return build_import_graph(_SRC_ROOT, PACKAGE)


@pytest.fixture(scope="module")
def graph_with_deferred() -> dict[str, set[str]]:
    return build_import_graph(_SRC_ROOT, PACKAGE, include_deferred=True)


class TestImportLayers:
    def test_protokit_has_no_module_load_import_cycles(self, graph: dict[str, set[str]]) -> None:
        cycle = find_cycle(graph)
        assert cycle is None, (
            "protokit has a module-load import cycle (KTD8):\n"
            f"  {' -> '.join(cycle)}\n"
            "(-> reads 'imports at module load'. The sanctioned breaks: an "
            "annotation-only import goes under `if TYPE_CHECKING:`; a runtime "
            "import moves into the function that needs it — never into a "
            "containment `except` arm; a from-import of a package attribute is "
            "rewritten to import from the submodule that defines it. An edge to "
            "a package can come from importing a module beneath it — `import "
            "a.b.c` initialises `a.b` first — so a package can appear in a cycle "
            "that no module imports by name. See this module's docstring.)"
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
        anchors = {PACKAGE, f"{PACKAGE}.formatters", f"{PACKAGE}.schema.lint"}
        assert anchors <= set(modules), (
            f"expected the protokit tree; missing {anchors - set(modules)}"
        )
        dangling = {t for targets in graph.values() for t in targets if t not in graph}
        assert not dangling, f"edges to names that are not modules in the tree: {dangling}"

    def test_every_package_directory_has_an_init(self) -> None:
        # A directory of ``.py`` files without an ``__init__.py`` is a
        # namespace package: an import target with no source file, so no node
        # in the graph — which breaks the one-node-per-file invariant the
        # cycle assertion relies on. A directory holding only subdirectories
        # is checked too: ``pkg/ns/inner`` resolves ``pkg.ns`` on the way in.
        missing = directories_without_an_init(_SRC_ROOT / PACKAGE)
        assert not missing, f"package directories without an __init__.py: {missing}"

    def test_deferred_imports_are_the_cycle_prevention_mechanism(
        self, graph: dict[str, set[str]], graph_with_deferred: dict[str, set[str]]
    ) -> None:
        for importer, imported in DEFERRED_EDGES:
            assert importer in graph and imported in graph, (
                f"{importer} or {imported} is no longer in the tree; update DEFERRED_EDGES"
            )
            assert imported not in graph[importer], (
                f"{importer} now imports {imported} at module load; that closes a "
                "cycle with the top-level import in the other direction"
            )
            assert imported in graph_with_deferred[importer], (
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
        self, graph_with_deferred: dict[str, set[str]]
    ) -> None:
        violations = layer0_violations(graph_with_deferred, SEAM_MODULES)
        listing = "\n".join(
            f"  {module} imports {', '.join(sorted(targets))}"
            for module, targets in sorted(violations.items())
        )
        assert not violations, (
            "layer-0 seam modules must import nothing from protokit at any scope "
            f"(KTD8):\n{listing}"
        )

    def test_landed_seams_pin_matches_the_tree(self, graph: dict[str, set[str]]) -> None:
        landed = {seam for seam in SEAM_MODULES if seam in graph}
        assert landed == LANDED_SEAMS, (
            f"seams in the tree {sorted(landed)} != LANDED_SEAMS {sorted(LANDED_SEAMS)}; "
            "a Wave B landing updates LANDED_SEAMS in the same PR (a seam that landed "
            "under another spelling goes into SEAM_MODULES first)"
        )

    def test_every_module_imports_in_a_fresh_interpreter(self) -> None:
        # The interpreter-level truth the static gate approximates: this
        # catches a load-time failure the edge model cannot see (an import
        # executed through a module-level call, an ``importlib`` string) and
        # inherits the CI cell's protobuf backend through the environment.
        modules = sorted(discover_modules(_SRC_ROOT, PACKAGE))
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {
                module: pool.submit(
                    import_in_fresh_interpreter, module, src_root=_SRC_ROOT, cwd=_REPO_ROOT
                )
                for module in modules
            }
        results: dict[str, subprocess.CompletedProcess[str]] = {}
        for module, future in futures.items():
            try:
                results[module] = future.result()
            except subprocess.TimeoutExpired as exc:
                results[module] = _timed_out(module, exc)
        failures = {module: result for module, result in results.items() if result.returncode}
        listing = "\n".join(
            f"  {module}:\n{_stderr_tail(result)}" for module, result in sorted(failures.items())
        )
        assert not failures, f"modules that fail to import in a fresh interpreter:\n{listing}"


# ---------------------------------------------------------------------------
# KTD3: injected-violation self-tests over synthetic packages
# ---------------------------------------------------------------------------


def _write_package(
    tmp_path: Path, files: Mapping[str, str], *, raw: Mapping[str, bytes] | None = None
) -> Path:
    """Write ``files`` (path relative to ``src/pkg`` -> source) and return ``src``.

    ``raw`` writes the same way from bytes, for a source whose encoding is
    the point of the test rather than the text it decodes to.
    """
    src = tmp_path / "src"
    for rel, source in files.items():
        path = src / "pkg" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
    for rel, data in (raw or {}).items():
        path = src / "pkg" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    # ``touch`` creates the root ``__init__`` only when ``files`` did not; an
    # explicit one keeps its content.
    (src / "pkg" / "__init__.py").touch()
    return src


def _graph_of(
    tmp_path: Path, files: Mapping[str, str], *, include_deferred: bool = False
) -> dict[str, set[str]]:
    src = _write_package(tmp_path, files)
    return build_import_graph(src, "pkg", include_deferred=include_deferred)


def _cycle_of(
    tmp_path: Path, files: Mapping[str, str], *, include_deferred: bool = False
) -> list[str] | None:
    return find_cycle(_graph_of(tmp_path, files, include_deferred=include_deferred))


def _fresh_import_of(tmp_path: Path, module: str) -> subprocess.CompletedProcess[str]:
    """Import ``module`` from the package ``_write_package`` wrote under ``tmp_path``."""
    return import_in_fresh_interpreter(module, src_root=tmp_path / "src", cwd=tmp_path)


# Shapes on which the interpreter's verdict is loud, so the gate's can be
# checked against it (``test_gate_verdict_agrees_with_the_interpreter``).
_NON_ANCESTOR_PACKAGE_CYCLE = {
    "_a.py": "import pkg.sub._c\nX = 1\n",
    "sub/__init__.py": "from pkg._a import X\n",
    "sub/_c.py": "",
}
_FROM_NAME_CYCLE = {
    "_a.py": "from pkg._b import y\nx = 1\n",
    "_b.py": "from pkg._a import x\ny = 2\n",
}
# The protokit.formatters shape: __init__ imports the submodules; a submodule
# does ``from pkg import <sibling>``.
_PACKAGE_INIT_SHAPE = {
    "__init__.py": "from pkg import _a\nfrom pkg import _b\n",
    "_a.py": "from pkg import _b as sibling\n",
    "_b.py": "",
}
# A guard name rebound at module scope: ``TYPE_CHECKING`` is the typing flag
# where the import binds it and ``True`` where the ``if`` reads it, so the
# block runs and the interpreter is loud about what it imports.
_REBOUND_GUARD_CYCLE = {
    "_a.py": "import pkg._b\nA = 1\n",
    "_b.py": "from typing import TYPE_CHECKING\nTYPE_CHECKING = True\n"
    "if TYPE_CHECKING:\n    from pkg._a import A\n",
}
# Two packages deep: the cycle closes through the grandparent ``__init__``,
# which only a rule that counts *every* package on the path can see.
_GRANDPARENT_PACKAGE_CYCLE = {
    "_a.py": "import pkg.x.y._z\nX = 1\n",
    "x/__init__.py": "from pkg._a import X\n",
    "x/y/__init__.py": "",
    "x/y/_z.py": "",
}
# The over-approximation the packages-on-path rule accepts: a cycle through a
# package ``__init__`` that the interpreter imports without complaint.
_SIBLING_PACKAGE_SHAPE = {
    "_a.py": "from pkg.sub import _c\n",
    "sub/__init__.py": "from pkg import _a\n",
    "sub/_c.py": "",
}


class TestImportLayersSelfCheck:
    def test_two_module_top_level_cycle_is_reported_with_both_names(self, tmp_path: Path) -> None:
        cycle = _cycle_of(tmp_path, {"_a.py": "import pkg._b\n", "_b.py": "import pkg._a\n"})
        assert cycle is not None
        assert cycle[0] == cycle[-1]
        assert set(cycle) == {"pkg._a", "pkg._b"}

    def test_cycle_is_rendered_in_import_order(self, tmp_path: Path) -> None:
        graph = _graph_of(
            tmp_path,
            {"_a.py": "import pkg._b\n", "_b.py": "import pkg._c\n", "_c.py": "import pkg._a\n"},
        )
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
        cycle = _cycle_of(tmp_path, _FROM_NAME_CYCLE)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_package_init_importing_its_own_submodules_is_not_a_cycle(self, tmp_path: Path) -> None:
        assert _cycle_of(tmp_path, _PACKAGE_INIT_SHAPE) is None

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

    def test_import_through_a_non_ancestor_package_init_is_a_cycle(self, tmp_path: Path) -> None:
        # ``pkg._a`` imports ``pkg.sub._c``, which initialises ``pkg.sub``
        # first — and ``pkg.sub`` needs a name ``pkg._a`` has not bound yet.
        cycle = _cycle_of(tmp_path, _NON_ANCESTOR_PACKAGE_CYCLE)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg.sub"}

    def test_import_through_a_grandparent_package_init_is_a_cycle(self, tmp_path: Path) -> None:
        # Depth pin: *every* package on the path counts, not just the
        # target's parent. The real tree imports this deep (``protokit.cli``
        # -> ``protokit.schema.lint.cli``), and a rule that stopped at the
        # immediate parent would miss the cycle that closes through
        # ``pkg.x/__init__`` entirely.
        graph = _graph_of(tmp_path, _GRANDPARENT_PACKAGE_CYCLE)
        assert graph["pkg._a"] == {"pkg.x", "pkg.x.y", "pkg.x.y._z"}
        cycle = find_cycle(graph)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg.x"}

    def test_cycle_through_a_sibling_package_init_is_a_deliberate_over_approximation(
        self, tmp_path: Path
    ) -> None:
        # The packages-on-path rule is fail-closed by construction, and this
        # is what that costs: the gate reports a cycle the interpreter
        # tolerates from every entry point, because ``from pkg.sub import
        # _c`` needs ``pkg`` only to have *started* initialising and
        # ``pkg.sub``'s ``from pkg import _a`` then finds the partially
        # initialised module in ``sys.modules``. Pinned rather than fixed:
        # dropping the rule to silence it reopens the real load-order failure
        # ``test_import_through_a_non_ancestor_package_init_is_a_cycle`` pins.
        cycle = _cycle_of(tmp_path, _SIBLING_PACKAGE_SHAPE)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg.sub"}
        for entry_point in ("pkg._a", "pkg.sub", "pkg.sub._c"):
            result = _fresh_import_of(tmp_path, entry_point)
            assert result.returncode == 0, f"import {entry_point}:\n{result.stderr}"

    @pytest.mark.parametrize(
        ("files", "gate_reports_a_cycle"),
        [
            (_NON_ANCESTOR_PACKAGE_CYCLE, True),
            (_GRANDPARENT_PACKAGE_CYCLE, True),
            (_REBOUND_GUARD_CYCLE, True),
            (_FROM_NAME_CYCLE, True),
            (_PACKAGE_INIT_SHAPE, False),
        ],
        ids=[
            "non-ancestor-package-init",
            "grandparent-package-init",
            "rebound-type-checking-guard",
            "from-name-cycle",
            "package-init-shape",
        ],
    )
    def test_gate_verdict_agrees_with_the_interpreter(
        self, tmp_path: Path, files: Mapping[str, str], gate_reports_a_cycle: bool
    ) -> None:
        # Ties the gate's verdict to ground truth on the shapes where the
        # interpreter is loud. A plain-import mutual cycle (``import pkg._b``
        # / ``import pkg._a``) does not raise at runtime — the half-initialised
        # module is simply bound — which is why the static gate exists.
        cycle = _cycle_of(tmp_path, files)
        result = _fresh_import_of(tmp_path, "pkg._a")
        if gate_reports_a_cycle:
            assert cycle is not None
            assert result.returncode != 0, "the interpreter accepted a cycle the gate reports"
            assert "partially initialized module" in result.stderr, result.stderr
        else:
            assert cycle is None
            assert result.returncode == 0, result.stderr

    def test_import_executed_through_a_module_level_call_is_outside_the_edge_model(
        self, tmp_path: Path
    ) -> None:
        # A documented boundary of the static gate: the walk is syntactic and
        # a call is not an import statement, so the import ``register()``
        # executes at module load is invisible here while the interpreter
        # fails on it. ``test_every_module_imports_in_a_fresh_interpreter`` is
        # the runtime complement; extending the walker to follow module-level
        # calls updates this pin.
        files = {
            "_a.py": "import pkg._b\nX = 1\n",
            "_b.py": "def register():\n    from pkg._a import X\n\n\nregister()\n",
        }
        assert _cycle_of(tmp_path, files) is None
        result = _fresh_import_of(tmp_path, "pkg._a")
        assert result.returncode != 0, "the interpreter accepted the call-executed import"
        assert "partially initialized module" in result.stderr, result.stderr

    def test_an_import_that_never_returns_becomes_a_named_failure(self, tmp_path: Path) -> None:
        # Without the wall-clock bound a module that blocks on load (a read,
        # a socket) stalls the sweep until the CI job cap and names nothing.
        # A short timeout here stands in for the generous one the sweep uses;
        # what is pinned is that the bound exists and that the sweep turns it
        # into an ordinary failure row rather than an error that takes the
        # whole run down.
        _write_package(tmp_path, {"_a.py": "import time\n\ntime.sleep(30)\n"})
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            import_in_fresh_interpreter(
                "pkg._a", src_root=tmp_path / "src", cwd=tmp_path, timeout=0.5
            )
        result = _timed_out("pkg._a", caught.value)
        assert result.returncode != 0
        assert "did not finish" in result.stderr and "pkg._a" in result.stderr

    @pytest.mark.parametrize(
        "source",
        [
            "def f():\n    import pkg._a\n",
            "async def f():\n    import pkg._a\n",
            "class C:\n    def m(self):\n        import pkg._a\n",
            "class C:\n    @staticmethod\n    def s():\n        import pkg._a\n",
            "def outer():\n    def inner():\n        import pkg._a\n",
        ],
        ids=["def", "async-def", "method", "static-method", "nested-def"],
    )
    def test_import_in_a_deferred_scope_is_not_an_edge(self, tmp_path: Path, source: str) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": source}
        assert _cycle_of(tmp_path, files) is None
        cycle = _cycle_of(tmp_path, files, include_deferred=True)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    @pytest.mark.parametrize(
        "guard",
        [
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n",
            "import typing\nif typing.TYPE_CHECKING:\n",
            "import typing as t\nif t.TYPE_CHECKING:\n",
            "from typing import TYPE_CHECKING as TC\nif TC:\n",
            "from typing_extensions import TYPE_CHECKING\nif TYPE_CHECKING:\n",
            "import typing_extensions as te\nif te.TYPE_CHECKING:\n",
        ],
        ids=[
            "name",
            "attribute",
            "aliased-attribute",
            "aliased-name",
            "typing-extensions",
            "typing-extensions-attribute",
        ],
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

    @pytest.mark.parametrize(
        ("source", "expect_cycle"),
        [
            ("if not TYPE_CHECKING:\n    import pkg._a\n", True),
            ("if not TYPE_CHECKING:\n    pass\nelse:\n    import pkg._a\n", False),
        ],
        ids=["body-is-counted", "else-is-excluded"],
    )
    def test_negated_type_checking_guard(
        self, tmp_path: Path, source: str, expect_cycle: bool
    ) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": "from typing import TYPE_CHECKING\n" + source}
        cycle = _cycle_of(tmp_path, files)
        if expect_cycle:
            assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}
        else:
            assert cycle is None

    @pytest.mark.parametrize(
        ("source", "extra_files"),
        [
            (
                "class Flags:\n    TYPE_CHECKING = True\n"
                "if Flags.TYPE_CHECKING:\n    import pkg._a\n",
                {},
            ),
            (
                "from typing import TYPE_CHECKING\nif TYPE_CHECKING or False:\n    import pkg._a\n",
                {},
            ),
            ("TYPE_CHECKING = False\nif TYPE_CHECKING:\n    import pkg._a\n", {}),
            (
                "from pkg import TYPE_CHECKING\nif TYPE_CHECKING:\n    import pkg._a\n",
                {"__init__.py": "from typing import TYPE_CHECKING\n"},
            ),
            ("HAS_X = False\nif not HAS_X:\n    import pkg._a\n", {}),
            ("HAS_X = False\nif not HAS_X:\n    pass\nelse:\n    import pkg._a\n", {}),
            (
                "from typing import TYPE_CHECKING as X\nX = True\n"
                "if X:\n    from pkg._a import A\n",
                {},
            ),
            (_REBOUND_GUARD_CYCLE["_b.py"], {}),
            (
                "def f():\n    from typing import TYPE_CHECKING\nTYPE_CHECKING = True\n"
                "if TYPE_CHECKING:\n    from pkg._a import A\n",
                {},
            ),
            (
                "def f():\n    from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n    import pkg._a\n",
                {},
            ),
        ],
        ids=[
            "non-typing-receiver",
            "compound-test",
            "no-typing-import",
            "re-exported-name",
            "negated-non-guard-body",
            "negated-non-guard-else",
            "rebound-alias",
            "rebound-name",
            "rebound-after-a-function-scope-import",
            "bound-only-inside-a-function",
        ],
    )
    def test_unrecognised_type_checking_spelling_is_counted(
        self, tmp_path: Path, source: str, extra_files: Mapping[str, str]
    ) -> None:
        # Fail-closed pin: a test the walker does not recognise as the guard
        # is a plain ``if`` and is entered — a false positive at worst, never
        # a missed edge. That covers a name that is not typing's flag at all
        # (never imported, re-exported by another module, negated when it is
        # not the guard) and one that has stopped being it by the time the
        # ``if`` runs (rebound at module scope, or bound only inside a
        # function, where the module-level ``if`` would read a name that is
        # not there at all). The interpreter agrees on the rebinding shapes —
        # ``test_gate_verdict_agrees_with_the_interpreter`` runs one of them.
        files = {"_a.py": "import pkg._b\n", "_b.py": source, **extra_files}
        cycle = _cycle_of(tmp_path, files)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    @pytest.mark.parametrize(
        "source",
        [
            "try:\n    import pkg._a\nexcept ImportError:\n    pass\n",
            "try:\n    import nonesuch_mod\nexcept ImportError:\n    import pkg._a\n",
            "try:\n    pass\nexcept ImportError:\n    pass\nelse:\n    import pkg._a\n",
            "try:\n    pass\nfinally:\n    import pkg._a\n",
            "import sys\nif sys.version_info >= (3, 10):\n    import pkg._a\n",
            "import sys\nif sys.version_info < (3, 10):\n    pass\nelse:\n    import pkg._a\n",
            "import sys\nif sys.version_info < (3, 10):\n    pass\nelif True:\n    import pkg._a\n",
            "import contextlib\nwith contextlib.nullcontext():\n    import pkg._a\n",
            "for _ in range(1):\n    import pkg._a\n",
            "while True:\n    import pkg._a\n    break\n",
            "match 1:\n    case _:\n        import pkg._a\n",
            "class C:\n    import pkg._a\n",
            "class C:\n    class D:\n        import pkg._a\n",
        ],
        ids=[
            "try-body",
            "except-arm",
            "try-else",
            "try-finally",
            "if-body",
            "if-else",
            "elif",
            "with",
            "for-body",
            "while-body",
            "match-arm",
            "class-body",
            "nested-class-body",
        ],
    )
    def test_import_in_a_load_time_compound_statement_is_an_edge(
        self, tmp_path: Path, source: str
    ) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": source}
        cycle = _cycle_of(tmp_path, files)
        assert cycle is not None and set(cycle) == {"pkg._a", "pkg._b"}

    def test_every_name_of_a_multi_name_import_is_an_edge(self, tmp_path: Path) -> None:
        files = {
            "_a.py": "import pkg._b, pkg._c\nfrom pkg import _d, _e\n",
            "_b.py": "",
            "_c.py": "",
            "_d.py": "",
            "_e.py": "",
        }
        graph = _graph_of(tmp_path, files)
        assert graph["pkg._a"] == {"pkg._b", "pkg._c", "pkg._d", "pkg._e"}

    def test_star_import_is_an_edge_to_the_module(self, tmp_path: Path) -> None:
        files = {"_a.py": "from pkg._b import *\n", "_b.py": ""}
        graph = _graph_of(tmp_path, files)
        assert graph["pkg._a"] == {"pkg._b"}

    def test_relative_imports_resolve_against_the_importer_package(self, tmp_path: Path) -> None:
        files = {
            "__init__.py": "from . import _a\n",
            "_a.py": "from . import _b\n",
            "_b.py": "from .sub import _c\n",
            "sub/__init__.py": "from . import _c\n",
            "sub/_c.py": "from .._a import x\n",
        }
        graph = _graph_of(tmp_path, files)
        assert graph["pkg"] == {"pkg._a"}
        assert graph["pkg._a"] == {"pkg._b"}
        assert graph["pkg._b"] == {"pkg.sub._c", "pkg.sub"}
        assert graph["pkg.sub"] == {"pkg.sub._c"}
        assert graph["pkg.sub._c"] == {"pkg._a"}
        # More than one cycle closes here (through ``pkg.sub._c`` directly and
        # through ``pkg.sub``); the exact sets are proven by the dedicated
        # cycle tests.
        assert find_cycle(graph) is not None

    def test_a_relative_import_beyond_the_top_level_names_the_importing_module(
        self, tmp_path: Path
    ) -> None:
        # ``resolve_name`` raises on a ``from`` that climbs past the
        # top-level package, and an uncaught raise out of the module-scoped
        # ``graph`` fixture errors every gate test with a traceback that
        # names no source. The gate's job here is to say which file.
        files = {"sub/__init__.py": "", "sub/_a.py": "from ... import x\n"}
        with pytest.raises(ImportError) as caught:
            _graph_of(tmp_path, files)
        assert "pkg.sub._a" in str(caught.value)
        assert "_a.py" in str(caught.value)

    def test_dotted_import_is_an_edge_to_the_module_and_the_non_ancestor_packages_on_its_path(
        self, tmp_path: Path
    ) -> None:
        files = {
            "_a.py": "import pkg.sub._c\n",
            "sub/__init__.py": "",
            "sub/_c.py": "",
            "sub/_d.py": "import pkg.sub._c\n",
        }
        graph = _graph_of(tmp_path, files)
        assert graph["pkg._a"] == {"pkg.sub._c", "pkg.sub"}
        # ``pkg.sub`` is ``pkg.sub._d``'s own package: already initialising.
        assert graph["pkg.sub._d"] == {"pkg.sub._c"}

    def test_self_import_is_not_an_edge(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg._a\nfrom pkg import _a\n"}
        graph = _graph_of(tmp_path, files)
        assert graph["pkg._a"] == set()
        assert find_cycle(graph) is None

    def test_imports_outside_the_package_are_ignored(self, tmp_path: Path) -> None:
        # ``pkgutil`` shares the package's prefix: a startswith check without
        # the dot would count it.
        files = {"_a.py": "import os\nimport pkgutil\nfrom collections import abc\n"}
        graph = _graph_of(tmp_path, files)
        assert graph["pkg._a"] == set()

    def test_every_module_in_the_tree_is_a_node(self, tmp_path: Path) -> None:
        files = {"_a.py": "", "sub/__init__.py": "", "sub/_c.py": ""}
        src = _write_package(tmp_path, files)
        assert set(discover_modules(src, "pkg")) == {"pkg", "pkg._a", "pkg.sub", "pkg.sub._c"}
        assert set(build_import_graph(src, "pkg")) == {"pkg", "pkg._a", "pkg.sub", "pkg.sub._c"}

    def test_sources_are_parsed_as_bytes_so_a_bom_or_a_coding_cookie_still_builds(
        self, tmp_path: Path
    ) -> None:
        # Both files import fine in the interpreter, and both defeat
        # ``read_text(encoding="utf-8")``: the BOM raises SyntaxError and the
        # latin-1 byte raises UnicodeDecodeError — erroring the whole gate on
        # a file whose imports are not the problem.
        src = _write_package(
            tmp_path,
            {"_b.py": ""},
            raw={
                "_bom.py": b"\xef\xbb\xbfimport pkg._b\n",
                "_cookie.py": b"# -*- coding: latin-1 -*-\nimport pkg._b\nX = '\xe9'\n",
            },
        )
        graph = build_import_graph(src, "pkg")
        assert graph["pkg._bom"] == {"pkg._b"}
        assert graph["pkg._cookie"] == {"pkg._b"}

    def test_a_directory_holding_only_subdirectories_is_named(self, tmp_path: Path) -> None:
        # ``pkg/ns`` holds no source of its own, so deriving directories from
        # the parents of ``.py`` files makes it invisible — while an import
        # of ``pkg.ns.inner`` still resolves ``pkg.ns`` as a namespace
        # package on the way in.
        src = _write_package(tmp_path, {"ns/inner/__init__.py": "", "ns/inner/_a.py": ""})
        assert directories_without_an_init(src / "pkg") == ["pkg/ns"]

    def test_layer0_violation_names_the_seam_and_what_it_imports(self, tmp_path: Path) -> None:
        files = {
            "_seam.py": "import os\nimport pkg._a\nfrom pkg import _b\n",
            "_a.py": "",
            "_b.py": "",
        }
        graph = _graph_of(tmp_path, files)
        assert layer0_violations(graph, ["pkg._seam"]) == {"pkg._seam": {"pkg._a", "pkg._b"}}

    def test_layer0_counts_a_seam_function_level_import_on_the_deferred_graph(
        self, tmp_path: Path
    ) -> None:
        files = {"_seam.py": "def f():\n    from pkg._a import x\n", "_a.py": "x = 1\n"}
        assert layer0_violations(_graph_of(tmp_path, files), ["pkg._seam"]) == {}
        with_deferred = _graph_of(tmp_path, files, include_deferred=True)
        assert layer0_violations(with_deferred, ["pkg._seam"]) == {"pkg._seam": {"pkg._a"}}

    def test_layer0_checks_every_module_under_a_package_shaped_seam(self, tmp_path: Path) -> None:
        # ``pkg._seamless`` shares the seam's prefix: a startswith check
        # without the dot would count it.
        files = {
            "_seam/__init__.py": "",
            "_seam/impl.py": "import pkg._a\n",
            "_seamless.py": "import pkg._a\n",
            "_a.py": "",
        }
        graph = _graph_of(tmp_path, files)
        assert layer0_violations(graph, ["pkg._seam"]) == {"pkg._seam.impl": {"pkg._a"}}

    def test_layer0_exempts_a_type_checking_only_import(self, tmp_path: Path) -> None:
        files = {
            "_seam.py": "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    from pkg._a import A\n",
            "_a.py": "",
        }
        with_deferred = _graph_of(tmp_path, files, include_deferred=True)
        assert layer0_violations(with_deferred, ["pkg._seam"]) == {}

    def test_layer0_passes_on_a_seam_importing_only_the_stdlib(self, tmp_path: Path) -> None:
        files = {"_seam.py": "import os\nfrom pathlib import Path\n", "_a.py": "import pkg._seam\n"}
        graph = _graph_of(tmp_path, files)
        assert layer0_violations(graph, ["pkg._seam"]) == {}

    def test_layer0_passes_with_an_empty_seam_list(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": ""}
        graph = _graph_of(tmp_path, files)
        assert layer0_violations(graph, []) == {}

    def test_layer0_skips_seams_absent_from_the_tree(self, tmp_path: Path) -> None:
        files = {"_a.py": "import pkg._b\n", "_b.py": ""}
        graph = _graph_of(tmp_path, files)
        assert layer0_violations(graph, ["pkg._not_yet"]) == {}
