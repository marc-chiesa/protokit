"""Engine cross-file pre-walk pass + ``FileLintContext.directory_packages`` — D6c U1.

The cross-file pre-walk pass iterates ``compile_result.root_files`` (NOT
``pool_file_names`` per KTD-4 (d) empirical correction; buf does not
cross-fire PACKAGE_SAME_DIRECTORY / DIRECTORY_SAME_PACKAGE across module
boundaries, so protokit's analog scopes to per-invocation files) and
builds a 2-level ``directory_packages`` accumulator:
``dict[package, dict[filename, dirname]]``. The accumulator is wrapped
at both nesting depths via ``types.MappingProxyType`` (defense-in-depth
against accidental mutation by co-authored rule code) and injected
into every ``FileLintContext`` via
``_build_file_ctx(..., directory_packages=...)``.

Empirically-locked design decisions verified here (per Phase 0
verifications at ``/tmp/d6c_phase0/`` against buf v1.69.0):

- **Iterate ``root_files``, NOT ``pool_file_names``** (diverges from R7;
  KTD-4 (d) — buf does not cross-fire across module boundaries).
- **No empty-package skip** — ``fd.package == ""`` participates in the
  accumulator with an empty-string key, because buf fires R8b on
  packageless files mixed with declared-package files in the same
  directory (KTD-4 (b)).
- **Proto-root canonicalization** — files at the root render their
  parent as ``"."`` via ``str(PurePosixPath(name).parent) or "."``
  (matches buf v1.69.0's ``"directory \\\".\\\""`` empirically; KTD-4 (c)).
- **No WKT filter** at ``google/protobuf/`` (mirrors R7 posture; KTD-4
  (a) — single-file Phase 0 fixture was inconclusive but the safest
  alignment with R7 is no-filter; if U3 surfaces a divergence, document
  via ``_PARITY_EXCEPTIONS`` entry).
- **Cross-platform determinism** via ``posixpath.basename`` (NOT
  ``os.path.basename``).
- **Defensive ``try/except (KeyError, AttributeError, ValueError):
  continue``** matching the R7 pattern at ``engine.py:543-569``.
- **2-level ``MappingProxyType`` wrap** — mutation raises ``TypeError``
  at both nesting depths.

U1 ships engine plumbing with zero rule consumers; this module pins
the contract that U2's R8 + R8b rules will consume.
"""

from __future__ import annotations

import inspect
import types
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.decorator import lint_rule
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    ElementKind,
    FileLintContext,
    LintProfile,
    LintSeverity,
)

# ---- Fixture helpers --------------------------------------------------------


def _write_proto(dest: Path, name: str, contents: str) -> Path:
    """Write a .proto file at ``dest/name`` (creating intermediate dirs)."""
    path = dest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def _make_capture_pack(
    profile_name: str, rule_id: str, captured: list[Any],
) -> Any:
    """Synthetic rule pack capturing both accumulator views per call.

    Each captured entry is a 2-tuple ``(directory_packages,
    directory_packages_by_dir)`` so tests can assert both R8's
    per-package view and R8b's per-directory inverted index.
    """

    @lint_rule(
        rule_id=rule_id,
        severity=LintSeverity.INFO,
        profiles=(profile_name,),
        element=ElementKind.FILE,
        message_template="captured",
        source_spec="",
    )
    def _capture(ctx: FileLintContext) -> None:
        captured.append((ctx.directory_packages, ctx.directory_packages_by_dir))

    module = types.SimpleNamespace()
    module.__name__ = f"_test_capture_dpkg_{rule_id.replace('/', '_')}"
    module.RULES = (_capture,)
    return module


def _materialize_fixture(
    tmp_path: Path,
    files: dict[str, str],
) -> Path:
    """Materialise a multi-file proto fixture; return root proto-path."""
    out = tmp_path / "fixture"
    out.mkdir(parents=True, exist_ok=True)
    for relpath, contents in files.items():
        _write_proto(out, relpath, contents)
    return out


def _run_and_capture(
    proto_root: Path,
    root_protos: list[Path],
) -> list[
    tuple[
        Mapping[str, Mapping[str, str]] | None,
        Mapping[str, Mapping[str, frozenset[str]]] | None,
    ]
]:
    """Run engine over ``root_protos``; return captured accumulator snapshots."""
    captured: list[
        tuple[
            Mapping[str, Mapping[str, str]] | None,
            Mapping[str, Mapping[str, frozenset[str]]] | None,
        ]
    ] = []
    rule_id = "u1-capture/directory-packages"
    pack = _make_capture_pack("u1-capture-dpkg", rule_id, captured)
    engine = LintEngine()
    engine.load_rule_pack(pack)
    compile_result = compile_protos_to_result(
        root_protos,
        proto_paths=(str(proto_root),),
    )
    engine.run(
        compile_result,
        profile=LintProfile(
            name="default",
            rule_ids=frozenset({rule_id}),
            min_severity=LintSeverity.INFO,
        ),
    )
    return captured


# ---- Accumulator construction ------------------------------------------------


class TestAccumulatorIteratesRootFiles:
    """KTD-4 (d): accumulator iterates ``root_files``, NOT ``pool_file_names``.

    Load-bearing contract — diverges from R7's pre-walk which iterates
    ``pool_file_names`` for cross-import language-namespace conflicts.
    R8/R8b's per-module-isolation semantic (buf does not cross-fire
    across module boundaries) requires the accumulator to scope to
    files protokit was invoked on, NOT transitively-imported files.
    """

    def test_root_files_only_in_accumulator_not_transitive_imports(
        self, tmp_path: Path,
    ) -> None:
        """Three files: a imports b imports c. Only a is root.

        Pool contains all 3; root_files = (a,). Accumulator must
        contain ONLY a's entry. If accumulator iterates
        ``pool_file_names`` (R7's posture) instead, b + c would also
        appear and this test fails.
        """
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "c.proto": (
                    'syntax = "proto3";\n'
                    "package acme.transitive;\n"
                    "message C {}\n"
                ),
                "b.proto": (
                    'syntax = "proto3";\n'
                    "package acme.transitive;\n"
                    'import "c.proto";\n'
                    "message B { C c = 1; }\n"
                ),
                "a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.transitive;\n"
                    'import "b.proto";\n'
                    "message A { B b = 1; }\n"
                ),
            },
        )

        captured = _run_and_capture(proto_root, [proto_root / "a.proto"])

        assert len(captured) == 1
        snapshot, _by_dir = captured[0]
        assert snapshot is not None, "non-empty root_files must produce accumulator"
        assert "acme.transitive" in snapshot
        per_pkg = snapshot["acme.transitive"]
        # Only a.proto should appear — b and c are transitive-only.
        assert set(per_pkg.keys()) == {"a.proto"}, (
            f"accumulator should iterate root_files only; got "
            f"{set(per_pkg.keys())} (b/c indicate pool_file_names scope)"
        )


class TestEmptyPackageIncluded:
    """KTD-4 (b): empty-package files PARTICIPATE in accumulator.

    Buf empirical: fires R8b on packageless files mixed with declared-
    package files in the same directory. Protokit's accumulator must
    track packageless files (empty-string key) so the rule callable
    can detect the mixed-declared+undeclared case.
    """

    def test_packageless_file_keyed_by_empty_string(
        self, tmp_path: Path,
    ) -> None:
        """Two files at root, one declares package, one doesn't."""
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message A {}\n"
                ),
                "b.proto": (
                    'syntax = "proto3";\n'
                    "message B {}\n"
                ),
            },
        )

        captured = _run_and_capture(
            proto_root,
            [proto_root / "a.proto", proto_root / "b.proto"],
        )

        assert len(captured) == 2
        snapshot, _by_dir = captured[0]
        assert snapshot is not None
        # Two distinct keys: "acme.foo" + "" (the packageless entry).
        assert set(snapshot.keys()) == {"acme.foo", ""}, (
            f"packageless files must appear under empty-string key; got "
            f"{set(snapshot.keys())}"
        )
        assert snapshot["acme.foo"] == {"a.proto": "."}
        assert snapshot[""] == {"b.proto": "."}


class TestProtoRootCanonicalization:
    """KTD-4 (c): proto-root files canonicalize parent to ``"."``."""

    def test_proto_root_file_dirname_is_dot(
        self, tmp_path: Path,
    ) -> None:
        """Single file at proto-root produces ``"."`` dirname."""
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message A {}\n"
                ),
            },
        )

        captured = _run_and_capture(proto_root, [proto_root / "a.proto"])

        assert len(captured) == 1
        snapshot, _by_dir = captured[0]
        assert snapshot is not None
        assert snapshot == {"acme.foo": {"a.proto": "."}}, (
            f"proto-root dirname must canonicalize to '.'; got {snapshot}"
        )


class TestNestedDirectoriesByImmediateParent:
    """Files in nested dirs group by IMMEDIATE parent (not transitive)."""

    def test_files_grouped_by_immediate_parent_dir(
        self, tmp_path: Path,
    ) -> None:
        """Files at foo/bar/, foo/baz/, foo/ — each gets its own dirname."""
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "foo/x.proto": (
                    'syntax = "proto3";\n'
                    "package acme.shared;\n"
                    "message X {}\n"
                ),
                "foo/bar/y.proto": (
                    'syntax = "proto3";\n'
                    "package acme.shared;\n"
                    "message Y {}\n"
                ),
                "foo/baz/z.proto": (
                    'syntax = "proto3";\n'
                    "package acme.shared;\n"
                    "message Z {}\n"
                ),
            },
        )

        captured = _run_and_capture(
            proto_root,
            [
                proto_root / "foo/x.proto",
                proto_root / "foo/bar/y.proto",
                proto_root / "foo/baz/z.proto",
            ],
        )

        assert len(captured) == 3
        snapshot, _by_dir = captured[0]
        assert snapshot is not None
        per_pkg = snapshot["acme.shared"]
        assert per_pkg == {
            "foo/x.proto": "foo",
            "foo/bar/y.proto": "foo/bar",
            "foo/baz/z.proto": "foo/baz",
        }, f"dirname must use immediate parent only; got {per_pkg}"


class TestAccumulatorEmptyOnEmptyRootFiles:
    """Accumulator returns ``None`` when ``root_files`` is empty.

    Mirrors R7's behavior on empty pool. Test-helper paths +
    compile-failure paths benefit from the early-return signal so
    R8/R8b rules can early-return without iterating an empty Mapping.
    """

    def test_returns_none_when_root_files_empty(self) -> None:
        """Direct call on an engine with no root_files."""
        from google.protobuf import descriptor_pool as descriptor_pool_pkg

        from protokit.schema.compile import CompileResult

        engine = LintEngine()
        empty_result = CompileResult(
            pool=descriptor_pool_pkg.Default(),
            root_files=(),
            pool_file_names=(),
            diagnostics=(),
        )
        by_pkg, by_dir = engine._build_directory_package_accumulator(empty_result)
        assert by_pkg is None
        assert by_dir is None


class TestImmutability:
    """2-level ``MappingProxyType`` wrap rejects mutation at both depths."""

    def test_outer_mapping_is_mappingproxy(
        self, tmp_path: Path,
    ) -> None:
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message A {}\n"
                ),
            },
        )

        captured = _run_and_capture(proto_root, [proto_root / "a.proto"])
        snapshot, _by_dir = captured[0]
        assert snapshot is not None
        assert isinstance(snapshot, MappingProxyType)
        with pytest.raises(TypeError):
            snapshot["new_pkg"] = {}  # type: ignore[index]

    def test_inner_mapping_is_mappingproxy(
        self, tmp_path: Path,
    ) -> None:
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message A {}\n"
                ),
            },
        )

        captured = _run_and_capture(proto_root, [proto_root / "a.proto"])
        snapshot, _by_dir = captured[0]
        assert snapshot is not None
        per_pkg = snapshot["acme.foo"]
        assert isinstance(per_pkg, MappingProxyType)
        with pytest.raises(TypeError):
            per_pkg["b.proto"] = "elsewhere"  # type: ignore[index]


# ---- State lifecycle ---------------------------------------------------------


class TestStateLifecycle:
    """The four lifecycle mechanics mirror R7's ``_current_package_options``.

    1. ``__init__`` declares the instance attribute with ``None`` default.
    2. ``run()`` populates the attribute after Step 3.5 pre-walk.
    3. ``run()``'s ``finally`` block clears the attribute back to ``None``
       (prevents cross-``run()`` leak).
    4. ``_build_file_ctx`` threads the snapshot into ``FileLintContext.directory_packages``.

    A regression that omits any one of these mechanics fails the
    corresponding sub-test below.
    """

    def test_init_declares_attribute_with_none_default(self) -> None:
        """Mechanic 1: ``LintEngine().__init__`` sets both attrs to ``None``."""
        engine = LintEngine()
        assert hasattr(engine, "_current_directory_packages")
        assert engine._current_directory_packages is None
        assert hasattr(engine, "_current_directory_packages_by_dir")
        assert engine._current_directory_packages_by_dir is None

    def test_run_clears_attribute_in_finally(
        self, tmp_path: Path,
    ) -> None:
        """Mechanic 3: post-``run()`` the attribute is back to ``None``.

        Ensures the accumulator state does NOT leak across ``run()``
        invocations (a stale accumulator could otherwise cause findings
        from a prior compile_result to bleed into a later one).
        """
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message A {}\n"
                ),
            },
        )

        captured: list[Any] = []
        rule_id = "u1-lifecycle/check-reset"
        pack = _make_capture_pack("u1-lifecycle-reset", rule_id, captured)
        engine = LintEngine()
        engine.load_rule_pack(pack)
        compile_result = compile_protos_to_result(
            [proto_root / "a.proto"],
            proto_paths=(str(proto_root),),
        )
        engine.run(
            compile_result,
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({rule_id}),
                min_severity=LintSeverity.INFO,
            ),
        )
        # Mechanic 2 verification (populate during run): ctx received non-None
        # for both views.
        snapshot, by_dir = captured[0]
        assert snapshot is not None
        assert by_dir is not None
        # Mechanic 3 verification (reset in finally — both views).
        assert engine._current_directory_packages is None
        assert engine._current_directory_packages_by_dir is None


# ---- FileLintContext field contract -----------------------------------------


class TestFileLintContextField:
    """``FileLintContext.directory_packages`` field contract."""

    def test_field_default_is_none_for_test_helpers(self) -> None:
        """Mechanic 4 partial: test helpers can construct without kwarg."""
        from google.protobuf import descriptor_pool as descriptor_pool_pkg

        pool = descriptor_pool_pkg.Default()
        # Use any real fd from the pool; google/protobuf/descriptor.proto
        # is always available in the default pool.
        fd = pool.FindFileByName("google/protobuf/descriptor.proto")
        ctx = FileLintContext(
            file=fd,
            pool=pool,
            profile="default",
            _emit_fn=lambda finding: None,
            _rule_id="test",
            _effective_severity=lambda vk: LintSeverity.INFO,
        )
        assert ctx.directory_packages is None
        assert ctx.directory_packages_by_dir is None
        # Sibling field also stays None — confirms our new fields don't
        # accidentally override the R7 pattern.
        assert ctx.package_options is None


# ---- Presence-ratchet for the 4 lifecycle mechanics --------------------------


class TestLifecycleMechanicsPresenceRatchet:
    """Pin the 4 lifecycle mechanics by source-substring.

    Per [[presence-ratchet-test-pattern-for-prose-substrings-2026-05-14]]
    5-discipline rule (each substring fits a single source line). The
    ratchet catches regressions that delete the accumulator mechanics
    silently — e.g., refactoring ``run()`` and forgetting the
    ``finally`` reset, or removing the ``_build_file_ctx`` thread.
    """

    def test_engine_source_pins_four_mechanics(self) -> None:
        """Inspect engine.py source for the 4 expected substrings."""
        from protokit.schema.lint import engine as engine_module

        src = inspect.getsource(engine_module)

        # Mechanic 1: __init__ declares _current_directory_packages = None.
        assert "self._current_directory_packages" in src, (
            "engine.__init__ must declare _current_directory_packages attr"
        )

        # Mechanic 2: run() calls _build_directory_package_accumulator.
        assert "self._build_directory_package_accumulator(" in src, (
            "engine.run() must populate _current_directory_packages via "
            "_build_directory_package_accumulator() call"
        )

        # Mechanic 3: finally block resets to None.
        # Substring chosen to fit a single source line (5th discipline rule).
        assert "self._current_directory_packages = None" in src, (
            "engine.run() finally block must reset "
            "_current_directory_packages to None"
        )

        # Mechanic 4: _build_file_ctx threads BOTH views into FileLintContext.
        assert "directory_packages=self._current_directory_packages" in src, (
            "engine._build_file_ctx must thread the per-package view "
            "into FileLintContext via directory_packages kwarg"
        )
        assert (
            "directory_packages_by_dir=self._current_directory_packages_by_dir"
            in src
        ), (
            "engine._build_file_ctx must thread the per-directory inverted "
            "view into FileLintContext via directory_packages_by_dir kwarg"
        )


# ---- Inverted-index view (R8b primary access pattern, ADV-1 fix) ------------


class TestInvertedIndexView:
    """Per-directory inverted index ``directory_packages_by_dir`` (R8b view).

    Resolves ce:review ADV-1: the per-package view alone would force R8b
    into O(N) per-file scan over all packages to find files in the
    current dir = O(N^2) total across N root files. The inverted index
    gives R8b O(1) directory-keyed lookup.
    """

    def test_inverted_index_keyed_by_directory(self, tmp_path: Path) -> None:
        """3 files across 2 dirs with mixed packages — verify both views."""
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "pkg/a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message A {}\n"
                ),
                "pkg/b.proto": (
                    'syntax = "proto3";\n'
                    "package acme.bar;\n"
                    "message B {}\n"
                ),
                "other_dir/c.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message C {}\n"
                ),
            },
        )

        captured = _run_and_capture(
            proto_root,
            [
                proto_root / "pkg/a.proto",
                proto_root / "pkg/b.proto",
                proto_root / "other_dir/c.proto",
            ],
        )

        assert len(captured) == 3
        _by_pkg, by_dir = captured[0]
        assert by_dir is not None

        # `pkg` directory contains 2 packages (acme.foo via a.proto, acme.bar
        # via b.proto). R8b uses this directly for the "mixed packages in
        # same dir" detection.
        assert set(by_dir["pkg"].keys()) == {"acme.foo", "acme.bar"}
        assert by_dir["pkg"]["acme.foo"] == frozenset({"pkg/a.proto"})
        assert by_dir["pkg"]["acme.bar"] == frozenset({"pkg/b.proto"})

        # `other_dir` contains 1 package (acme.foo via c.proto).
        assert set(by_dir["other_dir"].keys()) == {"acme.foo"}
        assert by_dir["other_dir"]["acme.foo"] == frozenset({"other_dir/c.proto"})

    def test_inverted_index_empty_package_under_empty_string_key(
        self, tmp_path: Path,
    ) -> None:
        """Packageless files appear under empty-string package key per KTD-4 (b)."""
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message A {}\n"
                ),
                "b.proto": (
                    'syntax = "proto3";\n'
                    "message B {}\n"
                ),
            },
        )

        captured = _run_and_capture(
            proto_root, [proto_root / "a.proto", proto_root / "b.proto"],
        )
        _by_pkg, by_dir = captured[0]
        assert by_dir is not None
        # Proto-root canonicalizes to ".". Both packages (acme.foo and "")
        # appear under that directory.
        assert set(by_dir["."].keys()) == {"acme.foo", ""}
        assert by_dir["."]["acme.foo"] == frozenset({"a.proto"})
        assert by_dir["."][""] == frozenset({"b.proto"})

    def test_inverted_index_consistent_with_per_package_view(
        self, tmp_path: Path,
    ) -> None:
        """Both views reflect the same triples — cross-validation."""
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "x/foo.proto": (
                    'syntax = "proto3";\n'
                    "package acme.x;\n"
                    "message Foo {}\n"
                ),
                "y/bar.proto": (
                    'syntax = "proto3";\n'
                    "package acme.x;\n"
                    "message Bar {}\n"
                ),
            },
        )
        captured = _run_and_capture(
            proto_root,
            [proto_root / "x/foo.proto", proto_root / "y/bar.proto"],
        )
        by_pkg, by_dir = captured[0]
        assert by_pkg is not None and by_dir is not None

        # Reconstruct triples from both views; assert equality.
        from_pkg = {
            (pkg, fname, dirname)
            for pkg, files in by_pkg.items()
            for fname, dirname in files.items()
        }
        from_dir = {
            (pkg, fname, dirname)
            for dirname, packages in by_dir.items()
            for pkg, fnames in packages.items()
            for fname in fnames
        }
        assert from_pkg == from_dir

    def test_inverted_index_inner_value_is_frozenset(
        self, tmp_path: Path,
    ) -> None:
        """Inner fname collection is frozenset (immutable by construction)."""
        proto_root = _materialize_fixture(
            tmp_path,
            {
                "a.proto": (
                    'syntax = "proto3";\n'
                    "package acme.foo;\n"
                    "message A {}\n"
                ),
            },
        )
        captured = _run_and_capture(proto_root, [proto_root / "a.proto"])
        _by_pkg, by_dir = captured[0]
        assert by_dir is not None
        fnames = by_dir["."]["acme.foo"]
        assert isinstance(fnames, frozenset)
