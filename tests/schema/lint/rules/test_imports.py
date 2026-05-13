"""Tests for the D6a Unit 5 imports-discipline rule pack.

Covers the 3 rules registered in :mod:`protokit.schema.lint.rules.imports`:

- ``imports/no-public`` — fires for each ``import public "...";``
- ``imports/no-weak`` — fires for each ``import weak "...";``
- ``imports/unused`` — fires for each ordinary import whose types
  the file does not reference (skips public + weak; mirrors buf's
  IMPORT_USED).

Patterns mirror ``tests/schema/lint/rules/test_enum.py``: shared
``_compile`` + ``_run_single`` from conftest, derived
``_ALL_IMPORTS_RULE_IDS`` frozenset, per-rule TestClasses with
isolation profiles, profile-membership tests, and a full-pack
integration test that fires every rule on a deliberately-bad
multi-file fixture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import imports as imports_pack
from protokit.schema.lint.rules.imports import (
    RULES,
    check_no_public_imports,
    check_no_weak_imports,
    check_unused_imports,
)

from .conftest import _compile
from .conftest import _run_single as _run_single_with_pack


def _run_single(
    tmp_path: Path,
    sources: dict[str, str],
    rule_id: str,
) -> Any:
    """Thin wrapper that fixes the pack to ``imports`` for this file's tests."""
    return _run_single_with_pack(tmp_path, sources, rule_id, imports_pack)


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata
# ---------------------------------------------------------------------------


class TestImportsPackShape:
    """The imports pack exposes RULES with all 3 D6a Unit 5 rules registered."""

    def test_rules_tuple_contains_three_callables(self) -> None:
        assert isinstance(RULES, tuple)
        assert len(RULES) == 3
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_pack_includes_all_three_rules(self) -> None:
        assert check_no_public_imports in RULES
        assert check_no_weak_imports in RULES
        assert check_unused_imports in RULES


class TestImportsRuleSpecs:
    """The 3 new rules carry the D6a Unit 5 spec metadata."""

    def test_no_public_spec(self) -> None:
        spec = check_no_public_imports._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "imports/no-public"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:IMPORT_NO_PUBLIC"

    def test_no_weak_spec(self) -> None:
        spec = check_no_weak_imports._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "imports/no-weak"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:IMPORT_NO_WEAK"

    def test_unused_spec(self) -> None:
        spec = check_unused_imports._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "imports/unused"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:IMPORT_USED"


# ---------------------------------------------------------------------------
# Shared proto2 helper fixtures — proto2 because `import public`/`weak`
# are practically proto2 idioms (proto3 syntactically accepts them but
# they're discouraged in modern proto3 codebases).
# ---------------------------------------------------------------------------


_FOO_PROTO2 = """
syntax = "proto2";
package foo;
message Foo { optional string name = 1; }
"""

_BAZ_PROTO2 = """
syntax = "proto2";
package baz;
message Baz { optional string x = 1; }
"""


# ---------------------------------------------------------------------------
# imports/no-public
# ---------------------------------------------------------------------------


_NO_PUBLIC_GOOD = """
syntax = "proto2";
package bar;
import "foo.proto";
message Bar { optional foo.Foo f = 1; }
"""

_NO_PUBLIC_BAD = """
syntax = "proto2";
package bar;
import public "foo.proto";
message Bar { optional foo.Foo f = 1; }
"""

_NO_PUBLIC_MULTIPLE_BAD = """
syntax = "proto2";
package bar;
import public "foo.proto";
import public "baz.proto";
message Bar { optional foo.Foo f = 1; optional baz.Baz b = 2; }
"""


class TestNoPublicImports:
    """``imports/no-public`` fires once per ``import public`` declaration."""

    def test_happy_path_normal_import_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _NO_PUBLIC_GOOD},
            "imports/no-public",
        )
        assert report.findings == ()

    def test_sad_path_single_public_import_fires_once(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _NO_PUBLIC_BAD},
            "imports/no-public",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "imports/no-public"
        assert f.params == {"imported": "foo.proto"}

    def test_sad_path_multiple_public_imports_fire_per_import(
        self, tmp_path: Path,
    ) -> None:
        """Per-import fan-out: N findings for N public imports."""
        report = _run_single(
            tmp_path,
            {
                "foo.proto": _FOO_PROTO2,
                "baz.proto": _BAZ_PROTO2,
                "bar.proto": _NO_PUBLIC_MULTIPLE_BAD,
            },
            "imports/no-public",
        )
        assert len(report.findings) == 2
        offenders = {f.params["imported"] for f in report.findings}
        assert offenders == {"foo.proto", "baz.proto"}


# ---------------------------------------------------------------------------
# imports/no-weak
# ---------------------------------------------------------------------------


_NO_WEAK_BAD = """
syntax = "proto2";
package bar;
import weak "foo.proto";
message Bar { optional string x = 1; }
"""

_NO_WEAK_MULTIPLE_BAD = """
syntax = "proto2";
package bar;
import weak "foo.proto";
import weak "baz.proto";
message Bar { optional string x = 1; }
"""


class TestNoWeakImports:
    """``imports/no-weak`` fires once per ``import weak`` declaration."""

    def test_happy_path_no_weak_import_clean(self, tmp_path: Path) -> None:
        # Reuse the no-public happy fixture — it has only an ordinary
        # import, so no-weak should not fire on it.
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _NO_PUBLIC_GOOD},
            "imports/no-weak",
        )
        assert report.findings == ()

    def test_sad_path_weak_import_fires(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _NO_WEAK_BAD},
            "imports/no-weak",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "imports/no-weak"
        assert f.params == {"imported": "foo.proto"}

    def test_sad_path_multiple_weak_imports_fire_per_import(
        self, tmp_path: Path,
    ) -> None:
        """Per-import fan-out: N findings for N weak imports.

        Symmetric with ``test_sad_path_multiple_public_imports_fire_per_import``
        on the no-public side — the per-offender fan-out shape is
        identical for both index arrays.
        """
        report = _run_single(
            tmp_path,
            {
                "foo.proto": _FOO_PROTO2,
                "baz.proto": _BAZ_PROTO2,
                "bar.proto": _NO_WEAK_MULTIPLE_BAD,
            },
            "imports/no-weak",
        )
        assert len(report.findings) == 2
        offenders = {f.params["imported"] for f in report.findings}
        assert offenders == {"foo.proto", "baz.proto"}


# ---------------------------------------------------------------------------
# imports/unused
# ---------------------------------------------------------------------------


# Happy: import is used via a message-field type reference.
_UNUSED_GOOD_FIELD_REF = """
syntax = "proto3";
package bar;
import "foo.proto";
message Bar { foo.Foo f = 1; }
"""

# Happy: import is used via a method input/output type.
_UNUSED_GOOD_SERVICE_REF = """
syntax = "proto3";
package bar;
import "foo.proto";
service BarService {
  rpc Echo (foo.Foo) returns (foo.Foo);
}
"""

# Happy: import is used via an enum-field type.
_FOO_PROTO3_WITH_ENUM = """
syntax = "proto3";
package foo;
enum Status { STATUS_UNSPECIFIED = 0; STATUS_ACTIVE = 1; }
message Foo { Status s = 1; }
"""

_UNUSED_GOOD_ENUM_REF = """
syntax = "proto3";
package bar;
import "foo.proto";
message Bar { foo.Status s = 1; }
"""

# Sad: import is declared but no type from it is referenced.
_UNUSED_BAD = """
syntax = "proto3";
package bar;
import "foo.proto";
message Bar { string x = 1; }
"""

# Sad: import is declared and only used by a sibling import — direct
# import is still unused locally. This pins the "direct only, not
# transitive" buf semantics.
_UNUSED_BAD_TRANSITIVE_DOES_NOT_RESCUE = """
syntax = "proto3";
package bar;
import "foo.proto";
import "baz.proto";
message Bar { baz.Baz b = 1; }
"""

_BAZ_PROTO3 = """
syntax = "proto3";
package baz;
message Baz { string x = 1; }
"""

# Edge: public import — skipped from unused check even if locally
# unreferenced (intentional re-export per buf semantics).
_UNUSED_PUBLIC_NOT_FLAGGED = """
syntax = "proto3";
package bar;
import public "foo.proto";
message Bar { string x = 1; }
"""

# Edge: weak import — skipped from unused check even if locally
# unreferenced (compat semantics per buf).
_UNUSED_WEAK_NOT_FLAGGED = """
syntax = "proto2";
package bar;
import weak "foo.proto";
message Bar { optional string x = 1; }
"""

# Edge: well-known import treated same as user import per buf;
# unused well-known still fires.
_UNUSED_WKT_UNUSED = """
syntax = "proto3";
package bar;
import "google/protobuf/timestamp.proto";
message Bar { string x = 1; }
"""

_UNUSED_WKT_USED = """
syntax = "proto3";
package bar;
import "google/protobuf/timestamp.proto";
message Bar { google.protobuf.Timestamp t = 1; }
"""

# Edge: nested message uses the imported type — the walker must
# recurse into nested_types to detect this.
_UNUSED_GOOD_NESTED_REF = """
syntax = "proto3";
package bar;
import "foo.proto";
message Bar {
  message Inner { foo.Foo f = 1; }
  Inner i = 1;
}
"""

# Edge: map field with imported message-type value — the walker must
# recurse into the synthetic ``<FieldName>Entry`` nested message that
# the compiler generates for the map, find its value-type field, and
# record the value type's file. Pins the docstring claim that map
# fields are covered transitively via nested_types.
_UNUSED_GOOD_MAP_REF = """
syntax = "proto3";
package bar;
import "foo.proto";
message Bar { map<string, foo.Foo> items = 1; }
"""

# Sad path with a proto2 importer — cross-syntax verification that
# fdp.dependency is populated identically on both syntaxes. (All other
# imports/unused sad-path fixtures use proto3 as the importer.)
_UNUSED_BAD_PROTO2 = """
syntax = "proto2";
package bar;
import "foo.proto";
message Bar { optional string x = 1; }
"""


class TestUnusedImports:
    """``imports/unused`` fires on declared-but-unreferenced direct imports."""

    def test_happy_path_field_reference_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _UNUSED_GOOD_FIELD_REF},
            "imports/unused",
        )
        assert report.findings == ()

    def test_happy_path_service_method_reference_clean(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _UNUSED_GOOD_SERVICE_REF},
            "imports/unused",
        )
        assert report.findings == ()

    def test_happy_path_enum_field_reference_clean(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {
                "foo.proto": _FOO_PROTO3_WITH_ENUM,
                "bar.proto": _UNUSED_GOOD_ENUM_REF,
            },
            "imports/unused",
        )
        assert report.findings == ()

    def test_happy_path_nested_message_reference_clean(
        self, tmp_path: Path,
    ) -> None:
        """Nested types must be walked recursively to catch the reference."""
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _UNUSED_GOOD_NESTED_REF},
            "imports/unused",
        )
        assert report.findings == ()

    def test_happy_path_map_field_reference_clean(
        self, tmp_path: Path,
    ) -> None:
        """Map fields cover the import via the synthetic <Field>Entry walk.

        Pins the docstring claim that ``map<K, V> field = N;``
        compiles to a nested ``<FieldName>Entry`` message whose
        value field references the imported V type. The walker's
        ``nested_types`` recursion must see the synthetic Entry,
        walk its fields, and record the V type's file as used.
        Without that path, the import is wrongly flagged.
        """
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _UNUSED_GOOD_MAP_REF},
            "imports/unused",
        )
        assert report.findings == ()

    def test_sad_path_proto2_unreferenced_import_fires(
        self, tmp_path: Path,
    ) -> None:
        """Cross-syntax verification: CopyToProto's fdp.dependency is
        populated identically for proto2 and proto3 importing files,
        so the rule fires the same way regardless of importer syntax.
        """
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _UNUSED_BAD_PROTO2},
            "imports/unused",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "imports/unused"
        assert f.params == {"imported": "foo.proto"}

    def test_sad_path_unreferenced_import_fires(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _UNUSED_BAD},
            "imports/unused",
        )
        assert len(report.findings) == 1
        f = report.findings[0]
        assert f.violation_kind == "imports/unused"
        assert f.params == {"imported": "foo.proto"}

    def test_sad_path_only_sibling_import_used(self, tmp_path: Path) -> None:
        """Pins direct-only semantics (matches buf IMPORT_USED)."""
        report = _run_single(
            tmp_path,
            {
                "foo.proto": _FOO_PROTO2,
                "baz.proto": _BAZ_PROTO3,
                "bar.proto": _UNUSED_BAD_TRANSITIVE_DOES_NOT_RESCUE,
            },
            "imports/unused",
        )
        # baz.proto is used (Baz field); foo.proto is the offender.
        offenders = {f.params["imported"] for f in report.findings}
        assert offenders == {"foo.proto"}

    def test_public_import_skipped_from_unused_check(
        self, tmp_path: Path,
    ) -> None:
        """Public imports re-export; locally unreferenced is intentional."""
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _UNUSED_PUBLIC_NOT_FLAGGED},
            "imports/unused",
        )
        assert report.findings == ()

    def test_weak_import_skipped_from_unused_check(
        self, tmp_path: Path,
    ) -> None:
        """Weak imports are compat-mode; locally unreferenced is acceptable."""
        report = _run_single(
            tmp_path,
            {"foo.proto": _FOO_PROTO2, "bar.proto": _UNUSED_WEAK_NOT_FLAGGED},
            "imports/unused",
        )
        assert report.findings == ()

    def test_unused_well_known_import_fires(self, tmp_path: Path) -> None:
        """Buf treats WKTs like user imports — unused WKT still fires."""
        report = _run_single(
            tmp_path,
            {"bar.proto": _UNUSED_WKT_UNUSED},
            "imports/unused",
        )
        offenders = {f.params["imported"] for f in report.findings}
        assert offenders == {"google/protobuf/timestamp.proto"}

    def test_used_well_known_import_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"bar.proto": _UNUSED_WKT_USED},
            "imports/unused",
        )
        assert report.findings == ()


# ---------------------------------------------------------------------------
# Profile membership — derived from RULES so future additions auto-update
# ---------------------------------------------------------------------------


_ALL_IMPORTS_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)


class TestImportsProfileMembership:
    """``LintProfile.from_pack`` returns the expected rule_id sets."""

    def test_from_pack_recommended_contains_all_three_rules(self) -> None:
        profile = LintProfile.from_pack(imports_pack, "recommended")
        assert profile.name == "recommended"
        assert profile.rule_ids == _ALL_IMPORTS_RULE_IDS

    def test_from_pack_default_contains_all_three_rules(self) -> None:
        profile = LintProfile.from_pack(imports_pack, "default")
        assert profile.name == "default"
        assert profile.rule_ids == _ALL_IMPORTS_RULE_IDS

    def test_from_pack_essentials_contains_no_imports_rules(self) -> None:
        profile = LintProfile.from_pack(imports_pack, "essentials")
        assert profile.rule_ids == frozenset()

    def test_from_pack_unknown_profile_returns_empty(self) -> None:
        profile = LintProfile.from_pack(imports_pack, "nonexistent")
        assert profile.rule_ids == frozenset()


# ---------------------------------------------------------------------------
# Integration — all 3 rules fire on a deliberately-bad fixture
# ---------------------------------------------------------------------------


# A proto2 file that violates all three rules at once: a public
# import, a weak import, and an ordinary import that's not used.
_TRIPLE_BAD_FIXTURE = """
syntax = "proto2";
package badtriple;
import public "foo.proto";
import weak "baz.proto";
import "qux.proto";
message Triple { optional string x = 1; }
"""

_QUX_PROTO2 = """
syntax = "proto2";
package qux;
message Qux { optional string n = 1; }
"""


class TestImportsPackIntegration:
    """All 3 imports rules fire on a fixture violating each."""

    def test_recommended_profile_fires_all_three_imports_rules(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(
            tmp_path,
            {
                "foo.proto": _FOO_PROTO2,
                "baz.proto": _BAZ_PROTO2,
                "qux.proto": _QUX_PROTO2,
                "triple.proto": _TRIPLE_BAD_FIXTURE,
            },
        )
        engine = LintEngine()
        engine.load_rule_pack(imports_pack)
        profile = LintProfile.from_pack(imports_pack, "recommended")
        report = engine.run(result, profile=profile)
        # Exactly 3 findings expected: 1 per rule on the triple.proto file.
        # (The other files are clean: foo/baz/qux declare no imports.)
        assert len(report.findings) == 3
        fired_rule_ids = {f.rule_id for f in report.findings}
        assert fired_rule_ids == _ALL_IMPORTS_RULE_IDS
