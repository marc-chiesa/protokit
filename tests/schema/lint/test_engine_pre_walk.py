"""Engine Step 3.5 pre-walk pass + ``FileLintContext.package_options`` — D6b U4a.

The pre-walk pass iterates the FULL pool
(``compile_result.pool_file_names``) once before Step 4's per-file
dispatch walk and builds a 3-level ``package_options`` accumulator:
``dict[package, dict[option_attr, dict[filename, str | None]]]``. The
accumulator is wrapped at all 3 nesting depths via
``types.MappingProxyType`` (defense-in-depth against accidental
mutation by co-authored rule code) and injected into every
``FileLintContext`` via ``_build_file_ctx(..., package_options=...)``.

Empirically-locked design decisions verified here:

- **No WKT filter** at ``google/protobuf/`` (per
  ``_buf_smoke/recorded/wkt-conflict.json``).
- **No empty-package skip** — ``ctx.file.package == ""`` participates
  in the accumulator like any other package (per
  ``_buf_smoke/recorded/empty-package-mixed.json``).
- **Lowercase bool rendering** for ``java_multiple_files`` via
  ``str(value).lower()`` (per
  ``_buf_smoke/recorded/mixed-value-java-multiple-files.json``).
- **Cross-platform determinism** via ``posixpath.basename`` (NOT
  ``os.path.basename`` which is platform-aware).
- **Defensive ``try/except KeyError: continue``** matching the existing
  Step 4 pattern at ``engine.py:407-412``.
- **3-level ``MappingProxyType`` wrap** — mutation raises ``TypeError``
  at all 3 nesting depths.

U4a ships engine plumbing with zero rule consumers; this module pins
the contract that U4b's R7 rules will consume.
"""

from __future__ import annotations

import inspect
import time
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint._cli_utils import _safe_for_stderr
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    ElementKind,
    FileLintContext,
    LintProfile,
    LintSeverity,
)

# ---- Fixture helpers --------------------------------------------------------


_OPTION_ATTRS = (
    "go_package",
    "java_package",
    "csharp_namespace",
    "php_namespace",
    "ruby_package",
    "swift_prefix",
    "java_multiple_files",
)


def _write_proto(dest: Path, name: str, contents: str) -> Path:
    path = dest / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


def _three_files_same_package(
    tmp_path: Path,
    *,
    pkg: str = "u4a.engine_pre_walk",
    go_packages: tuple[str | None, ...] = ("X", "Y", "X"),
) -> Path:
    """Materialise three sibling .proto files in the same package.

    ``go_packages[i] is None`` omits the ``option go_package`` declaration.
    """
    out = tmp_path / "three_files"
    out.mkdir(parents=True, exist_ok=True)
    pkg_line = f"package {pkg};\n" if pkg else ""
    for name, value in zip(["a.proto", "b.proto", "c.proto"], go_packages, strict=True):
        opt_line = (
            f'option go_package = "github.com/x/{value}";\n'
            if value is not None
            else ""
        )
        (out / name).write_text(
            f'syntax = "proto3";\n\n'
            f"{pkg_line}\n"
            f"{opt_line}\n"
            f"message Stub{name[0].upper()} {{}}\n"
        )
    return out


def _build_engine_with_no_rules() -> LintEngine:
    """Construct a bare engine — U4a verifies plumbing, no R7 consumers yet."""
    return LintEngine()


def _default_profile() -> LintProfile:
    """Minimal profile that loads no R7 rules — pre-walk runs regardless."""
    return LintProfile(
        name="default",
        min_severity=LintSeverity.INFO,
        rule_ids=frozenset(),
    )


def _make_capture_pack(profile_name: str, rule_id: str, captured: list[Any]) -> Any:
    """Build a synthetic rule pack module with a single FILE-element rule that
    captures ``ctx.package_options`` into ``captured``.

    Engine ``load_rule_pack(module)`` consumes ``module.RULES`` (tuple of
    @lint_rule-decorated callables). We build a fake module via ``types.SimpleNamespace``
    so each test gets an isolated rule that doesn't interfere with global registries.
    """
    import types

    from protokit.schema.lint.decorator import lint_rule

    @lint_rule(
        rule_id=rule_id,
        severity=LintSeverity.INFO,
        profiles=(profile_name,),
        element=ElementKind.FILE,
        message_template="captured",
        source_spec="",
    )
    def _capture(ctx: FileLintContext) -> None:
        captured.append(ctx.package_options)

    module = types.SimpleNamespace()
    # load_rule_pack reads module.__name__ for idempotency + module.RULES.
    module.__name__ = f"_test_capture_{rule_id.replace('/', '_')}"
    module.RULES = (_capture,)
    return module


# ---- Accumulator construction over full pool --------------------------------


class TestAccumulatorConstruction:
    """``LintEngine.run`` builds ``package_options`` from the full pool.

    ce:review follow-up (Finding #3 / Testing T-1 + T-2 + Maintainability
    M1 + Adversarial ADV-U4a-003): the original two tests in this class
    set up monkeypatch-based captures but the captures never fired (no
    FILE-element rules were loaded → ``_build_file_ctx`` was never
    invoked). Both tests fell back to asserting on
    ``result.pool_file_names`` — a ``CompileResult`` field already
    covered by ``test_compile_pool_file_names.py``. Deleting
    ``_build_package_options_accumulator`` from the engine would not
    have failed those tests. Rewritten here using ``_make_capture_pack``
    (the same pattern used by ``TestPreWalkPackageOptionsInjection``
    immediately below) so the accumulator is actually observed.
    """

    def test_accumulator_built_from_pool_file_names_not_root_files(
        self, tmp_path: Path,
    ) -> None:
        """Pre-walk iterates ``pool_file_names``, not ``root_files``.

        Verifies the load-bearing semantic difference between the two
        fields: ``pool_file_names`` includes transitively-imported
        files, ``root_files`` does not. The fixture has a.proto import
        b.proto + c.proto, so passing only a.proto as root pulls b/c
        into the pool transitively — the precise scenario where
        ``pool_file_names`` and ``root_files`` diverge. The captured
        ``ctx.package_options`` must include accumulator entries for
        b.proto + c.proto (transitive) alongside a.proto (root). If a
        regression caused the pre-walk to iterate ``root_files``
        instead, only ``a.proto`` would appear and this test fails.
        """
        # Three files: a.proto imports b.proto + c.proto. All in the
        # same package so they share a per-pkg accumulator entry.
        proto_dir = tmp_path / "transitive_fixture"
        proto_dir.mkdir(parents=True, exist_ok=True)
        (proto_dir / "b.proto").write_text(
            'syntax = "proto3";\n'
            'package u4a.transitive;\n'
            'option go_package = "github.com/x/b";\n'
            'message StubB {}\n'
        )
        (proto_dir / "c.proto").write_text(
            'syntax = "proto3";\n'
            'package u4a.transitive;\n'
            'option go_package = "github.com/x/c";\n'
            'message StubC {}\n'
        )
        (proto_dir / "a.proto").write_text(
            'syntax = "proto3";\n'
            'package u4a.transitive;\n'
            'import "b.proto";\n'
            'import "c.proto";\n'
            'option go_package = "github.com/x/a";\n'
            'message StubA { StubB b = 1; StubC c = 2; }\n'
        )

        a_only = compile_protos_to_result(
            [proto_dir / "a.proto"],
            proto_paths=(str(proto_dir),),
        )
        # Pool contains all 3 (transitive imports); root_files only a.
        assert set(a_only.pool_file_names) >= {
            "a.proto", "b.proto", "c.proto",
        }, (
            f"pool_file_names should be a superset of root_files via "
            f"transitive imports; got {a_only.pool_file_names}"
        )
        assert a_only.root_files == ("a.proto",), (
            f"root_files should reflect CLI argv only; got "
            f"{a_only.root_files}"
        )

        # Capture the accumulator via a FILE-element rule consumer.
        captured: list[Mapping[str, Mapping[str, Mapping[str, str | None]]] | None] = []
        rule_id = "u4a-followup/capture-superset"
        pack = _make_capture_pack(
            "u4a-followup-capture-superset", rule_id, captured,
        )
        engine = LintEngine()
        engine.load_rule_pack(pack)
        engine.run(
            a_only,
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({rule_id}),
                min_severity=LintSeverity.INFO,
            ),
        )

        # The capture rule fires for a.proto (the only root); the
        # captured ``package_options`` must include EVERY pool file's
        # entry, not just root_files. Concrete invariant: the per-attr
        # inner map for go_package keys on every fixture file.
        assert len(captured) >= 1, (
            "FILE-element capture rule should have fired at least once"
        )
        pkg_options = captured[0]
        assert pkg_options is not None, (
            "ctx.package_options should be populated when pool is non-empty"
        )
        per_attr = pkg_options["u4a.transitive"]["go_package"]
        keys = set(per_attr.keys())
        assert keys >= {"a.proto", "b.proto", "c.proto"}, (
            f"per-attr inner map must include every pool file (roots + "
            f"transitive imports); got keys {keys}. If a regression caused "
            f"the pre-walk to iterate root_files instead of "
            f"pool_file_names, only 'a.proto' would appear."
        )

    def test_accumulator_3_level_dict_shape(self, tmp_path: Path) -> None:
        """``package_options[pkg][attr][fname] = str | None`` shape.

        Captures the actual ``ctx.package_options`` accumulator (via
        ``_make_capture_pack``) and walks its 3-level structure:
        outer keys are package names (str); each inner map keys on
        option attr name (str); each leaf map keys on filename (str)
        with values ``str | None``.
        """
        # Mixed-value fixture: a + b declare go_package; c omits.
        # Helper prefixes each non-None value with 'github.com/x/'.
        proto_dir = _three_files_same_package(
            tmp_path,
            pkg="shape.test",
            go_packages=("a", "b", None),
        )
        result = compile_protos_to_result(
            [
                proto_dir / "a.proto",
                proto_dir / "b.proto",
                proto_dir / "c.proto",
            ],
        )

        captured: list[Mapping[str, Mapping[str, Mapping[str, str | None]]] | None] = []
        rule_id = "u4a-followup/capture-shape"
        pack = _make_capture_pack(
            "u4a-followup-capture-shape", rule_id, captured,
        )
        engine = LintEngine()
        engine.load_rule_pack(pack)
        engine.run(
            result,
            profile=LintProfile(
                name="default",
                rule_ids=frozenset({rule_id}),
                min_severity=LintSeverity.INFO,
            ),
        )

        assert len(captured) >= 1
        pkg_options = captured[0]
        assert pkg_options is not None

        # Level 1: package keys.
        assert "shape.test" in pkg_options, (
            f"package_options outer should key on package name; "
            f"got keys {list(pkg_options)}"
        )

        # Level 2: option_attr keys per package.
        per_pkg = pkg_options["shape.test"]
        assert "go_package" in per_pkg, (
            f"per-package map should include every PACKAGE_SAME_* attr; "
            f"got keys {sorted(per_pkg)}"
        )

        # Level 3: filename → str | None per attr.
        go_pkg_per_file = per_pkg["go_package"]
        assert go_pkg_per_file["a.proto"] == "github.com/x/a"
        assert go_pkg_per_file["b.proto"] == "github.com/x/b"
        assert go_pkg_per_file["c.proto"] is None, (
            "omitted option should appear as None, not absent"
        )


class TestPreWalkPackageOptionsInjection:
    """Pre-walk-built accumulator reaches rule contexts via ``FileLintContext.package_options``."""

    def _capture_with_minimal_rule(
        self, result: Any, captured: list[Any],
    ) -> None:
        """Register a tiny FILE-element rule that captures ctx.package_options."""
        rule_id = "u4a/capture-package-options"
        pack = _make_capture_pack("u4a-capture", rule_id, captured)
        engine = LintEngine()
        engine.load_rule_pack(pack)
        profile = LintProfile(
            name="u4a-capture",
            min_severity=LintSeverity.INFO,
            rule_ids=frozenset({rule_id}),
        )
        engine.run(result, profile=profile)

    def test_package_options_injected_into_file_context(
        self, tmp_path: Path,
    ) -> None:
        """``ctx.package_options`` is non-None when pool_file_names is non-empty."""
        proto_dir = _three_files_same_package(tmp_path)
        result = compile_protos_to_result(
            [proto_dir / "a.proto", proto_dir / "b.proto", proto_dir / "c.proto"],
        )
        captured: list[Any] = []
        self._capture_with_minimal_rule(result, captured)
        assert captured, "rule should have been dispatched at least once"
        for pkg_opts in captured:
            assert pkg_opts is not None
            assert isinstance(pkg_opts, Mapping)

    def test_package_options_3_level_shape(self, tmp_path: Path) -> None:
        """``pkg_opts[pkg][attr][fname] = str | None`` for every fixture file."""
        proto_dir = _three_files_same_package(tmp_path)
        result = compile_protos_to_result(
            [proto_dir / "a.proto", proto_dir / "b.proto", proto_dir / "c.proto"],
        )
        captured: list[Any] = []
        self._capture_with_minimal_rule(result, captured)
        pkg_opts = captured[0]
        assert "u4a.engine_pre_walk" in pkg_opts
        per_pkg = pkg_opts["u4a.engine_pre_walk"]
        # All 7 PACKAGE_SAME_* attrs captured per package.
        assert set(per_pkg.keys()) == set(_OPTION_ATTRS)
        # Per-attr dict has one entry per fixture file.
        go_pkg_dict = per_pkg["go_package"]
        assert set(go_pkg_dict.keys()) >= {"a.proto", "b.proto", "c.proto"}
        # Values are str (declared) or None (omitted). a→X, b→Y, c→X.
        assert go_pkg_dict["a.proto"] == "github.com/x/X"
        assert go_pkg_dict["b.proto"] == "github.com/x/Y"
        assert go_pkg_dict["c.proto"] == "github.com/x/X"

    def test_mixed_presence_captures_none_for_omitters(
        self, tmp_path: Path,
    ) -> None:
        """``a→X, b omits, c omits`` → ``{a: "X", b: None, c: None}``."""
        proto_dir = _three_files_same_package(
            tmp_path, go_packages=("X", None, None),
        )
        result = compile_protos_to_result(
            [proto_dir / "a.proto", proto_dir / "b.proto", proto_dir / "c.proto"],
        )
        captured: list[Any] = []
        self._capture_with_minimal_rule(result, captured)
        per_pkg = captured[0]["u4a.engine_pre_walk"]
        go_pkg = per_pkg["go_package"]
        assert go_pkg["a.proto"] == "github.com/x/X"
        assert go_pkg["b.proto"] is None
        assert go_pkg["c.proto"] is None

    def test_empty_package_string_is_captured_as_real_key(
        self, tmp_path: Path,
    ) -> None:
        """No-package files participate in the accumulator under the ``""`` key."""
        proto_dir = _three_files_same_package(tmp_path, pkg="")
        result = compile_protos_to_result(
            [proto_dir / "a.proto", proto_dir / "b.proto", proto_dir / "c.proto"],
        )
        captured: list[Any] = []
        self._capture_with_minimal_rule(result, captured)
        assert "" in captured[0]

    def test_no_wkt_filter_google_protobuf_in_accumulator(
        self, tmp_path: Path,
    ) -> None:
        """``google.protobuf`` package appears in accumulator (NO filter)."""
        # User file imports a WKT → google/protobuf/any.proto is in pool.
        user = _write_proto(
            tmp_path, "user.proto",
            'syntax = "proto3";\n\n'
            'package u4a.no_wkt_filter;\n\n'
            'import "google/protobuf/any.proto";\n\n'
            'message U { google.protobuf.Any p = 1; }\n',
        )
        result = compile_protos_to_result([user])
        captured: list[Any] = []
        self._capture_with_minimal_rule(result, captured)
        # google.protobuf package IS in the accumulator — buf v1.69.0 does
        # NOT special-case it (recorded/wkt-conflict.json).
        assert "google.protobuf" in captured[0]


class TestPlanRequiredScenarios:
    """ce:review follow-up (Finding #8 / Testing T-5): 5 scenarios called
    out in plan L334 that the original U4a test suite missed.

    - **multi-package isolation:** two packages in the pool produce
      independent per-pkg entries (no aliasing).
    - **single-file package:** exactly one .proto in a package → per-attr
      map has exactly one entry.
    - **all-omit:** every file in a package omits a given option → every
      per-attr value is None.
    - **all-same:** every file declares the same value (clean-pass case
      for U4b R7 rule emission — accumulator captures uniformly).
    - **transitive-import contribution:** a transitively-imported file
      (not in root_files) contributes to the per-pkg accumulator entry
      for ITS package.
    """

    def _capture(
        self, result: Any, captured: list[Any],
    ) -> None:
        """Register a FILE-element capture rule + run the engine."""
        rule_id = "u4a-followup/plan-scenarios"
        pack = _make_capture_pack(
            "u4a-followup-plan-scenarios", rule_id, captured,
        )
        engine = LintEngine()
        engine.load_rule_pack(pack)
        engine.run(
            result,
            profile=LintProfile(
                name="u4a-followup-plan-scenarios",
                rule_ids=frozenset({rule_id}),
                min_severity=LintSeverity.INFO,
            ),
        )

    def test_multi_package_isolation(self, tmp_path: Path) -> None:
        """Two packages → independent per-pkg accumulator entries."""
        # alpha.proto in package u4a.scenarios.alpha
        # beta.proto in package u4a.scenarios.beta
        # Both declare go_package; different values.
        _write_proto(
            tmp_path, "alpha.proto",
            'syntax = "proto3";\n'
            'package u4a.scenarios.alpha;\n'
            'option go_package = "github.com/x/alpha";\n'
            'message AlphaStub {}\n',
        )
        _write_proto(
            tmp_path, "beta.proto",
            'syntax = "proto3";\n'
            'package u4a.scenarios.beta;\n'
            'option go_package = "github.com/x/beta";\n'
            'message BetaStub {}\n',
        )
        result = compile_protos_to_result(
            [tmp_path / "alpha.proto", tmp_path / "beta.proto"],
        )
        captured: list[Any] = []
        self._capture(result, captured)
        pkg_opts = captured[0]

        assert "u4a.scenarios.alpha" in pkg_opts
        assert "u4a.scenarios.beta" in pkg_opts
        # Each package's per-attr entry references only its own file.
        alpha_go = pkg_opts["u4a.scenarios.alpha"]["go_package"]
        beta_go = pkg_opts["u4a.scenarios.beta"]["go_package"]
        assert "alpha.proto" in alpha_go and "beta.proto" not in alpha_go, (
            f"alpha pkg entry must not contain beta's file; got {alpha_go}"
        )
        assert "beta.proto" in beta_go and "alpha.proto" not in beta_go, (
            f"beta pkg entry must not contain alpha's file; got {beta_go}"
        )
        # Values are isolated too.
        assert alpha_go["alpha.proto"] == "github.com/x/alpha"
        assert beta_go["beta.proto"] == "github.com/x/beta"

    def test_single_file_package(self, tmp_path: Path) -> None:
        """One .proto in a package → per-attr map has exactly one entry."""
        _write_proto(
            tmp_path, "solo.proto",
            'syntax = "proto3";\n'
            'package u4a.scenarios.solo;\n'
            'option go_package = "github.com/x/solo";\n'
            'message SoloStub {}\n',
        )
        result = compile_protos_to_result([tmp_path / "solo.proto"])
        captured: list[Any] = []
        self._capture(result, captured)
        pkg_opts = captured[0]

        per_pkg = pkg_opts["u4a.scenarios.solo"]
        go_pkg = per_pkg["go_package"]
        assert list(go_pkg.keys()) == ["solo.proto"], (
            f"single-file package's per-attr map must have exactly one "
            f"key; got {list(go_pkg.keys())}"
        )
        assert go_pkg["solo.proto"] == "github.com/x/solo"

    def test_all_omit(self, tmp_path: Path) -> None:
        """All files in a package omit go_package → every value is None."""
        # 3 files, none declare go_package.
        _write_proto(
            tmp_path, "x.proto",
            'syntax = "proto3";\n'
            'package u4a.scenarios.allomit;\n'
            'message X {}\n',
        )
        _write_proto(
            tmp_path, "y.proto",
            'syntax = "proto3";\n'
            'package u4a.scenarios.allomit;\n'
            'message Y {}\n',
        )
        _write_proto(
            tmp_path, "z.proto",
            'syntax = "proto3";\n'
            'package u4a.scenarios.allomit;\n'
            'message Z {}\n',
        )
        result = compile_protos_to_result(
            [tmp_path / "x.proto", tmp_path / "y.proto", tmp_path / "z.proto"],
        )
        captured: list[Any] = []
        self._capture(result, captured)
        pkg_opts = captured[0]

        go_pkg = pkg_opts["u4a.scenarios.allomit"]["go_package"]
        assert set(go_pkg.keys()) == {"x.proto", "y.proto", "z.proto"}
        assert all(v is None for v in go_pkg.values()), (
            f"all-omit scenario should have every per-file value None; "
            f"got {dict(go_pkg)}"
        )

    def test_all_same(self, tmp_path: Path) -> None:
        """All files declare the same value → accumulator captures uniformly."""
        for fname in ("p.proto", "q.proto", "r.proto"):
            _write_proto(
                tmp_path, fname,
                f'syntax = "proto3";\n'
                f'package u4a.scenarios.allsame;\n'
                f'option go_package = "github.com/x/unified";\n'
                f'message {fname[0].upper()} {{}}\n',
            )
        result = compile_protos_to_result(
            [tmp_path / "p.proto", tmp_path / "q.proto", tmp_path / "r.proto"],
        )
        captured: list[Any] = []
        self._capture(result, captured)
        pkg_opts = captured[0]

        go_pkg = pkg_opts["u4a.scenarios.allsame"]["go_package"]
        assert set(go_pkg.values()) == {"github.com/x/unified"}, (
            f"all-same scenario should have one distinct value; "
            f"got {set(go_pkg.values())}"
        )
        # U4b R7 rule will treat this as the clean-pass case (no finding).

    def test_transitive_import_contribution(self, tmp_path: Path) -> None:
        """Transitively-imported file contributes to its package's entry.

        Root: root.proto in package u4a.scenarios.transitive_root,
        imports dep.proto.
        Dep: dep.proto in package u4a.scenarios.transitive_dep (different
        package), declares its own go_package.

        Even though dep.proto is NOT a root, the pre-walk must include
        its package's accumulator entry because the pool contains dep.
        Validates the load-bearing 'pool-driven, not root-driven' design.
        """
        proto_dir = tmp_path / "transitive_scenario"
        proto_dir.mkdir(parents=True, exist_ok=True)
        _write_proto(
            proto_dir, "dep.proto",
            'syntax = "proto3";\n'
            'package u4a.scenarios.transitive_dep;\n'
            'option go_package = "github.com/x/dep";\n'
            'message DepStub {}\n',
        )
        _write_proto(
            proto_dir, "root.proto",
            'syntax = "proto3";\n'
            'package u4a.scenarios.transitive_root;\n'
            'import "dep.proto";\n'
            'option go_package = "github.com/x/root";\n'
            'message RootStub { u4a.scenarios.transitive_dep.DepStub d = 1; }\n',
        )
        result = compile_protos_to_result(
            [proto_dir / "root.proto"],
            proto_paths=(str(proto_dir),),
        )
        # root_files contains only root.proto; pool_file_names also has dep.
        assert result.root_files == ("root.proto",)
        assert "dep.proto" in result.pool_file_names

        captured: list[Any] = []
        self._capture(result, captured)
        pkg_opts = captured[0]

        # BOTH packages appear in the accumulator (transitive contributes).
        assert "u4a.scenarios.transitive_root" in pkg_opts
        assert "u4a.scenarios.transitive_dep" in pkg_opts, (
            f"transitive dep's package must appear in accumulator; got "
            f"{set(pkg_opts.keys())}"
        )
        # dep's package entry has dep's go_package value.
        dep_go = pkg_opts["u4a.scenarios.transitive_dep"]["go_package"]
        assert dep_go == {"dep.proto": "github.com/x/dep"}


class TestLowercaseBoolRendering:
    """``java_multiple_files`` captured as lowercase string ``"true"`` / ``"false"``."""

    def test_java_multiple_files_true_captured_as_lowercase(
        self, tmp_path: Path,
    ) -> None:
        """``option java_multiple_files = true;`` → ``"true"`` (NOT ``"True"``)."""
        proto = _write_proto(
            tmp_path, "u.proto",
            'syntax = "proto3";\n\n'
            'package u4a.bool_lower;\n\n'
            'option java_multiple_files = true;\n\n'
            'message U {}\n',
        )
        # Need 2+ files for the package_options dict to actually populate
        # the attr per the engine pre-walk semantics — but the per-attr
        # dict captures every file regardless.
        proto_b = _write_proto(
            tmp_path, "v.proto",
            'syntax = "proto3";\n\n'
            'package u4a.bool_lower;\n\n'
            'option java_multiple_files = false;\n\n'
            'message V {}\n',
        )
        result = compile_protos_to_result([proto, proto_b])

        captured: list[Any] = []
        rule_id = "u4a/capture-bool"
        pack = _make_capture_pack("u4a-capture-bool", rule_id, captured)
        engine = LintEngine()
        engine.load_rule_pack(pack)
        profile = LintProfile(
            name="u4a-capture-bool",
            min_severity=LintSeverity.INFO,
            rule_ids=frozenset({rule_id}),
        )
        engine.run(result, profile=profile)

        per_pkg = captured[0]["u4a.bool_lower"]
        per_attr = per_pkg["java_multiple_files"]
        # CRITICAL: lowercase, NOT Python title-case.
        assert per_attr["u.proto"] == "true"
        assert per_attr["v.proto"] == "false"


# ---- 3-level MappingProxyType immutability invariant ------------------------


class TestMappingProxyTypeInvariant:
    """``package_options`` is frozen at all 3 nesting depths."""

    def _populated_ctx(self, tmp_path: Path) -> Any:
        proto_dir = _three_files_same_package(tmp_path)
        result = compile_protos_to_result(
            [proto_dir / "a.proto", proto_dir / "b.proto", proto_dir / "c.proto"],
        )
        captured: list[Any] = []
        rule_id = "u4a/capture-immut"
        pack = _make_capture_pack("u4a-immut", rule_id, captured)
        engine = LintEngine()
        engine.load_rule_pack(pack)
        profile = LintProfile(
            name="u4a-immut",
            min_severity=LintSeverity.INFO,
            rule_ids=frozenset({rule_id}),
        )
        engine.run(result, profile=profile)
        return captured[0]

    def test_outer_mutation_raises_type_error(self, tmp_path: Path) -> None:
        """Level 1: ``pkg_opts[new_pkg] = {}`` raises ``TypeError``."""
        pkg_opts = self._populated_ctx(tmp_path)
        with pytest.raises(TypeError):
            pkg_opts["new.package"] = {}  # type: ignore[index]

    def test_per_package_mutation_raises_type_error(
        self, tmp_path: Path,
    ) -> None:
        """Level 2: ``pkg_opts[pkg][new_attr] = {}`` raises ``TypeError``."""
        pkg_opts = self._populated_ctx(tmp_path)
        per_pkg = pkg_opts["u4a.engine_pre_walk"]
        with pytest.raises(TypeError):
            per_pkg["new_attr"] = {}  # type: ignore[index]

    def test_per_attr_mutation_raises_type_error(self, tmp_path: Path) -> None:
        """Level 3: ``pkg_opts[pkg][attr][new_file] = "X"`` raises ``TypeError``."""
        pkg_opts = self._populated_ctx(tmp_path)
        per_pkg = pkg_opts["u4a.engine_pre_walk"]
        per_attr = per_pkg["go_package"]
        with pytest.raises(TypeError):
            per_attr["new.proto"] = "X"  # type: ignore[index]

    def test_outer_is_mapping_proxy(self, tmp_path: Path) -> None:
        """Outer wrapper is a ``MappingProxyType`` instance."""
        pkg_opts = self._populated_ctx(tmp_path)
        assert isinstance(pkg_opts, MappingProxyType)


# ---- Structural pin via inspect.getsource -----------------------------------


class TestStructuralPin:
    """Engine source contains the load-bearing pre-walk patterns."""

    def _engine_source(self) -> str:
        """Concatenated source: ``run`` + the factored pre-walk helper.

        The pre-walk implementation lives in
        :meth:`LintEngine._build_package_options_accumulator`; ``run()``
        invokes it before Step 4. Pinning across both methods locks the
        architectural decisions regardless of where the helper boundary
        sits.
        """
        return (
            inspect.getsource(LintEngine.run)
            + "\n# --- helper boundary ---\n"
            + inspect.getsource(LintEngine._build_package_options_accumulator)
        )

    def test_pre_walk_uses_pool_file_names_sorted_by_posixpath_basename(
        self,
    ) -> None:
        """Sorted iteration over ``pool_file_names`` with ``posixpath.basename`` key."""
        source = self._engine_source()
        # Pin the load-bearing pre-walk substrings (live in the helper).
        assert "compile_result.pool_file_names" in source
        assert "posixpath.basename" in source
        # The sorted iteration MUST happen on pool_file_names.
        assert "sorted(" in source
        # No WKT filter — verify ``_WKT_PATH_PREFIX`` is NOT introduced as a
        # gating substring (filter dropped per the empirical wkt-conflict
        # evidence; this assertion catches accidental re-introduction).
        assert "_WKT_PATH_PREFIX" not in source

    def test_pre_walk_precedes_step_4_root_files_walk(self) -> None:
        """``run()`` invokes the pre-walk helper BEFORE Step 4's root_files walk.

        ce:review follow-up (Finding #14 / Testing T-6): regex-based
        match (whitespace-tolerant) instead of the previous exact
        16-space-indented substring, so a non-behavioral reformatter
        run cannot break this ordering pin. The ordering invariant
        itself (pre-walk before Step 4) is what we lock — not the
        formatter's choice of indentation.
        """
        import re

        run_source = inspect.getsource(LintEngine.run)
        pre_walk_call_pos = run_source.find(
            "_build_package_options_accumulator"
        )
        # Match `for fname in sorted(` followed by any whitespace then
        # `compile_result.root_files`. Tolerates one-line, multi-line,
        # and varying indentation while still anchoring on the Step 4
        # walk signature (distinguishes it from the docstring earlier
        # in the method that mentions `compile_result.root_files` in
        # prose).
        step_4_match = re.search(
            r"for\s+fname\s+in\s+sorted\(\s*compile_result\.root_files",
            run_source,
        )
        assert pre_walk_call_pos != -1, (
            "run() must invoke _build_package_options_accumulator"
        )
        assert step_4_match is not None, (
            "Step 4's `for fname in sorted(compile_result.root_files, ...)` "
            "walk pattern not found in run() source"
        )
        assert pre_walk_call_pos < step_4_match.start(), (
            "pre-walk helper call must precede Step 4's root_files walk"
        )

    def test_pre_walk_uses_defensive_try_except_keyerror(self) -> None:
        """``try/except KeyError: continue`` mirrors Step 4 pattern.

        Both Step 3.5 (in the helper) and Step 4 (in ``run``) use the
        same defensive idiom; combined source contains 2+ occurrences.
        """
        source = self._engine_source()
        assert source.count("except KeyError:") >= 2


# ---- Sanitizer quote-character round-trip (Step 10 verification) ------------


class TestSanitizerQuoteCharacterRoundTrip:
    """``_safe_for_stderr`` passes ``"`` through unchanged.

    Load-bearing for U4b's helper architecture: the helper escapes inner
    quotes as ``\\"`` via ``value.replace('"', '\\"')`` per declared value
    before composition (per ``_buf_smoke/recorded/mixed-value-with-inner-quote.json``).
    If the sanitizer also escaped or stripped quotes, the helper's
    explicit escape would compound or fail. This test pins the sanitizer's
    pass-through contract so U4b can rely on it.
    """

    def test_safe_for_stderr_preserves_double_quote(self) -> None:
        assert _safe_for_stderr('foo"bar') == 'foo"bar'

    def test_safe_for_stderr_preserves_multiple_quotes(self) -> None:
        assert _safe_for_stderr('"X","Y","Z"') == '"X","Y","Z"'

    def test_safe_for_stderr_preserves_backslash_quote_sequence(self) -> None:
        """Pre-escaped ``\\"`` sequence survives sanitization."""
        assert _safe_for_stderr('X\\"quoted') == 'X\\"quoted'


# ---- Benchmark gate (SC E7: <50ms on 1K-file fixture) ----------------------


class TestPreWalkBenchmark:
    """Pre-walk completes under the SC E7 threshold on a 1K-file fixture.

    ce:review follow-up (Finding #5 / PERF-2 + PERF-3 + Testing T-7):
    split into two assertions. The plan's SC E7 target (<50ms) applies
    specifically to the pre-walk accumulator build — NOT to full
    ``engine.run`` (which also walks 1000 root files for the capture
    rule dispatch). Measuring only ``engine.run`` conflated pre-walk
    cost with per-file rule dispatch, so a 30ms→180ms pre-walk
    regression could pass silently under a 200ms full-envelope ceiling.
    Now: ``test_pre_walk_isolated_under_50ms_on_1k_file_fixture``
    asserts the plan target directly against
    ``_build_package_options_accumulator``; the legacy full-envelope
    assertion is renamed and retained at a documented CI-headroom
    ceiling. Both use warmup + median-of-3 for stability against OS
    scheduling jitter (single-shot timing was previously susceptible).
    """

    @staticmethod
    def _make_1k_fixture(tmp_path: Path) -> tuple[Path, ...]:
        """Generate 1000 .proto files in 100 packages."""
        for pkg_idx in range(100):
            pkg = f"u4a.benchmark.pkg{pkg_idx}"
            for file_idx in range(10):
                name = f"pkg{pkg_idx}/f{file_idx}.proto"
                go_pkg = f"github.com/bench/p{pkg_idx}/f{file_idx}"
                _write_proto(
                    tmp_path, name,
                    f'syntax = "proto3";\n\n'
                    f'package {pkg};\n\n'
                    f'option go_package = "{go_pkg}";\n\n'
                    f'message Stub{file_idx} {{}}\n',
                )
        paths = tuple(sorted(tmp_path.rglob("*.proto")))
        assert len(paths) == 1000, f"expected 1000 fixtures, got {len(paths)}"
        return paths

    @staticmethod
    def _median_of_3_ms(fn: Any) -> float:
        """Run ``fn`` once for warmup + 3 timed iterations, return median ms."""
        fn()  # warmup — primes pool caches + lazy imports
        timings_ms: list[float] = []
        for _ in range(3):
            start = time.perf_counter()
            fn()
            timings_ms.append((time.perf_counter() - start) * 1000)
        timings_ms.sort()
        return timings_ms[1]  # median

    @pytest.mark.slow
    def test_pre_walk_isolated_under_50ms_on_1k_file_fixture(
        self, tmp_path: Path,
    ) -> None:
        """Pre-walk accumulator build alone < 50ms (plan SC E7).

        Measures ``_build_package_options_accumulator`` in isolation,
        not via ``engine.run`` — separates pre-walk cost from per-file
        rule dispatch so a regression in EITHER component is caught
        individually. Plan SC E7's <50ms target applies here.
        """
        paths = self._make_1k_fixture(tmp_path)
        result = compile_protos_to_result(list(paths))
        engine = LintEngine()

        elapsed_ms = self._median_of_3_ms(
            lambda: engine._build_package_options_accumulator(result),
        )

        # Plan SC E7: <50ms on 1K files. If CI runners consistently
        # exceed this, surface it via an issue + the deferred-D6c
        # lazy-gating discussion — do NOT silently raise the ceiling.
        assert elapsed_ms < 50, (
            f"_build_package_options_accumulator on 1K-file fixture "
            f"took {elapsed_ms:.1f}ms (median of 3); plan SC E7 target "
            f"is <50ms. Investigate before relaxing the ceiling: either "
            f"the pre-walk has a real regression or it's time to revisit "
            f"the deferred-D6c lazy-gating discussion."
        )

    @pytest.mark.slow
    def test_engine_run_under_200ms_on_1k_file_fixture(
        self, tmp_path: Path,
    ) -> None:
        """Full ``engine.run`` envelope < 200ms (CI-headroom ceiling).

        Includes pre-walk + Step 4 per-file walk + 1000 capture-rule
        invocations. NOT the SC E7 target (that's the isolated
        pre-walk above); this is a sanity envelope so a per-file
        regression in Step 4 dispatch doesn't slip past the smaller
        SC E7 gate.
        """
        paths = self._make_1k_fixture(tmp_path)
        result = compile_protos_to_result(list(paths))

        rule_id = "u4a/bench"
        ignored: list[Any] = []
        pack = _make_capture_pack("u4a-bench", rule_id, ignored)
        engine = LintEngine()
        engine.load_rule_pack(pack)
        profile = LintProfile(
            name="u4a-bench",
            min_severity=LintSeverity.INFO,
            rule_ids=frozenset({rule_id}),
        )

        elapsed_ms = self._median_of_3_ms(
            lambda: engine.run(result, profile=profile),
        )

        assert elapsed_ms < 200, (
            f"engine.run on 1K-file fixture took {elapsed_ms:.1f}ms "
            f"(median of 3); full-envelope ceiling is 200ms (includes "
            f"pre-walk + 1000 capture-rule dispatches). The isolated "
            f"SC E7 pre-walk gate catches pre-walk-only regressions; "
            f"this gate catches per-file dispatch regressions."
        )
