"""Tests for the D6a Unit 3 naming-family extensions.

Covers the 8 new naming rules registered in the ``naming`` rule pack
plus the widened profile membership of the existing
``naming/snake-case-fields`` canary. Patterns follow
``tests/schema/lint/test_canary_naming.py``: module-level proto
fixtures, ``_compile`` helper, and class-based organization
(``TestPackShape`` / per-rule happy + sad / ``TestProfileMembership``
/ ``TestFromPack``).

Each rule's happy and sad paths use a single-rule profile so other
rules in the pack do not contribute findings to the assertion under
test — this keeps the per-rule sad-path tests focused on the rule's
own violations rather than coupling them to peer-rule behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import ElementKind, LintProfile, LintSeverity
from protokit.schema.lint.rules import naming as naming_pack
from protokit.schema.lint.rules.naming import (
    RULES,
    check_pascal_case_enums,
    check_pascal_case_messages,
    check_pascal_case_rpcs,
    check_pascal_case_services,
    check_snake_case_fields,
    check_snake_case_files,
    check_snake_case_oneofs,
    check_snake_case_packages,
    check_upper_snake_case_enum_values,
)

# ---------------------------------------------------------------------------
# Shared compile + engine helpers
# ---------------------------------------------------------------------------


def _compile(
    tmp_path: Path,
    sources: dict[str, str],
) -> Any:
    """Write ``sources`` under ``tmp_path`` and compile them.

    Keys may include POSIX-style subdirectory segments
    (``"acme/v1/users.proto"``); the helper creates the parent
    directories as needed. Returns a ``CompileResult``.
    """
    paths: list[Path] = []
    for fname, text in sources.items():
        p = tmp_path / fname
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        paths.append(p)
    return compile_protos_to_result(
        paths=paths,
        proto_paths=(str(tmp_path),),
    )


def _run_single(
    tmp_path: Path,
    sources: dict[str, str],
    rule_id: str,
) -> Any:
    """Run the engine with a profile containing only ``rule_id``.

    Returns the ``LintReport``. The profile uses ``INFO`` min-severity
    so the test exercises emission rather than the severity-gate logic
    (which has its own dedicated tests).
    """
    result = _compile(tmp_path, sources)
    engine = LintEngine()
    engine.load_rule_pack(naming_pack)
    profile = LintProfile(
        name="default",
        rule_ids=frozenset({rule_id}),
        min_severity=LintSeverity.INFO,
    )
    return engine.run(result, profile=profile)


# ---------------------------------------------------------------------------
# Module shape — RULES tuple + spec metadata for the 8 new rules
# ---------------------------------------------------------------------------


class TestNamingPackShape:
    """The naming pack exposes RULES with all D6a Unit 3 rules registered."""

    def test_rules_tuple_contains_nine_callables(self) -> None:
        """RULES grew from 1 (canary) to 9 (canary + 8 new in D6a Unit 3)."""
        assert isinstance(RULES, tuple)
        assert len(RULES) == 9
        for fn in RULES:
            assert hasattr(fn, "_lint_spec")

    def test_pack_includes_all_d6a_unit3_rules(self) -> None:
        """Every new rule's decorated callable is listed in RULES."""
        assert check_snake_case_fields in RULES
        assert check_pascal_case_messages in RULES
        assert check_pascal_case_enums in RULES
        assert check_upper_snake_case_enum_values in RULES
        assert check_snake_case_oneofs in RULES
        assert check_pascal_case_services in RULES
        assert check_pascal_case_rpcs in RULES
        assert check_snake_case_files in RULES
        assert check_snake_case_packages in RULES


class TestNewRuleSpecs:
    """The 8 new rules carry the D6a Unit 3 spec metadata.

    All new rules share ``severity=ERROR``,
    ``profiles=("recommended", "default")``, and a
    ``source_spec`` of the form ``"buf:<RULE_ID>"`` (R2 — buf parity
    self-documentation at the spec level).
    """

    def test_pascal_case_messages_spec(self) -> None:
        spec = check_pascal_case_messages._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/pascal-case-messages"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.MESSAGE
        assert spec.source_spec == "buf:MESSAGE_PASCAL_CASE"

    def test_pascal_case_enums_spec(self) -> None:
        spec = check_pascal_case_enums._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/pascal-case-enums"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.ENUM
        assert spec.source_spec == "buf:ENUM_PASCAL_CASE"

    def test_upper_snake_case_enum_values_spec(self) -> None:
        spec = check_upper_snake_case_enum_values._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/upper-snake-case-enum-values"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.ENUM_VALUE
        assert spec.source_spec == "buf:ENUM_VALUE_UPPER_SNAKE_CASE"

    def test_snake_case_oneofs_spec(self) -> None:
        spec = check_snake_case_oneofs._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/snake-case-oneofs"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.ONEOF
        assert spec.source_spec == "buf:ONEOF_LOWER_SNAKE_CASE"

    def test_pascal_case_services_spec(self) -> None:
        spec = check_pascal_case_services._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/pascal-case-services"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.SERVICE
        assert spec.source_spec == "buf:SERVICE_PASCAL_CASE"

    def test_pascal_case_rpcs_spec(self) -> None:
        spec = check_pascal_case_rpcs._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/pascal-case-rpcs"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.METHOD
        assert spec.source_spec == "buf:RPC_PASCAL_CASE"

    def test_snake_case_files_spec(self) -> None:
        spec = check_snake_case_files._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/snake-case-files"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:FILE_LOWER_SNAKE_CASE"

    def test_snake_case_packages_spec(self) -> None:
        spec = check_snake_case_packages._lint_spec  # type: ignore[attr-defined]
        assert spec.rule_id == "naming/snake-case-packages"
        assert spec.severity is LintSeverity.ERROR
        assert spec.profiles == ("recommended", "default")
        assert spec.element is ElementKind.FILE
        assert spec.source_spec == "buf:PACKAGE_LOWER_SNAKE_CASE"


# ---------------------------------------------------------------------------
# naming/pascal-case-messages
# ---------------------------------------------------------------------------


_PASCAL_MSG_GOOD = """
syntax = "proto3";
package good;

message User {}
message UserService {}
message A {}
message URL {}
"""

_PASCAL_MSG_BAD = """
syntax = "proto3";
package bad;

message userBad {}
message bad_message {}
message _Leading {}
"""

_MSG_WITH_MAP_FIELD = """
syntax = "proto3";
package mapfield;

message Settings {
  map<string, string> attributes = 1;
}
"""


class TestPascalCaseMessages:
    """``naming/pascal-case-messages`` fires on non-PascalCase messages."""

    def test_happy_path_pascal_case_messages_clean(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _PASCAL_MSG_GOOD},
            "naming/pascal-case-messages",
        )
        assert report.findings == ()

    def test_sad_path_non_pascal_messages_fire(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"bad.proto": _PASCAL_MSG_BAD},
            "naming/pascal-case-messages",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"userBad", "bad_message", "_Leading"}

    def test_map_entry_synthetic_message_skipped(
        self, tmp_path: Path,
    ) -> None:
        """Synthetic ``<Field>Entry`` map-entry messages do not fire.

        ``map<K, V> attributes`` synthesizes a nested
        ``AttributesEntry`` message with ``options.map_entry = true``.
        Per the rule's docstring, those synthetic types are skipped to
        keep the rule's correctness independent of compiler naming
        choices.
        """
        report = _run_single(
            tmp_path,
            {"mapfield.proto": _MSG_WITH_MAP_FIELD},
            "naming/pascal-case-messages",
        )
        assert report.findings == ()


# ---------------------------------------------------------------------------
# naming/pascal-case-enums
# ---------------------------------------------------------------------------


_PASCAL_ENUM_GOOD = """
syntax = "proto3";
package good;

enum Status {
  STATUS_UNSPECIFIED = 0;
}
enum URL {
  URL_UNSPECIFIED = 0;
}
"""

# proto3 requires enum value names to be unique within a file (not just
# within an enum), so the two bad enums use distinct ``_UNSPECIFIED``
# value prefixes to keep the compiler happy while still flexing two
# differently-shaped bad enum-type names.
_PASCAL_ENUM_BAD = """
syntax = "proto3";
package bad;

enum statusBad {
  STATUSBAD_UNSPECIFIED = 0;
}
enum status_other {
  STATUS_OTHER_UNSPECIFIED = 0;
}
"""


class TestPascalCaseEnums:
    """``naming/pascal-case-enums`` fires on non-PascalCase enum types."""

    def test_happy_path_pascal_enums_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _PASCAL_ENUM_GOOD},
            "naming/pascal-case-enums",
        )
        assert report.findings == ()

    def test_sad_path_non_pascal_enums_fire(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"bad.proto": _PASCAL_ENUM_BAD},
            "naming/pascal-case-enums",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"statusBad", "status_other"}


# ---------------------------------------------------------------------------
# naming/upper-snake-case-enum-values
# ---------------------------------------------------------------------------


_UPPER_SNAKE_GOOD = """
syntax = "proto3";
package good;

enum Status {
  STATUS_UNSPECIFIED = 0;
  STATUS_ACTIVE = 1;
  STATUS_V2 = 2;
}
"""

_UPPER_SNAKE_BAD = """
syntax = "proto3";
package bad;

enum Status {
  STATUS_UNSPECIFIED = 0;
  StatusActive = 1;
  STATUS_active = 2;
}
"""


class TestUpperSnakeCaseEnumValues:
    """``naming/upper-snake-case-enum-values`` fires on non-UPPER_SNAKE values."""

    def test_happy_path_upper_snake_values_clean(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _UPPER_SNAKE_GOOD},
            "naming/upper-snake-case-enum-values",
        )
        assert report.findings == ()

    def test_sad_path_mixed_case_values_fire(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"bad.proto": _UPPER_SNAKE_BAD},
            "naming/upper-snake-case-enum-values",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"StatusActive", "STATUS_active"}


# ---------------------------------------------------------------------------
# naming/snake-case-oneofs
# ---------------------------------------------------------------------------


_ONEOF_GOOD = """
syntax = "proto3";
package good;

message User {
  oneof contact {
    string email = 1;
    string phone = 2;
  }
  oneof primary_id {
    string username = 3;
    int64 user_id = 4;
  }
}
"""

_ONEOF_BAD = """
syntax = "proto3";
package bad;

message User {
  oneof Contact {
    string email = 1;
  }
  oneof primaryId {
    string username = 2;
  }
}
"""


# Proto3 ``optional`` fields synthesize a wrapper oneof named with a
# leading underscore. The check_snake_case_oneofs rule must skip
# these — protobuf grammar forbids user-authored underscore-prefixed
# oneof names, so the leading underscore reliably discriminates
# compiler-synthesized oneofs from user-declared ones.
_ONEOF_PROTO3_OPTIONAL = """
syntax = "proto3";
package optfield;

message User {
  optional string email_address = 1;
  optional int64 user_id = 2;
}
"""


class TestSnakeCaseOneofs:
    """``naming/snake-case-oneofs`` fires on non-snake_case oneof names."""

    def test_happy_path_snake_oneofs_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _ONEOF_GOOD},
            "naming/snake-case-oneofs",
        )
        assert report.findings == ()

    def test_sad_path_non_snake_oneofs_fire(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"bad.proto": _ONEOF_BAD},
            "naming/snake-case-oneofs",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"Contact", "primaryId"}

    def test_proto3_optional_synthetic_oneof_skipped(
        self, tmp_path: Path,
    ) -> None:
        """Synthetic oneofs from proto3 ``optional`` fields do not fire.

        ``optional string email_address = 1;`` synthesizes a wrapper
        oneof named ``_email_address``. The leading underscore is the
        discriminator: protobuf grammar prohibits user-authored
        underscore-prefixed oneof names, so the rule can safely skip
        any oneof whose name begins with ``_`` without losing
        coverage of user-declared violations.
        """
        report = _run_single(
            tmp_path,
            {"optfield.proto": _ONEOF_PROTO3_OPTIONAL},
            "naming/snake-case-oneofs",
        )
        assert report.findings == ()


# ---------------------------------------------------------------------------
# naming/pascal-case-services
# ---------------------------------------------------------------------------


_SERVICE_GOOD = """
syntax = "proto3";
package good;

message Empty {}

service UserService {
  rpc GetUser (Empty) returns (Empty);
}
service URL {
  rpc Resolve (Empty) returns (Empty);
}
"""

_SERVICE_BAD = """
syntax = "proto3";
package bad;

message Empty {}

service userService {
  rpc Ping (Empty) returns (Empty);
}
service user_service {
  rpc Ping (Empty) returns (Empty);
}
"""


class TestPascalCaseServices:
    """``naming/pascal-case-services`` fires on non-PascalCase services."""

    def test_happy_path_pascal_services_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _SERVICE_GOOD},
            "naming/pascal-case-services",
        )
        assert report.findings == ()

    def test_sad_path_non_pascal_services_fire(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"bad.proto": _SERVICE_BAD},
            "naming/pascal-case-services",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"userService", "user_service"}


# ---------------------------------------------------------------------------
# naming/pascal-case-rpcs
# ---------------------------------------------------------------------------


_RPC_GOOD = """
syntax = "proto3";
package good;

message Empty {}

service UserService {
  rpc GetUser (Empty) returns (Empty);
  rpc ListUsers (Empty) returns (Empty);
  rpc A (Empty) returns (Empty);
}
"""

_RPC_BAD = """
syntax = "proto3";
package bad;

message Empty {}

service UserService {
  rpc getUser (Empty) returns (Empty);
  rpc get_user (Empty) returns (Empty);
}
"""


class TestPascalCaseRpcs:
    """``naming/pascal-case-rpcs`` fires on non-PascalCase RPCs."""

    def test_happy_path_pascal_rpcs_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _RPC_GOOD},
            "naming/pascal-case-rpcs",
        )
        assert report.findings == ()

    def test_sad_path_non_pascal_rpcs_fire(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"bad.proto": _RPC_BAD},
            "naming/pascal-case-rpcs",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"getUser", "get_user"}


# ---------------------------------------------------------------------------
# naming/snake-case-files
# ---------------------------------------------------------------------------


_FILE_GOOD_CONTENT = """
syntax = "proto3";
package good;
"""

_FILE_BAD_CONTENT = """
syntax = "proto3";
package bad;
"""


class TestSnakeCaseFiles:
    """``naming/snake-case-files`` fires on non-snake_case file basenames."""

    def test_happy_path_snake_case_basename_clean(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"foo_bar.proto": _FILE_GOOD_CONTENT},
            "naming/snake-case-files",
        )
        assert report.findings == ()

    def test_sad_path_pascal_case_basename_fires(
        self, tmp_path: Path,
    ) -> None:
        report = _run_single(
            tmp_path,
            {"Foo_Bar.proto": _FILE_BAD_CONTENT},
            "naming/snake-case-files",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"Foo_Bar"}

    def test_directory_path_ignored_basename_only(
        self, tmp_path: Path,
    ) -> None:
        """The rule inspects only the basename stem, not the path.

        A file at ``acme/v1/Foo_Bar.proto`` fires on the stem
        ``Foo_Bar``; the parent directory's case is irrelevant. This
        matches buf's FILE_LOWER_SNAKE_CASE which is documented as a
        basename check.
        """
        report = _run_single(
            tmp_path,
            {"acme/v1/Foo_Bar.proto": _FILE_BAD_CONTENT},
            "naming/snake-case-files",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"Foo_Bar"}

    def test_directory_path_clean_basename_does_not_fire(
        self, tmp_path: Path,
    ) -> None:
        """Mixed-case directory + snake_case basename is clean.

        ``Acme/V1/foo_bar.proto`` has an uppercase parent directory
        but a snake_case basename — the rule does not fire on the
        directory portion (that is a host-fs naming concern, not a
        protobuf-source-naming one).
        """
        report = _run_single(
            tmp_path,
            {"Acme/V1/foo_bar.proto": _FILE_GOOD_CONTENT},
            "naming/snake-case-files",
        )
        assert report.findings == ()

    def test_multi_dot_basename_fires_on_inner_dot(
        self, tmp_path: Path,
    ) -> None:
        """Multi-dot filenames fire because the inner dot survives stem-strip.

        ``PurePosixPath('acme.v1.proto').stem`` is ``'acme.v1'`` (only
        the final extension is stripped). The dot is not in the
        snake_case character class, so the rule fires on ``acme.v1``.
        Users encoding version segments should put them in the
        directory path (``acme/v1/users.proto``) rather than the
        basename. This matches buf's FILE_LOWER_SNAKE_CASE behavior.
        """
        report = _run_single(
            tmp_path,
            {"acme.v1.proto": _FILE_GOOD_CONTENT},
            "naming/snake-case-files",
        )
        bad_names = {f.params["name"] for f in report.findings}
        assert bad_names == {"acme.v1"}


# ---------------------------------------------------------------------------
# naming/snake-case-packages
# ---------------------------------------------------------------------------


_PKG_GOOD = """
syntax = "proto3";
package acme.api.v1.users;
"""

_PKG_BAD_ONE_SEGMENT = """
syntax = "proto3";
package acme.API.v1.users;
"""

_PKG_BAD_MULTIPLE_SEGMENTS = """
syntax = "proto3";
package Acme.API.v1.Users;
"""

_PKG_NONE = """
syntax = "proto3";
"""


class TestSnakeCasePackages:
    """``naming/snake-case-packages`` fires on non-snake_case package segments."""

    def test_happy_path_snake_package_clean(self, tmp_path: Path) -> None:
        report = _run_single(
            tmp_path,
            {"good.proto": _PKG_GOOD},
            "naming/snake-case-packages",
        )
        assert report.findings == ()

    def test_sad_path_one_bad_segment_fires_once(
        self, tmp_path: Path,
    ) -> None:
        """Only the offending segment is named in the finding."""
        report = _run_single(
            tmp_path,
            {"bad.proto": _PKG_BAD_ONE_SEGMENT},
            "naming/snake-case-packages",
        )
        offending_segments = {
            f.params["segment"] for f in report.findings
        }
        assert offending_segments == {"API"}
        # Each finding includes the original full-package context.
        for f in report.findings:
            assert f.params["package"] == "acme.API.v1.users"

    def test_sad_path_multiple_bad_segments_fire_per_segment(
        self, tmp_path: Path,
    ) -> None:
        """Multi-segment violations emit one finding per offender."""
        report = _run_single(
            tmp_path,
            {"bad.proto": _PKG_BAD_MULTIPLE_SEGMENTS},
            "naming/snake-case-packages",
        )
        offending_segments = {
            f.params["segment"] for f in report.findings
        }
        assert offending_segments == {"Acme", "API", "Users"}

    def test_missing_package_does_not_fire(self, tmp_path: Path) -> None:
        """A file with no ``package`` declaration is skipped.

        Missing-package detection is the responsibility of the
        separate ``package/defined`` rule (D6a Unit 6); this rule
        speaks only to the case-shape of declared segments. Skipping
        the missing-package case here avoids double-reporting once
        Unit 6 lands.
        """
        report = _run_single(
            tmp_path,
            {"none.proto": _PKG_NONE},
            "naming/snake-case-packages",
        )
        assert report.findings == ()


# ---------------------------------------------------------------------------
# Profile membership — from_pack returns the expected rule_id sets
# ---------------------------------------------------------------------------


# Rule_ids the naming pack registers — derived from RULES so a future
# rule addition (or removal) auto-updates this constant rather than
# requiring a hand-edit at every consumer. The ``_lint_spec`` attribute
# is attached by the ``@lint_rule`` decorator at module-import time;
# the ``type: ignore`` mirrors the established access pattern used in
# the per-rule spec-metadata tests above.
_ALL_NAMING_RULE_IDS = frozenset(
    fn._lint_spec.rule_id  # type: ignore[attr-defined]
    for fn in RULES
)


class TestProfileMembership:
    """``LintProfile.from_pack`` returns the expected rule_id sets.

    Per R3, ``default`` is structurally equivalent to ``recommended``
    in D6a — the option-aware differentiator that distinguishes them
    is deferred to D6b (J1). ``essentials`` is the protokit-native
    name for the no-naming-rules profile.
    """

    def test_from_pack_recommended_contains_all_naming_rules(self) -> None:
        profile = LintProfile.from_pack(naming_pack, "recommended")
        assert profile.name == "recommended"
        assert profile.rule_ids == _ALL_NAMING_RULE_IDS

    def test_from_pack_default_contains_all_naming_rules(self) -> None:
        """In D6a, ``default`` mirrors ``recommended``."""
        profile = LintProfile.from_pack(naming_pack, "default")
        assert profile.name == "default"
        assert profile.rule_ids == _ALL_NAMING_RULE_IDS

    def test_from_pack_essentials_contains_no_naming_rules(self) -> None:
        """``essentials`` does not include the naming family."""
        profile = LintProfile.from_pack(naming_pack, "essentials")
        assert profile.name == "essentials"
        assert profile.rule_ids == frozenset()

    def test_from_pack_unknown_profile_returns_empty(self) -> None:
        profile = LintProfile.from_pack(naming_pack, "nonexistent")
        assert profile.rule_ids == frozenset()


# ---------------------------------------------------------------------------
# Edge cases — single-character names, leading underscores
# ---------------------------------------------------------------------------


_SINGLE_CHAR_GOOD = """
syntax = "proto3";
package single;

message A {}

enum E {
  E_UNSPECIFIED = 0;
}

service S {
  rpc R (A) returns (A);
}
"""


class TestSingleCharacterNames:
    """Single uppercase letters satisfy the PascalCase rules.

    The PascalCase regex ``^[A-Z][A-Za-z0-9]*$`` accepts a bare ``A``
    / ``E`` / ``S`` / ``R``, matching buf's permissive PascalCase
    semantics. The plan calls this out as an edge case: "Empty /
    single-character names — ``naming/pascal-case-messages`` on
    ``message A`` is clean (A is PascalCase by convention)."
    """

    def test_single_char_pascal_names_all_clean(self, tmp_path: Path) -> None:
        result = _compile(
            tmp_path, {"single.proto": _SINGLE_CHAR_GOOD},
        )
        engine = LintEngine()
        engine.load_rule_pack(naming_pack)
        profile = LintProfile.from_pack(naming_pack, "recommended")
        report = engine.run(result, profile=profile)
        assert report.findings == ()


# ---------------------------------------------------------------------------
# Integration — all naming rules fire on a deliberately bad fixture
# ---------------------------------------------------------------------------


_ALL_BAD_FIXTURE = """
syntax = "proto3";
package Acme.API.v1;

message badMessage {
  string BadField = 1;
  oneof BadOneof {
    string username = 2;
  }
}

enum statusBad {
  STATUS_UNSPECIFIED = 0;
  StatusActive = 1;
}

service userService {
  rpc getUser (badMessage) returns (badMessage);
}
"""


class TestNamingPackIntegration:
    """All 9 naming rules fire on a deliberately-bad multi-element fixture.

    A single fixture violates every rule at once; the integration
    test asserts that running the full ``recommended`` profile from
    the pack surfaces a finding for each rule_id. This catches
    profile-wiring regressions (e.g., a rule accidentally shipped
    with ``profiles=("default",)`` only would silently miss the
    ``recommended`` profile run).
    """

    def test_recommended_profile_fires_all_naming_rules(
        self, tmp_path: Path,
    ) -> None:
        result = _compile(
            tmp_path,
            {"BadFile.proto": _ALL_BAD_FIXTURE},
        )
        engine = LintEngine()
        engine.load_rule_pack(naming_pack)
        profile = LintProfile.from_pack(naming_pack, "recommended")
        report = engine.run(result, profile=profile)
        fired_rule_ids = {f.rule_id for f in report.findings}
        assert fired_rule_ids == _ALL_NAMING_RULE_IDS
