"""Regression pins for deferred lint audit findings (family V, lint).

Every ``xfail`` in this module pins a LIVE defect that a later release owns.
Each pin is
``@pytest.mark.xfail(strict=True, raises=...)`` on the test function itself,
with a ``reason`` that begins with the finding ID and names the owning release.
The suite stays green while the defect exists and the pin flips to a hard
failure (XPASS under strict mode) the day the mechanism is fixed, so a fix
cannot land silently and no pin can rot into a permanently-red test.

Each pin asserts the correct outcome, and ``raises=`` names the exception that
was observed with ``--runxfail --tb=line`` under both protobuf backends. Every
run goes through ``CliRunner.invoke(..., catch_exceptions=False)``, so a crash
in the command is its own exception and never an exit code a pin could mistake
for the defect. A passing control sits beside every pin and shares its
construction: a red control says the harness broke, a red pin says the defect
moved.

V35 and V36 are the class V33 belonged to before 0.15.1 closed it: a
``LintRuntimeWarning`` category that means *a selected rule did not run*, on a
run that still exits by its findings alone. ``protokit lint`` exits 2 with
``error[lint-analysis-incomplete]:`` for the three such categories that
``protokit._trust.INCOMPLETE_ANALYSIS_CATEGORIES`` lists (``rule_exception``,
``unloaded_rule``, ``all_files_excluded``). Two more are left out of that set,
and those two are the V35 and V36 pins.

Pinned here:

* **V35** — ``extension_unresolved``. ``options/field-behavior-consistent``
  is in the ``default`` profile, which is also the profile a bare
  ``protokit lint`` runs. It looks ``google.api.field_behavior`` up in the
  compile pool, and when the inputs never defined that extension it records
  the warning and returns without checking anything. A plain schema therefore
  prints "rule ... skipped" and exits 0. The pin asserts that a run which
  records the skip exits 2. It is written as that implication, not as a bare
  ``exit_code == 2``, because ``protokit._trust`` names two ways to close the
  finding and the pin has to flip on either one: put the category in the gate,
  or (the one it calls the honest fix) stop recording a skip for a schema that
  cannot carry the extension, which leaves nothing to gate and an exit 0 that
  means what it says.
* **V36** — ``custom_annotation_extension_unresolved``. A
  ``[[tool.protokit.lint.custom_annotation_rules]]`` entry whose ``option``
  names no extension in the compile pool (written in the parenthesised
  ``.proto`` form, misspelled, or defined in a file that was never compiled)
  is skipped the same way. The user configured that rule at
  ``severity = "error"``, and a method without the annotation is exactly what
  it reports, so a schema that violates it exits 0. The pin asserts exit 2 for
  both spellings. The worked example's own test,
  ``test_parenthesized_option_currently_skips_the_rule_without_exit_2_v36`` in
  ``tests/schema/lint/cli/test_d6d_custom_annotation_example.py``, documents
  today's exit code and is the test the fix must update.
* **C13-C2** — a presence-only custom annotation rule on a ``repeated``
  option. ``HasExtension`` refuses a repeated extension, so every element is
  a ``rule_exception`` and the run exits 2 without the finding the rule
  exists to report. Owner U24 (0.17.0).
* **Lint rule-pack load** (no finding ID; maintainer ruling of 2026-10-12) — a
  ``--rule-pack`` whose ``RULES`` calls ``sys.exit(0)`` while it is read ends
  the run with exit 0, on a schema with an error-level finding. Owner U24
  (0.17.0).

``tests/meta/test_doc_claims.py`` measures the same two gaps from the other
side, as a guard on what the README and CHANGELOG may say while they are open
(``test_sarif_execution_successful_follows_the_gated_categories``). It goes red
when either category joins the gate; these pins are the half that names the
finding that closed.

The V36 and later runs pass ``--no-builtin-rules`` so the custom rule is the only rule
selected and the exit code has one cause. Under ``recommended`` the import that
supplies the option is itself reported by ``imports/unused`` (U20-2, pinned in
``test_audit_u20_buf_parity_pins.py``), which would turn every run here into an
exit 1 that says nothing about the custom rule.
"""

from __future__ import annotations

import json
import sys
import textwrap
import types
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from protokit.schema.lint.cli import main as lint_main
from tests.schema.lint.cli._helpers import runtime_warnings_from_json

_ANALYSIS_INCOMPLETE = "error[lint-analysis-incomplete]:"


def _write_tree(root: Path, sources: dict[str, str]) -> None:
    """Write ``sources`` (POSIX-relative name -> text) under ``root``."""
    for name, text in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _lint(*args: str) -> Result:
    """Run ``protokit lint --format json`` in-process and return the result.

    ``catch_exceptions=False`` lets an unhandled exception escape as itself
    instead of being folded into ``exit_code == 1``.
    """
    return CliRunner().invoke(lint_main, [*args, "--format", "json"], catch_exceptions=False)


def _payload(result: Result) -> dict[str, Any]:
    """The JSON report on stdout (``result.output`` would mix stderr in)."""
    return json.loads(result.stdout)


def _skips(result: Result, category: str) -> list[dict[str, Any]]:
    """Runtime warnings of ``category`` in the rendered report."""
    return [w for w in runtime_warnings_from_json(result.stdout) if w["category"] == category]


def _outcome(result: Result) -> str:
    """What the run did, on one line, for an assertion message."""
    return f"exit {result.exit_code}; stderr={result.stderr!r}; stdout={result.stdout!r}"


# ---------------------------------------------------------------------------
# V35 — extension_unresolved: a built-in rule that never ran, exit 0
# ---------------------------------------------------------------------------

_USER_PATH = "acme/v1/user.proto"
_FIELD_BEHAVIOR_PATH = "google/api/field_behavior.proto"

#: A plain schema: no options, no imports, nothing any ``default`` rule reports.
_USER = """\
syntax = "proto3";

package acme.v1;

message User {
  string name = 1;
}
"""

#: The part of googleapis' ``google/api/field_behavior.proto`` that defines the
#: extension ``options/field-behavior-consistent`` reads.
_FIELD_BEHAVIOR = """\
syntax = "proto3";

package google.api;

import "google/protobuf/descriptor.proto";

enum FieldBehavior {
  FIELD_BEHAVIOR_UNSPECIFIED = 0;
  OPTIONAL = 1;
  REQUIRED = 2;
}

extend google.protobuf.FieldOptions {
  repeated FieldBehavior field_behavior = 1052;
}
"""


def _lint_user_schema(
    root: Path, *, define_extension: bool, exclude: str = "google/**"
) -> Result:
    """``protokit lint --profile default`` on the plain ``User`` schema.

    Both files are always written; ``define_extension`` only decides whether
    the file that defines ``google.api.field_behavior`` is among the inputs,
    and so whether the extension is in the compile pool. That is the one
    variable between the V35 pin and its control.

    ``exclude`` keeps the vendored file's own findings out of the report. The
    default pattern matches nothing when that file is not an input.
    """
    _write_tree(root, {_USER_PATH: _USER, _FIELD_BEHAVIOR_PATH: _FIELD_BEHAVIOR})
    inputs = [str(root / _USER_PATH)]
    if define_extension:
        inputs.append(str(root / _FIELD_BEHAVIOR_PATH))
    flags = ("--no-config", "--profile", "default", "--exclude", exclude)
    return _lint(*flags, "--proto", *inputs, "-I", str(root))


def test_v35_resolved_extension_skips_nothing_and_exits_0_control(tmp_path: Path) -> None:
    """With the extension in the pool the rule runs, and exit 0 is the whole story."""
    result = _lint_user_schema(tmp_path, define_extension=True)
    payload = _payload(result)
    assert payload["runtime_warnings"] == [], _outcome(result)
    assert payload["findings"] == [], _outcome(result)
    assert result.exit_code == 0, _outcome(result)


def test_an_already_gated_skip_exits_2_through_this_harness_control(tmp_path: Path) -> None:
    """A category the gate does cover is observed as exit 2 by this harness.

    Shared by the V35 and V36 pins: it shows the outcome they assert is
    reachable through ``_lint`` today, with the report still rendered first.
    """
    result = _lint_user_schema(tmp_path, define_extension=False, exclude="**")
    assert len(_skips(result, "all_files_excluded")) == 1, _outcome(result)
    assert result.exit_code == 2, _outcome(result)
    assert _ANALYSIS_INCOMPLETE in result.stderr, _outcome(result)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V35: owned by U24 (0.17.0). `extension_unresolved` is not in "
        "protokit._trust.INCOMPLETE_ANALYSIS_CATEGORIES, so a run that records "
        "options/field-behavior-consistent as skipped still exits 0"
    ),
)
def test_v35_a_run_that_records_the_field_behavior_rule_skipped_exits_2(tmp_path: Path) -> None:
    """A plain schema under the default profile: the rule never ran, exit 0."""
    result = _lint_user_schema(tmp_path, define_extension=False)
    skipped = _skips(result, "extension_unresolved")
    # Exactly the two fixed outcomes: the skip is recorded and gated, or nothing
    # is skipped and the run is clean. An exit 2 with no skip on the report (a
    # compile that failed) is neither.
    gated = result.exit_code == 2 and bool(skipped)
    nothing_skipped = result.exit_code == 0 and not skipped
    assert gated or nothing_skipped, (
        f"the report records a rule that did not run "
        f"({[w['message'] for w in skipped]}) and the run did not exit 2: {_outcome(result)}"
    )


# ---------------------------------------------------------------------------
# V36 — custom_annotation_extension_unresolved: a configured rule that never
# ran, exit 0 on a schema that violates it
# ---------------------------------------------------------------------------

_AUDIT_OPTION = "acme.v1.audit_level"
_CUSTOM_RULE = "custom/audit-required"

#: Defines the method option the custom rule requires.
_AUDIT = """\
syntax = "proto3";

package acme.v1;

import "google/protobuf/descriptor.proto";

extend google.protobuf.MethodOptions {
  string audit_level = 50001;
}
"""

#: One method carries the option and one does not. The second is the violation
#: an ``audit-required`` rule exists to report.
_SERVICE = """\
syntax = "proto3";

package acme.v1;

import "acme/v1/audit.proto";

message PingRequest {}
message PingResponse {}

service PingService {
  rpc Audited(PingRequest) returns (PingResponse) {
    option (acme.v1.audit_level) = "high";
  }
  rpc Unaudited(PingRequest) returns (PingResponse);
}
"""

#: ``option`` spellings that name no extension in the compile pool. The first
#: is the ``.proto``-source form the worked example's pyproject warns against;
#: the second stands for a typo or a defining file that was never compiled.
_UNRESOLVED_OPTIONS = (f"({_AUDIT_OPTION})", "acme.v1.no_such_option")
_UNRESOLVED_IDS = ("parenthesised-option", "option-not-in-the-pool")


def _lint_audited_service(root: Path, option: str) -> Result:
    """Lint ``PingService`` with one error-severity custom annotation rule.

    ``option`` is the only variable between the V36 pins and their control.
    ``--no-builtin-rules`` leaves the custom rule as the only rule selected
    (see the module docstring).
    """
    proto_root = root / "proto"
    _write_tree(proto_root, {"acme/v1/audit.proto": _AUDIT, "acme/v1/service.proto": _SERVICE})
    config = root / "pyproject.toml"
    config.write_text(
        textwrap.dedent(
            f"""\
            [[tool.protokit.lint.custom_annotation_rules]]
            rule_suffix   = "audit-required"
            option        = "{option}"
            element_kinds = ["method"]
            severity      = "error"
            """
        ),
        encoding="utf-8",
    )
    service = str(proto_root / "acme/v1/service.proto")
    flags = ("--config", str(config), "--no-builtin-rules")
    return _lint(*flags, "--proto", service, "-I", str(proto_root))


def test_v36_resolved_custom_rule_reports_the_violation_and_exits_1_control(
    tmp_path: Path,
) -> None:
    """Spelled so it resolves, the rule runs: the schema violates it, exit 1."""
    result = _lint_audited_service(tmp_path, _AUDIT_OPTION)
    payload = _payload(result)
    assert [(f["rule_id"], f["severity"], f["violation_kind"]) for f in payload["findings"]] == [
        (_CUSTOM_RULE, "error", "custom-annotation-absent")
    ], _outcome(result)
    assert payload["findings"][0]["location"].endswith("PingService/Unaudited"), _outcome(result)
    assert payload["runtime_warnings"] == [], _outcome(result)
    assert result.exit_code == 1, _outcome(result)


@pytest.mark.parametrize("option", _UNRESOLVED_OPTIONS, ids=_UNRESOLVED_IDS)
def test_v36_unresolved_custom_rule_is_skipped_and_recorded_control(
    tmp_path: Path, option: str
) -> None:
    """The premise of the pin: the same schema, and the rule reports nothing.

    Says nothing about the exit code, so it keeps passing once the category is
    gated. If it fails, the pin below has lost the skip it is about and needs
    re-triage: accepting the parenthesised spelling, for one, would run the
    rule and leave that pin failing on an exit 1 it was never written for.
    """
    result = _lint_audited_service(tmp_path, option)
    payload = _payload(result)
    assert payload["findings"] == [], _outcome(result)
    assert [(w["category"], w["rule_id"]) for w in payload["runtime_warnings"]] == [
        ("custom_annotation_extension_unresolved", _CUSTOM_RULE)
    ], _outcome(result)


@pytest.mark.parametrize("option", _UNRESOLVED_OPTIONS, ids=_UNRESOLVED_IDS)
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "V36: owned by U24 (0.17.0). `custom_annotation_extension_unresolved` is not in "
        "protokit._trust.INCOMPLETE_ANALYSIS_CATEGORIES, so an error-severity "
        "custom annotation rule whose option does not resolve is skipped and "
        "the schema that violates it exits 0"
    ),
)
def test_v36_unresolved_error_severity_custom_rule_exits_2(tmp_path: Path, option: str) -> None:
    """The one rule the user configured did not run; that is not a clean run."""
    result = _lint_audited_service(tmp_path, option)
    # The skip has to be on the report: an exit 2 from anything else (a compile
    # that failed, a usage error) is not this finding being fixed.
    assert _skips(result, "custom_annotation_extension_unresolved"), _outcome(result)
    assert result.exit_code == 2, (
        f"custom rule with option {option!r} cannot have run, and the run did not exit 2: "
        f"{_outcome(result)}"
    )


# ---------------------------------------------------------------------------
# C13-C2 — a presence-only custom annotation rule on a ``repeated`` option
#
# Pinned 2026-10-17, owned by U24 (0.17.0). The synthetic rule's closure asks
# ``parsed.HasExtension(ext_desc)``, which protobuf refuses for a repeated
# extension (upb: "Field is repeated. A singular method is required.";
# pure-Python: '"acme.v1.tags" is repeated.'). Every method is then a
# ``rule_exception``, the rule reports nothing, and the run exits 2 with
# ``error[lint-analysis-incomplete]`` on a schema whose ``Bare`` method plainly
# lacks the option. How a repeated option should count as present is not
# designed: the pin accepts the rule running (a non-empty option is present, so
# ``Bare`` is reported) or the entry being refused at configuration time with
# an error naming the option.
# ---------------------------------------------------------------------------

_TAGS_OPTION = "acme.v1.tags"
_OWNER_OPTION = "acme.v1.owner"
_TAGS_RULE = "custom/tags-required"

#: A repeated and a singular method option, side by side.
_TAGS = """\
syntax = "proto3";

package acme.v1;

import "google/protobuf/descriptor.proto";

extend google.protobuf.MethodOptions {
  repeated string tags = 50001;
  string owner = 50002;
}
"""

#: ``Annotated`` carries both options and ``Bare`` neither.
_TAGGED_SERVICE = """\
syntax = "proto3";

package acme.v1;

import "acme/v1/tags.proto";

message Request {}

service Service {
  rpc Annotated(Request) returns (Request) {
    option (acme.v1.tags) = "x";
    option (acme.v1.owner) = "me";
  }
  rpc Bare(Request) returns (Request);
}
"""


def _lint_tagged_service(root: Path, option: str, *extra: str) -> Result:
    """Lint ``Service`` with one error-severity, presence-only custom rule on ``option``.

    ``option`` is the only variable between the C13-C2 pin and its control.
    ``extra`` is appended to the command line (the rule-pack pins below pass
    ``--rule-pack``). ``--no-builtin-rules`` leaves the custom rule as the only
    rule selected (see the module docstring).
    """
    proto_root = root / "proto"
    _write_tree(
        proto_root, {"acme/v1/tags.proto": _TAGS, "acme/v1/service.proto": _TAGGED_SERVICE}
    )
    config = root / "pyproject.toml"
    config.write_text(
        textwrap.dedent(
            f"""\
            [[tool.protokit.lint.custom_annotation_rules]]
            rule_suffix   = "tags-required"
            option        = "{option}"
            element_kinds = ["method"]
            severity      = "error"
            """
        ),
        encoding="utf-8",
    )
    service = str(proto_root / "acme/v1/service.proto")
    flags = ("--config", str(config), "--no-builtin-rules", *extra)
    return _lint(*flags, "--proto", service, "-I", str(proto_root))


def _reports_bare_and_exits_1(result: Result) -> bool:
    """Whether the run is the custom rule's report on ``Bare`` and nothing else."""
    payload = _payload(result)
    findings = [
        (f["rule_id"], f["severity"], f["violation_kind"], f["location"])
        for f in payload["findings"]
    ]
    return (
        result.exit_code == 1
        and payload["runtime_warnings"] == []
        and len(findings) == 1
        and findings[0][:3] == (_TAGS_RULE, "error", "custom-annotation-absent")
        and findings[0][3].endswith("Service/Bare")
    )


def test_c13_c2_singular_option_reports_the_bare_method_and_exits_1_control(
    tmp_path: Path,
) -> None:
    """The same rule on the singular option runs: ``Bare`` is reported, exit 1."""
    result = _lint_tagged_service(tmp_path, _OWNER_OPTION)

    assert _reports_bare_and_exits_1(result), _outcome(result)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "C13-C2: owned by U24 (0.17.0). The presence-only custom annotation rule "
        "calls HasExtension, which protobuf refuses for a repeated extension, so "
        "every method is a rule_exception, no finding is reported and the run "
        "exits 2 with error[lint-analysis-incomplete]"
    ),
)
def test_c13_c2_presence_only_rule_on_a_repeated_option_runs_or_is_refused(
    tmp_path: Path,
) -> None:
    """A presence-only rule on a repeated option must run, or be refused up front.

    Either outcome counts as fixed: the rule runs (``Bare`` reported, exit 1,
    no runtime warning), or the configuration is refused before any report
    (exit 2, stderr names the option, nothing on stdout). Today's run renders
    a report holding two ``rule_exception`` warnings and no finding.
    """
    result = _lint_tagged_service(tmp_path, _TAGS_OPTION)

    if not result.stdout.strip():
        # No report: only a refusal that names the option is a fix. Any other
        # exit without a report (a compile that failed) is not this finding.
        if result.exit_code == 2 and _TAGS_OPTION in result.stderr:
            return
        pytest.fail(f"no report, and not a refusal naming the option: {_outcome(result)}")
    rule_exceptions = _skips(result, "rule_exception")
    assert not rule_exceptions and _reports_bare_and_exits_1(result), (
        f"the presence-only rule on {_TAGS_OPTION} did not run "
        f"({[w['message'] for w in rule_exceptions]}): {_outcome(result)}"
    )


# ---------------------------------------------------------------------------
# Lint's ``--rule-pack`` loader — a pack that calls ``sys.exit(0)`` while its
# ``RULES`` are read
#
# Pinned 2026-10-17 by maintainer ruling (2026-10-12), owned by U24 (0.17.0).
# No finding ID. ``_load_user_rule_pack`` guards the import of the pack for
# ``SystemExit``, but around ``engine.load_rule_pack(module)``, which iterates
# ``RULES``, it catches only ``DuplicateRuleError``, ``AttributeError`` and
# ``TypeError``. A ``RULES`` whose iteration calls ``sys.exit(0)`` therefore
# becomes the process exit code: the run exits 0 with nothing on stdout, here
# on a schema with an error-level finding (exit 1 without the pack). The
# correct outcome is the one the import arm already gives: exit 2 with an
# ``error[lint-rule-pack-load]`` line naming the pack.
# ---------------------------------------------------------------------------

_EXITING_PACK = "c_lint_pack_exiting_while_rules_are_read"


class _RulesExitingWhenRead:
    """A ``RULES`` value whose iteration calls ``sys.exit(0)``."""

    def __iter__(self) -> Any:
        sys.exit(0)


class _RulesRaisingTypeErrorWhenRead:
    """A ``RULES`` value whose iteration raises ``TypeError``."""

    def __iter__(self) -> Any:
        raise TypeError("RULES could not be built")


def _lint_with_pack(root: Path, monkeypatch: pytest.MonkeyPatch, rules: object) -> Result:
    """Lint the tagged service (one error finding) with a pack whose ``RULES`` is ``rules``.

    ``rules`` is the only variable between the pin and its controls. The pack
    module is registered in ``sys.modules`` for this test only, so
    ``--rule-pack``'s import finds it.
    """
    module = types.ModuleType(_EXITING_PACK)
    module.RULES = rules  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, _EXITING_PACK, module)
    return _lint_tagged_service(root, _OWNER_OPTION, "--rule-pack", _EXITING_PACK)


def _names_the_pack_in_an_error_line(result: Result) -> bool:
    """Whether stderr has an ``error[...]`` line naming the pack.

    The load banner names the pack on every run, so the pack's name alone on
    stderr says nothing.
    """
    return any(
        line.startswith("error[") and _EXITING_PACK in line
        for line in result.stderr.splitlines()
    )


def test_rule_pack_with_empty_rules_leaves_the_error_finding_and_exit_1_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pack that loads and adds no rule: the schema's error finding exits 1."""
    result = _lint_with_pack(tmp_path, monkeypatch, ())

    assert _reports_bare_and_exits_1(result), _outcome(result)


def test_rule_pack_raising_while_rules_are_read_exits_2_naming_the_pack_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``RULES`` that raises ``TypeError`` when read: exit 2, the pack named."""
    result = _lint_with_pack(tmp_path, monkeypatch, _RulesRaisingTypeErrorWhenRead())

    assert result.exit_code == 2, _outcome(result)
    assert "error[lint-rule-pack-load]" in result.stderr, _outcome(result)
    assert _names_the_pack_in_an_error_line(result), _outcome(result)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Lint rule-pack load (ruling 2026-10-12, no finding ID): owned by U24 "
        "(0.17.0). _load_user_rule_pack guards the pack's import for SystemExit "
        "but not engine.load_rule_pack, which iterates RULES, so a RULES whose "
        "iteration calls sys.exit(0) ends the run with exit 0 and no output on a "
        "schema with an error-level finding"
    ),
)
def test_rule_pack_exiting_while_rules_are_read_exits_2_naming_the_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pack that ends the run while its rules are read is a load error, not a verdict."""
    result = _lint_with_pack(tmp_path, monkeypatch, _RulesExitingWhenRead())

    assert result.exit_code == 2, (
        f"a pack calling sys.exit(0) while RULES are read decided the exit code: "
        f"{_outcome(result)}"
    )
    assert _names_the_pack_in_an_error_line(result), _outcome(result)
