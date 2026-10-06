"""Regression pins for deferred lint audit findings (family V, lint).

Every ``xfail`` in this module pins a LIVE defect that a later release owns
(requirement R15 of the 0.16.0 re-audit fix wave). Each pin is
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

Both findings are the class V33 belonged to before 0.15.1 closed it: a
``LintRuntimeWarning`` category that means *a selected rule did not run*, on a
run that still exits by its findings alone. ``protokit lint`` exits 2 with
``error[lint-analysis-incomplete]:`` for the three such categories that
``protokit._trust.INCOMPLETE_ANALYSIS_CATEGORIES`` lists (``rule_exception``,
``unloaded_rule``, ``all_files_excluded``). Two more are left out of that set,
and those two are the pins.

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

``tests/meta/test_doc_claims.py`` measures the same two gaps from the other
side, as a guard on what the README and CHANGELOG may say while they are open
(``test_sarif_execution_successful_follows_the_gated_categories``). It goes red
when either category joins the gate; these pins are the half that names the
finding that closed.

The V36 runs pass ``--no-builtin-rules`` so the custom rule is the only rule
selected and the exit code has one cause. Under ``recommended`` the import that
supplies the option is itself reported by ``imports/unused`` (U20-2, pinned in
``test_audit_u20_buf_parity_pins.py``), which would turn every run here into an
exit 1 that says nothing about the custom rule.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from protokit.schema.lint.cli import main as lint_main

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
    return [w for w in _payload(result)["runtime_warnings"] if w["category"] == category]


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
        "V35: owned by 0.17.0 (lint row, unit not yet numbered in the parent "
        "plan). `extension_unresolved` is not in "
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
        "V36: owned by 0.17.0 (lint row, unit not yet numbered in the parent "
        "plan). `custom_annotation_extension_unresolved` is not in "
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
