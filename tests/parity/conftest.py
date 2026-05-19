"""Buf-parity test harness — D6a Unit 8 Phase A.

This conftest powers ``tests/parity/`` — the in-repo harness that
runs every D6a buf-equivalent rule's fixtures through both
``protokit lint`` and ``buf lint`` and asserts equivalent findings.
The ``parity`` marker is **documentary**: default ``pytest tests/``
DOES collect parity tests (verified at ``pyproject.toml:86-87``);
the marker is only honored by jobs that explicitly select via
``-m parity`` (e.g., the advisory CI ``parity`` job). Per-module
opt-in via ``pytestmark = pytest.mark.parity`` therefore decides
whether that module shows up in the advisory parity job, NOT
whether it runs at all. D6b U6's ``test_parity_package_same.py``
deliberately omits the marker so its recorded-snapshot tests run
in the required ``test`` job on every PR (no BUF_BINARY dep).

Resolved decisions (see ``docs/plans/2026-05-13-001-feat-d6a-u8-parity-test-infra-plan.md``):

- **Rule-id mapping is derived from ``LintRuleSpec.source_spec``.**
  Walking ``BUILTIN_PACKS`` at collection time stays in lockstep
  with rule additions in future deliveries.
- **Canary parity is direct (D6c U2 KTD-11).** The D2 canary's
  ``source_spec`` was corrected from ``"https://google.aip.dev/122"``
  to ``"buf:FIELD_LOWER_SNAKE_CASE"`` at D6c U2 so the rule
  participates in the buf-BASIC parity numerator via the same
  ``_extract_buf_rule_id`` path as every other R*: rule. The
  earlier ``_CANARY_PARITY_OVERRIDE`` indirection has been deleted
  (its "fail-loud" claim was inverted — a revert of the
  source_spec to the AIP-122 URL would silently re-enter the
  override path). Replaced with a post-walk ``assert
  "naming/snake-case-fields" in mapping`` in
  :func:`_build_rule_id_map` that fires loudly if the canary ever
  drops out of the parity numerator. **Any future change to the
  canary's ``_SNAKE_CASE_RE`` regex requires re-validating buf
  parity against the pinned buf version.**
- **Documented buf-parity divergences live in ``_PARITY_EXCEPTIONS``.**
  Each entry references the rule's four-site documentation
  (module docstring + rule docstring + ``message_template`` + paired
  branch tests) per the
  ``buf-parity-divergence-documentation-discipline-2026-05-13``
  learning. Deleting an entry breaks the corresponding test; the
  test's docstring + this map together form the fifth site that
  catches accidental removal during refactors.
- **Buf binary discovery prefers ``$BUF_BINARY`` then PATH.**
  Local developers can point at a custom buf via
  ``BUF_BINARY=$(which buf) pytest tests/parity -m parity``;
  CI's parity job exports ``BUF_BINARY=/usr/local/bin/buf``. If
  neither resolves, the ``buf_binary`` session fixture fails the
  test session with a clear actionable message.
- **Subprocess invocations are hard-capped at 30 seconds** and
  wrapped in a triple-arm
  (``SystemExit + KeyboardInterrupt + Exception``) guard per the
  ``keyboardinterrupt-baseexception-bypass-rule-pack-load-2026-05-07``
  learning so Ctrl-C during a hung tool invocation does not
  corrupt pytest's session state.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, NamedTuple

import pytest

from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.rules import BUILTIN_PACKS
from protokit.schema.lint.rules import package_same as _package_same_mod

# ce:review follow-up (Finding #9): subprocess + buf-discovery helpers
# live in tests/_buf_helpers.py so the U4 smoke harness and the parity
# harness share one source of truth. The local _run_subprocess +
# buf_binary fixture body below now delegate to the shared module.
from tests._buf_helpers import discover_buf_binary, run_buf_subprocess

#: Type alias for the parity-exceptions mapping. Keys are
#: ``(protokit_rule_id, fixture_stem)``; values are
#: ``(posture, reason)`` where posture is one of
#: ``"protokit_stricter"`` or ``"protokit_looser"``.
ParityPosture = Literal["protokit_stricter", "protokit_looser"]
ParityExceptionsMap = Mapping[tuple[str, str], tuple[ParityPosture, str]]
_VALID_POSTURES: frozenset[str] = frozenset({"protokit_stricter", "protokit_looser"})


class BufFinding(NamedTuple):
    """Typed view of one buf v1.69.0 NDJSON finding.

    Field set verified empirically against
    ``tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/*.json``
    (D6b U4a). All 7 fields are present in every non-empty buf-emitted
    finding; ``parse_buf_recorded_snapshot`` below raises on missing
    fields so a future buf release that changes the NDJSON shape
    surfaces loudly rather than via silent KeyError.

    Used by D6b U6's multi-file parity harness (``test_parity_package_same.py``)
    + reusable by future multi-file rule families that need typed
    NDJSON parsing of recorded buf snapshots.
    """

    path: str
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    type: str
    message: str

#: Documented buf-parity divergences. Keyed by
#: ``(protokit_rule_id, fixture_stem)``; value names the divergence
#: posture (``protokit_stricter`` or ``protokit_looser``) and a
#: short reason. Tests for these (rule, fixture) pairs assert the
#: divergence shape instead of strict equality.
#:
#: Each entry MUST also be documented at the four sites in the
#: rule's module:
#:   1. Module docstring
#:   2. Rule function docstring
#:   3. ``message_template``
#:   4. Per-branch test methods
#: per
#: ``docs/solutions/best-practices/buf-parity-divergence-documentation-discipline-2026-05-13.md``.
_PARITY_EXCEPTIONS: ParityExceptionsMap = {
    # file/syntax-specified: descriptor-level limitation — protoc
    # emits ``fdp.syntax == ""`` for both "no syntax statement" AND
    # explicit ``syntax = "proto2";``. Protokit fires on both;
    # buf only fires on the no-statement branch (it parses source
    # directly).
    ("file/syntax-specified", "explicit_proto2"): (
        "protokit_stricter",
        "descriptor cannot distinguish explicit-proto2 from no-syntax; "
        "protokit fires on both branches",
    ),
}

#: Buf rules that were deprecated upstream and cannot be exercised
#: by the parity harness. Per ``buf config ls-lint-rules`` against
#: the pinned buf version, ``IMPORT_NO_WEAK`` was deprecated in
#: buf v1.69.0 (``deprecated: true``, ``categories: []``) — invoking
#: ``buf lint`` with ``use: [IMPORT_NO_WEAK]`` triggers a buf-side
#: "resultRules was empty" error rather than a clean run.
#:
#: Protokit retains its ``imports/no-weak`` rule because the
#: ``proto2`` ``weak`` import keyword is still in the descriptor
#: format and still worth nudging users away from; buf's
#: deprecation reflects buf's product judgment, not a change in
#: the underlying protobuf semantics. Parity testing for these
#: rules is **skipped at runtime** with a clear reason rather than
#: silently mismarked as a divergence.
_BUF_DEPRECATED_RULES: frozenset[str] = frozenset({"IMPORT_NO_WEAK"})


def _extract_buf_rule_id(source_spec: str) -> str | None:
    """Return the buf rule id from a ``buf:RULE_ID`` source_spec, else None."""
    prefix = "buf:"
    if source_spec.startswith(prefix):
        return source_spec[len(prefix):]
    return None


def _build_package_same_proto_to_buf() -> Mapping[str, str]:
    """Walk ``package_same.RULES`` and return ``{protokit_rule_id: buf_rule_id}``.

    D6b U6 ce:review follow-up (MAINT-2 + MAINT-3 + KP-1): the map is
    built once at module-import time rather than rebuilt inside
    ``assert_parity_multi_file`` on every parametrized test invocation.

    Until D6b U7, R7 was not in ``BUILTIN_PACKS``, so the BUILTIN_PACKS-
    derived ``RULE_ID_MAP`` above didn't cover it — the dedicated walk
    kept U6's invocation path independent of the BUILTIN_PACKS
    sequencing. Post-U7, ``_PACKAGE_SAME_PROTO_TO_BUF`` is a subset of
    ``RULE_ID_MAP`` and could be derived from it; retained for
    assertion-module isolation so the parity gate's R25(a-e) invariants
    are not coupled to BUILTIN_PACKS-tuple drift.
    """
    mapping: dict[str, str] = {}
    for fn in _package_same_mod.RULES:
        spec = get_lint_spec(fn)
        buf_id = _extract_buf_rule_id(spec.source_spec)
        if buf_id is not None:
            mapping[spec.rule_id] = buf_id
    return mapping


#: ``protokit_rule_id -> buf_rule_id`` for the 7 R7 PACKAGE_SAME_* rules.
#: Built once at module import; consumed by ``assert_parity_multi_file``.
_PACKAGE_SAME_PROTO_TO_BUF: Mapping[str, str] = _build_package_same_proto_to_buf()

#: All R7 protokit rule_ids as a frozenset for fast membership checks.
_PACKAGE_SAME_RULE_IDS: frozenset[str] = frozenset(_PACKAGE_SAME_PROTO_TO_BUF.keys())

#: ``protokit_rule_id -> buf_rule_id`` for the 2 D6c R8 + R8b cross-file
#: rules (``package/same-directory`` + ``package/directory-same-package``).
#: Built once at module import; consumed by ``assert_parity_multi_file``'s
#: package_directory arm.
#:
#: **KTD-12 design choice**: derive the mapping from the same source as
#: R7 (walk ``package.RULES``, filter by buf-source-spec membership) but
#: filter by an inclusion frozenset rather than the broad "every rule in
#: package.RULES" R7 uses — ``package.RULES`` also contains the D6a
#: ``package/defined`` + ``package/directory-match`` rules whose snapshots
#: live in ``tests/parity/fixtures/`` (single-file harness) rather than
#: ``tests/schema/lint/rules/fixtures/package_directory/_buf_smoke/``
#: (multi-file harness). Keeping the explicit inclusion set documents
#: the load-bearing membership contract that U2's ce:review Finding #7
#: pointed at.
_D6C_PACKAGE_DIRECTORY_RULE_IDS: frozenset[str] = frozenset({
    "package/same-directory",
    "package/directory-same-package",
})


def _build_package_directory_proto_to_buf() -> Mapping[str, str]:
    """Walk ``package.RULES`` filtered to R8 + R8b and return ``{protokit_id: buf_id}``.

    Sibling of :func:`_build_package_same_proto_to_buf` for the D6c
    R8 + R8b family. Filters to the
    :data:`_D6C_PACKAGE_DIRECTORY_RULE_IDS` inclusion set so that
    ``package/defined`` and ``package/directory-match`` (D6a rules
    living in the single-file ``tests/parity/fixtures/`` harness) are
    excluded — those rules have their own parity coverage at
    :mod:`tests.parity.test_parity_package`.
    """
    from protokit.schema.lint.rules import package as _package_mod
    mapping: dict[str, str] = {}
    for fn in _package_mod.RULES:
        spec = get_lint_spec(fn)
        if spec.rule_id not in _D6C_PACKAGE_DIRECTORY_RULE_IDS:
            continue
        buf_id = _extract_buf_rule_id(spec.source_spec)
        if buf_id is not None:
            mapping[spec.rule_id] = buf_id
    return mapping


#: ``protokit_rule_id -> buf_rule_id`` for R8 + R8b. Built once at module
#: import; consumed by :func:`assert_parity_multi_file`'s package_directory
#: partition arm (KTD-12).
_PACKAGE_DIRECTORY_PROTO_TO_BUF: Mapping[str, str] = (
    _build_package_directory_proto_to_buf()
)

#: All R8/R8b protokit rule_ids as a frozenset for fast membership checks.
_PACKAGE_DIRECTORY_RULE_IDS_FROZEN: frozenset[str] = frozenset(
    _PACKAGE_DIRECTORY_PROTO_TO_BUF.keys()
)


def _build_rule_id_map() -> Mapping[str, str]:
    """Walk ``BUILTIN_PACKS`` and derive ``protokit_id -> buf_id``.

    Drops rules whose ``source_spec`` is not ``buf:*`` — those rules
    are protokit-only and not part of the parity contract.

    Uses ``get_lint_spec()`` (the documented external-caller
    accessor) so a malformed RULES tuple raises a clear
    ``TypeError`` rather than an opaque ``AttributeError``.

    **Canary inclusion** (post-D6c U2 KTD-11): the
    ``naming/snake-case-fields`` rule ships with
    ``source_spec="buf:FIELD_LOWER_SNAKE_CASE"`` and lands in the
    mapping via the standard ``buf:`` prefix path — no override
    layer needed. The post-walk assertion below guards the canary
    against an accidental revert of its source_spec back to the
    AIP-122 URL (which would silently drop it from the parity
    numerator). The direct-value assertion in
    :mod:`tests.schema.lint.test_canary_naming` is the primary
    source_spec contract; this fail-loud is the integration-layer
    backstop.
    """
    mapping: dict[str, str] = {}
    pack: ModuleType
    for pack in BUILTIN_PACKS:
        for fn in pack.RULES:
            spec = get_lint_spec(fn)
            protokit_id = spec.rule_id
            buf_id = _extract_buf_rule_id(spec.source_spec)
            if buf_id is not None:
                # Duplicate rule_id across packs (refactor collision,
                # accidental copy) would silently overwrite — every
                # subsequent parity test for the first rule would
                # then use the wrong buf_id. Fail loudly at module
                # import instead of silently producing wrong tests.
                if protokit_id in mapping and mapping[protokit_id] != buf_id:
                    raise AssertionError(
                        f"BUILTIN_PACKS registers protokit rule_id "
                        f"{protokit_id!r} twice with conflicting buf "
                        f"mappings: existing={mapping[protokit_id]!r}, "
                        f"new={buf_id!r}. Check for a duplicate "
                        f"@lint_rule decoration across rule packs."
                    )
                mapping[protokit_id] = buf_id
            # else: rule is protokit-only — excluded from parity.
    # Post-walk assertion: the canary must land in the mapping via the
    # ``buf:`` source_spec path. If this fails, the canary's source_spec
    # was reverted to a non-``buf:`` value (e.g., the AIP-122 URL it
    # carried pre-D6c U2) and the rule has silently dropped from the
    # parity numerator. See test_canary_naming.py:73 for the direct
    # source_spec value assertion.
    assert "naming/snake-case-fields" in mapping, (
        "canary rule 'naming/snake-case-fields' dropped from "
        "RULE_ID_MAP — source_spec may have reverted away from "
        "'buf:FIELD_LOWER_SNAKE_CASE'. See test_canary_naming.py for "
        "the direct value contract; KTD-11 in docs/plans/2026-05-18-"
        "003-feat-d6c-r8-r8b-cross-file-package-rules-plan.md for the "
        "audit-trail rationale."
    )
    return mapping


#: Module-level computed rule-id map. Exposed as a fixture below;
#: also importable for collection-time invariants in test modules.
RULE_ID_MAP: Mapping[str, str] = _build_rule_id_map()


def _validate_parity_exceptions() -> None:
    """Fail collection if ``_PARITY_EXCEPTIONS`` references unknown rule_ids,
    invalid posture values, or fixture files that do not exist on disk.

    Drift between the exceptions allowlist and the actual rule
    registry / fixture tree would silently mask a divergence (entry-
    for-deleted-rule, fixture rename) or fire spuriously (typo in
    rule_id or posture). Validating once at import keeps the harness
    in lockstep with both the rule registry AND the fixture corpus.
    """
    known_rules = set(RULE_ID_MAP.keys())
    fixtures_root = Path(__file__).resolve().parent / "fixtures"
    for (rule_id, fixture_stem), (posture, _reason) in _PARITY_EXCEPTIONS.items():
        if rule_id not in known_rules:
            raise AssertionError(
                f"_PARITY_EXCEPTIONS references unknown rule_id "
                f"{rule_id!r}; known parity rules: {sorted(known_rules)!r}"
            )
        if posture not in _VALID_POSTURES:
            raise AssertionError(
                f"_PARITY_EXCEPTIONS entry ({rule_id!r}, {fixture_stem!r}) "
                f"has invalid posture {posture!r}; valid: "
                f"{sorted(_VALID_POSTURES)!r}"
            )
        # Validate fixture_stem corresponds to an actual file under
        # tests/parity/fixtures/<rule_id>/. The harness convention is
        # one fixture directory per rule_id; the stem maps to
        # ``<rule_id>/<stem>.proto`` relative to fixtures_root.
        fixture_path = fixtures_root / rule_id / f"{fixture_stem}.proto"
        if not fixture_path.is_file():
            raise AssertionError(
                f"_PARITY_EXCEPTIONS entry ({rule_id!r}, {fixture_stem!r}) "
                f"references fixture {fixture_path} which does not exist. "
                f"Update the entry or restore the fixture."
            )


_validate_parity_exceptions()


# ---- Fixtures ---------------------------------------------------------------


@pytest.fixture(scope="session")
def rule_id_map() -> Mapping[str, str]:
    """Protokit rule_id -> buf rule_id, derived from BUILTIN_PACKS."""
    return RULE_ID_MAP


@pytest.fixture(scope="session")
def parity_exceptions() -> ParityExceptionsMap:
    """Documented divergences keyed by (rule_id, fixture_stem)."""
    return _PARITY_EXCEPTIONS


@pytest.fixture(scope="session")
def buf_deprecated_rules() -> frozenset[str]:
    """Buf rule IDs that cannot be exercised by the harness (deprecated upstream)."""
    return _BUF_DEPRECATED_RULES


def skip_if_buf_deprecated(buf_rule_id: str, protokit_rule_id: str) -> None:
    """Skip the current test cleanly when ``buf_rule_id`` is upstream-deprecated.

    Call this from a per-family ``test_parity`` method **before** any
    subprocess invocation. Skipping early avoids buf returning exit 1
    with ``"resultRules was empty"`` — which the new
    ``run_buf_lint`` exit-code guard correctly surfaces as a failure
    rather than letting it become a silent-green test.
    """
    if buf_rule_id in _BUF_DEPRECATED_RULES:
        pytest.skip(
            f"buf:{buf_rule_id} is deprecated in the pinned buf version "
            f"(categories=[], deprecated=true); protokit's "
            f"{protokit_rule_id!r} is protokit-only for this buf pin. "
            f"See _BUF_DEPRECATED_RULES in tests/parity/conftest.py."
        )


@pytest.fixture(scope="session")
def buf_binary() -> Path:
    """Resolve the buf binary; session-scoped wrapper around shared helper.

    Delegates to :func:`tests._buf_helpers.discover_buf_binary`. Kept
    as a session-scoped fixture so the parity harness skips cleanly
    when buf isn't available without re-running discovery for every
    parametrized test. The shared module references ``_BUF_PARITY_PIN``
    in its skip message, so the actionable error remains identical.
    """
    return discover_buf_binary()


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    """Absolute path to ``tests/parity/fixtures/``."""
    return Path(__file__).resolve().parent / "fixtures"


# ---- Subprocess helpers -----------------------------------------------------
# ce:review follow-up (Finding #9): the previous in-line
# _fail_subprocess + _stderr_repr + _run_subprocess implementations
# were moved verbatim to tests/_buf_helpers.py so the U4 smoke harness
# (tests/schema/lint/test_buf_smoke_assumptions.py) could reuse them.
# Parity-harness callers now route through run_buf_subprocess imported
# at the top of this module — same 30s timeout + triple-arm guard +
# diagnostic message format.


#: Buf exit codes that the harness treats as "ran successfully":
#:   0 = clean (no findings)
#:   100 = findings present
#: Anything else (1 = error / misconfiguration, 2 = unknown command,
#: 127 = binary missing, 128+signal, etc.) is a buf-side failure that
#: would otherwise produce silent-green tests via the empty-stdout
#: fall-through. The check below makes those failures loud.
_BUF_OK_EXIT_CODES: frozenset[int] = frozenset({0, 100})


def run_buf_lint(
    buf_binary_path: Path, fixture_dir: Path
) -> list[dict[str, Any]]:
    """Run ``buf lint --error-format=json`` against ``fixture_dir``.

    Returns a list of finding dicts parsed from buf's NDJSON output.
    Each dict carries at minimum ``path``, ``start_line``, and
    ``type`` (the buf rule_id). Empty list = no findings (clean
    lint). Buf exits 0 on a clean run and 100 when findings exist;
    any other exit code is a buf-side failure (misconfiguration,
    crash, missing binary) — surface those as test failures rather
    than silently returning ``[]``.
    """
    result = run_buf_subprocess(
        [str(buf_binary_path), "lint", "--error-format=json", "."],
        cwd=fixture_dir,
        label="buf lint",
    )
    if result.returncode not in _BUF_OK_EXIT_CODES:
        pytest.fail(
            f"buf lint exited {result.returncode} "
            f"(expected 0=clean or 100=findings) on cwd={fixture_dir}. "
            f"stderr: {result.stderr!r}; stdout: {result.stdout!r}"
        )
    findings: list[dict[str, Any]] = []
    if not result.stdout.strip():
        return findings
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"buf lint emitted non-JSON line {line!r} (cwd={fixture_dir}); "
                f"parse error: {exc}. Full stdout: {result.stdout!r}; "
                f"stderr: {result.stderr!r}"
            )
        findings.append(parsed)
    return findings


def run_protokit_lint(
    fixture_dir: Path, proto_relpath: str
) -> list[dict[str, Any]]:
    """Run ``protokit lint --proto --format json`` against one .proto.

    ``proto_relpath`` is the file's path relative to ``fixture_dir``;
    that directory is also the ``-I`` import path so transitive
    imports resolve. Findings come back from the ``lint_json``
    root's ``findings`` array. Empty list = no findings.
    """
    proto_path = fixture_dir / proto_relpath
    if not proto_path.is_file():
        pytest.fail(
            f"protokit lint: fixture {proto_path} does not exist "
            f"(fixture_dir={fixture_dir}, proto_relpath={proto_relpath!r})"
        )
    # Invoke via ``python -c "from protokit.cli import main; main()"``
    # rather than ``python -m protokit`` — the package has no
    # ``__main__``; the console_script entry point in pyproject.toml
    # is the only public invocation surface. Using ``sys.executable``
    # ensures the test inherits the venv pytest is running under.
    result = run_buf_subprocess(
        [
            sys.executable,
            "-c",
            "from protokit.cli import main; main()",
            "lint",
            "--proto",
            "--format",
            "json",
            "-I",
            str(fixture_dir),
            str(proto_path),
        ],
        cwd=fixture_dir,
        label="protokit lint",
    )
    # protokit lint exit codes (R20 ladder):
    #   0 = clean (no findings)
    #   1 = findings present (or WARNINGs exceed --max-warnings)
    #   2 = lint-internal error / click usage error
    # Any other exit code (e.g., 127 from CLI rename causing
    # ImportError, 128+signal from OOM, 130 from SIGINT) would
    # otherwise fall through ``if not result.stdout.strip(): return []``
    # and produce a silent-green parity test (no findings, no errors)
    # even when the harness's CLI invocation is broken.
    if result.returncode not in (0, 1):
        pytest.fail(
            f"protokit lint exited {result.returncode} "
            f"(expected 0=clean or 1=findings) on {proto_path}; "
            f"stderr: {result.stderr!r}; stdout: {result.stdout!r}"
        )
    if not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"protokit lint produced non-JSON stdout for {proto_path}: "
            f"{exc}. stdout: {result.stdout!r}; stderr: {result.stderr!r}"
        )
    findings_obj = payload.get("findings", [])
    if not isinstance(findings_obj, list):
        pytest.fail(
            f"protokit lint JSON 'findings' is not a list "
            f"(type={type(findings_obj).__name__}); payload: {payload!r}"
        )
    return findings_obj


def run_protokit_lint_multi_file(
    fixture_dir: Path,
    *,
    rule_pack: str | None = None,
    proto_paths: tuple[Path, ...] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Run ``protokit lint --proto --format json`` against ALL ``.proto``
    files in ``fixture_dir`` (recursive). Multi-file analog of
    ``run_protokit_lint`` above.

    Required for rule families whose emit shape depends on cross-file
    state (R7 PACKAGE_SAME_*'s all-disagreers-fire semantics need every
    package file in one invocation so the engine's cross-file
    accumulator sees every option value).

    **Recursion is REQUIRED**: ``googleapis-import/google/api/*.proto``
    and ``wkt-conflict/google/protobuf/*.proto`` live two directories
    deep in the U4a-committed smoke fixtures and produce the buf
    findings the parity test must match. A non-recursive glob would
    silently lint only the fixture-root ``a.proto``.

    ``proto_paths`` defaults to ``(fixture_dir,)``. ``-I`` is passed
    as a path **relative to** ``cwd=fixture_dir`` (typically ``.``)
    so protokit's emitted ``location`` is fixture-root-relative
    (e.g., ``"a.proto"``) — aligning with buf's recorded NDJSON
    ``path`` field after ``_normalize_buf_path``. Absolute
    ``-I str(fixture_dir)`` would produce absolute ``location``
    strings that fail ``assert_parity_multi_file`` path comparisons.

    Shadow paths:
      - NIL: ``fixture_dir`` containing zero ``.proto`` files →
        ``pytest.fail`` naming the empty path.
      - ERROR: subprocess exit outside ``(0, 1)`` → ``pytest.fail``
        matching the single-file pattern.
      - EMPTY: a zero-byte ``.proto`` routes through exit-code-2
        surfacing (protoc rejects empty files lacking ``syntax``);
        no special-case branch needed.
    """
    proto_files = sorted(fixture_dir.rglob("*.proto"))
    if not proto_files:
        pytest.fail(
            f"run_protokit_lint_multi_file: no .proto files found under "
            f"{fixture_dir} (rglob exhausted). Verify the fixture "
            f"directory is populated."
        )
    if proto_paths is None:
        proto_paths = (fixture_dir,)
    argv: list[str] = [
        sys.executable,
        "-c",
        "from protokit.cli import main; main()",
        "lint",
        "--proto",
        "--format",
        "json",
    ]
    for include_path in proto_paths:
        rel = "." if include_path == fixture_dir else str(
            include_path.relative_to(fixture_dir)
        )
        argv.extend(["-I", rel])
    if rule_pack is not None:
        argv.extend(["--rule-pack", rule_pack])
    for proto_file in proto_files:
        argv.append(str(proto_file.relative_to(fixture_dir)))
    result = run_buf_subprocess(
        argv, cwd=fixture_dir, label="protokit lint multi-file"
    )
    if result.returncode not in (0, 1):
        pytest.fail(
            f"protokit lint exited {result.returncode} "
            f"(expected 0=clean or 1=findings) on fixture_dir={fixture_dir} "
            f"with {len(proto_files)} .proto file(s); "
            f"stderr: {result.stderr!r}; stdout: {result.stdout!r}"
        )
    if not result.stdout.strip():
        return ()
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"protokit lint produced non-JSON stdout for {fixture_dir}: "
            f"{exc}. stdout: {result.stdout!r}; stderr: {result.stderr!r}"
        )
    findings_obj = payload.get("findings", [])
    if not isinstance(findings_obj, list):
        pytest.fail(
            f"protokit lint JSON 'findings' is not a list "
            f"(type={type(findings_obj).__name__}); payload: {payload!r}"
        )
    # File-level findings have no per-line position in lint_json; sort
    # by (location, rule_id) for deterministic test diagnostics.
    findings_obj.sort(key=lambda f: (
        str(f.get("location", "")),
        str(f.get("rule_id", "")),
    ))
    return tuple(findings_obj)


# ---- Parity assertion -------------------------------------------------------


def _normalize_buf_path(buf_path: str | None) -> str:
    """Normalize buf's emitted path so leading ``./`` or OS separators
    don't desync from the in-test ``proto_relpath`` strings.

    Buf v1.69.0 emits POSIX-relative paths without a leading ``./``
    (verified empirically), but a future release could change the
    convention. Normalizing both sides through
    ``PurePosixPath(...).as_posix()`` removes a class of silent
    false-passes on nested-directory fixtures.
    """
    if not buf_path:
        return ""
    from pathlib import PurePosixPath
    return PurePosixPath(buf_path).as_posix()


def parse_buf_recorded_snapshot(snapshot_path: Path) -> tuple[BufFinding, ...]:
    """Parse a buf v1.69.0 recorded NDJSON snapshot into typed ``BufFinding`` tuples.

    Multi-file analog of the live-mode parsing in ``run_buf_lint``
    above (which parses live buf stdout into raw dicts). U6's
    recorded-snapshot mode reads pre-captured byte-pinned snapshots
    rather than re-invoking buf at test time; the typed shape
    supports byte-stable sort + multiset comparison in
    ``assert_parity_multi_file``.

    Snapshot fields verified empirically against
    ``tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/*.json``
    (D6b U4a, SHA-pinned by
    ``tests/schema/lint/test_buf_smoke_recorded_checksums.py``):
    ``path``, ``start_line``, ``start_column``, ``end_line``,
    ``end_column``, ``type``, ``message``.

    Empty file (zero bytes — e.g., ``all-agree.json``,
    ``wkt-only.json`` both at SHA ``e3b0c44...``) yields ``()``.
    Missing or malformed JSON fields fail loudly with the snapshot
    path so a future buf release that changes the NDJSON shape is
    surfaced immediately.

    Findings are sorted by ``(path, start_line, start_column, type)``
    for deterministic comparison.
    """
    if not snapshot_path.is_file():
        pytest.fail(
            f"recorded snapshot not found: {snapshot_path}. "
            f"Verify _buf_smoke/recorded/ is populated and "
            f"CHECKSUMS.sha256 still validates via "
            f"tests/schema/lint/test_buf_smoke_recorded_checksums.py."
        )
    findings: list[BufFinding] = []
    for raw_line in snapshot_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"recorded snapshot {snapshot_path} has malformed NDJSON "
                f"line {line!r}: {exc}"
            )
        try:
            findings.append(BufFinding(
                path=data["path"],
                start_line=data["start_line"],
                start_column=data["start_column"],
                end_line=data["end_line"],
                end_column=data["end_column"],
                type=data["type"],
                message=data["message"],
            ))
        except KeyError as exc:
            pytest.fail(
                f"recorded snapshot {snapshot_path} line {line!r} missing "
                f"required field {exc}; buf v1.69.0 NDJSON shape expected: "
                f"path, start_line, start_column, end_line, end_column, "
                f"type, message."
            )
    findings.sort(key=lambda f: (f.path, f.start_line, f.start_column, f.type))
    return tuple(findings)


def _filter_buf_findings_by_rule(
    findings: list[dict[str, Any]], buf_rule_id: str, target_path: str
) -> list[dict[str, Any]]:
    """Filter NDJSON findings to (matching rule, matching file path).

    Paths are normalized through ``_normalize_buf_path`` so buf's
    emitted path format and our in-test ``proto_relpath`` stay
    aligned regardless of leading-``./`` or OS-separator drift.
    """
    matched: list[dict[str, Any]] = []
    normalized_target = _normalize_buf_path(target_path)
    for f in findings:
        # buf JSON shape (verified by test_buf_output_shape.py):
        #   {"path": "bad.proto", "start_line": N, "type": "RULE_ID", ...}
        if f.get("type") != buf_rule_id:
            continue
        if _normalize_buf_path(f.get("path")) != normalized_target:
            continue
        matched.append(f)
    return matched


def _filter_protokit_findings_by_rule(
    findings: list[dict[str, Any]], protokit_rule_id: str
) -> list[dict[str, Any]]:
    """Filter protokit lint_json findings to those matching ``rule_id``."""
    return [f for f in findings if f.get("rule_id") == protokit_rule_id]


def case_id(rule_id: str, proto_relpath: str, expected_fires: bool) -> str:
    """Render a readable parametrize id like ``pascal-case-messages-bad-sad``.

    Used by per-family test modules to label parametrized cases.
    Lives in conftest so all 5 modules share one definition; previously
    each module had a local ``_case_id`` copy that drifted in docstring.
    """
    rule_short = rule_id.split("/", 1)[1] if "/" in rule_id else rule_id
    fixture_stem = Path(proto_relpath).stem
    branch = "sad" if expected_fires else "happy"
    return f"{rule_short}-{fixture_stem}-{branch}"


def assert_parity(
    protokit_findings: list[dict[str, Any]],
    buf_findings: list[dict[str, Any]],
    protokit_rule_id: str,
    buf_rule_id: str,
    proto_relpath: str,
    expected_fires: bool,
    parity_exceptions: ParityExceptionsMap,
) -> None:
    """Assert protokit and buf produce equivalent findings on a fixture.

    ``expected_fires`` is the *parity-expected* outcome: True for
    sad-path fixtures (both tools should fire); False for
    happy-path fixtures (neither should fire). Per-rule deviations
    from this baseline must appear in ``parity_exceptions``,
    keyed by ``(protokit_rule_id, fixture_stem)`` where
    ``fixture_stem`` is ``Path(proto_relpath).stem``.

    Skips at runtime when ``buf_rule_id`` is in
    ``_BUF_DEPRECATED_RULES``: buf no longer ships the rule in any
    category, so a parity claim is not testable. The protokit rule
    remains active; this is just a harness limitation.
    """
    if buf_rule_id in _BUF_DEPRECATED_RULES:
        pytest.skip(
            f"buf:{buf_rule_id} is deprecated in the pinned buf version "
            f"(categories=[], deprecated=true); protokit's "
            f"{protokit_rule_id!r} is protokit-only for this buf pin. "
            f"See _BUF_DEPRECATED_RULES in tests/parity/conftest.py."
        )
    protokit_matches = _filter_protokit_findings_by_rule(
        protokit_findings, protokit_rule_id
    )
    buf_matches = _filter_buf_findings_by_rule(
        buf_findings, buf_rule_id, proto_relpath
    )
    fixture_stem = Path(proto_relpath).stem
    exception_key = (protokit_rule_id, fixture_stem)
    exception = parity_exceptions.get(exception_key)

    protokit_fired = len(protokit_matches) > 0
    buf_fired = len(buf_matches) > 0

    if exception is not None:
        posture, reason = exception
        if posture == "protokit_stricter":
            assert protokit_fired, (
                f"documented exception {exception_key!r} says "
                f"'protokit_stricter' ({reason}) but protokit did NOT fire "
                f"on {proto_relpath}. If the divergence has been resolved, "
                f"remove the _PARITY_EXCEPTIONS entry."
            )
            assert not buf_fired, (
                f"documented exception {exception_key!r} says "
                f"'protokit_stricter' ({reason}) but buf DID fire "
                f"on {proto_relpath}. Buf may have changed its behavior; "
                f"investigate whether the divergence still holds."
            )
            return
        if posture == "protokit_looser":
            assert not protokit_fired, (
                f"documented exception {exception_key!r} says "
                f"'protokit_looser' ({reason}) but protokit DID fire on "
                f"{proto_relpath}; either fix the rule or remove the entry."
            )
            assert buf_fired, (
                f"documented exception {exception_key!r} says "
                f"'protokit_looser' ({reason}) but buf did NOT fire on "
                f"{proto_relpath}; investigate."
            )
            return
        pytest.fail(
            f"_PARITY_EXCEPTIONS entry {exception_key!r} has unknown "
            f"posture {posture!r}; valid: 'protokit_stricter', "
            f"'protokit_looser'."
        )

    if expected_fires:
        assert protokit_fired and buf_fired, (
            f"parity sad-path: expected BOTH tools to fire on "
            f"{proto_relpath} for rule {protokit_rule_id} "
            f"(buf:{buf_rule_id}); protokit_fired={protokit_fired}, "
            f"buf_fired={buf_fired}. "
            f"protokit findings: {protokit_matches!r}; "
            f"buf findings: {buf_matches!r}"
        )
    else:
        assert not protokit_fired and not buf_fired, (
            f"parity happy-path: expected NEITHER tool to fire on "
            f"{proto_relpath} for rule {protokit_rule_id} "
            f"(buf:{buf_rule_id}); protokit_fired={protokit_fired}, "
            f"buf_fired={buf_fired}. "
            f"protokit findings: {protokit_matches!r}; "
            f"buf findings: {buf_matches!r}"
        )


# ---- Multi-file parity assertion (D6b U6) -----------------------------------


def assert_parity_multi_file(
    protokit_findings: Sequence[dict[str, Any]],
    buf_findings: Sequence[BufFinding],
    *,
    protokit_rule_ids: frozenset[str],
    fixture_scenario: str,
) -> None:
    """Assert per-file finding-set parity for the multi-file emit shape.

    Multi-file analog of ``assert_parity`` above. R7 PACKAGE_SAME_*
    rules emit one finding per file in a package when disagreement
    exists (all-disagreers-fire). Comparison is scoped per-fixture
    to the rule_id(s) named in ``protokit_rule_ids`` (typically the
    single rule that fixture's ``buf.yaml use:[]`` enables — per
    KD-7 in the D6b U6 plan); other R7 rules + non-R7 rules (D6a
    families fired by ``BUILTIN_PACKS``) are excluded from the
    assertion.

    Two-sided rule-id check catches three failure modes:

      (i)  Under-firing — protokit fails to fire when buf fires
           (or fires fewer findings than buf).
      (ii) Over-firing — protokit fires for a non-scoped R7 rule_id
           on this fixture (would happen if a future helper edit
           made e.g. ``package/same-java-package`` fire on a
           ``go_package``-only fixture). Catches latent-symmetry
           regressions per KD-7's rationale.
      (iii) Message-text drift — protokit's message bytes diverge
            from buf's for the same (path, rule_id) tuple.

    Comparison uses multiset equality on
    ``(buf_rule_id, normalized_path, message)`` tuples — protokit's
    file-level findings have no ``line``/``col`` in ``lint_json``
    output (verified empirically against R7's ``location: "a.proto"``
    shape), so ``(path, message)`` is the natural per-finding key.
    Sort-key uniqueness was empirically verified for all 21 U4a
    snapshots at U6 implementation time; the pre-assertion below
    surfaces any future drift.

    Diagnostic on failure names ``fixture_scenario`` + the
    diverging side(s) + a decision-tree hint so a maintainer can
    route immediately (fix protokit vs document via
    ``_PARITY_EXCEPTIONS``).
    """
    # ---- Sort-key uniqueness pre-assertion --------------------------
    buf_keys = [(f.path, f.start_line, f.start_column, f.type) for f in buf_findings]
    if len(buf_keys) != len(set(buf_keys)):
        duplicates = sorted({k for k in buf_keys if buf_keys.count(k) > 1})
        pytest.fail(
            f"assert_parity_multi_file({fixture_scenario}): buf snapshot has "
            f"duplicate (path, start_line, start_column, type) sort keys "
            f"({len(duplicates)} duplicate group(s)) — uniqueness assumption "
            f"broken. Either the snapshot has truly identical findings "
            f"(re-verify against buf v1.69.0) or the comparison shape needs "
            f"to include 'message' as a fourth discriminator. "
            f"Duplicate keys: {duplicates!r}"
        )

    # ---- Partition protokit findings: scoped / over-firing / unknown -----
    # Per D6c U3 KTD-12: the partition logic now supports TWO rule
    # families with their own ``_PROTO_TO_BUF`` mappings:
    #
    #   - R7 PACKAGE_SAME_* family (``_PACKAGE_SAME_PROTO_TO_BUF``)
    #   - R8 + R8b cross-file family (``_PACKAGE_DIRECTORY_PROTO_TO_BUF``)
    #
    # The union dictionary is computed once per call from
    # ``protokit_rule_ids``'s family membership — both families share the
    # same partition shape (in-scope / over-firing / unknown) but read
    # from family-specific mappings. The over-firing and unknown buckets
    # combine across families so a future cross-family typo (e.g., a
    # rule_id mis-prefixed as ``package/same-directory-same-package``)
    # surfaces in the unknown diagnostic rather than silently leaking.
    family_proto_to_buf: dict[str, str] = {
        **_PACKAGE_SAME_PROTO_TO_BUF,
        **_PACKAGE_DIRECTORY_PROTO_TO_BUF,
    }
    family_rule_ids: frozenset[str] = (
        _PACKAGE_SAME_RULE_IDS | _PACKAGE_DIRECTORY_RULE_IDS_FROZEN
    )
    # Family-aware unknown-prefix discriminator. R7 rules start with
    # ``package/same-`` (specifically ``package/same-<lang>``); R8/R8b
    # start with ``package/same-directory`` or ``package/directory-``.
    # Any rule_id starting with ``package/`` but NOT in the known
    # registry is potentially typo'd; the diagnostic shapes the message
    # so the offender can be routed to the right rule pack.

    protokit_in_scope: list[tuple[str, str, str]] = []  # (buf_id, path, msg)
    protokit_overfire: list[tuple[str, str, str]] = []  # (rule_id, path, msg)
    protokit_unknown: list[tuple[str, str, str]] = []   # (rule_id, path, msg)
    for f in protokit_findings:
        rule_id = str(f.get("rule_id", ""))
        path = _normalize_buf_path(str(f.get("location", "")))
        message = str(f.get("message", ""))
        if rule_id in protokit_rule_ids:
            protokit_in_scope.append(
                (family_proto_to_buf[rule_id], path, message)
            )
        elif rule_id in family_rule_ids:
            # Over-firing complement: a known family rule fired but is
            # outside the per-fixture scope (KD-7 for R7, KTD-12 for
            # R8/R8b).
            protokit_overfire.append((rule_id, path, message))
        elif (
            rule_id.startswith("package/same-")
            and rule_id != "package/same-directory"
        ):
            # Looks like an R7 family prefix but not in the registry —
            # most likely a typo in a future @lint_rule decoration.
            # Surface as a distinct error so the diagnostic points at
            # registration, not at under-firing (per ADV-3 ce:review
            # finding). The carve-out for ``package/same-directory``
            # (R8) handles the cross-family ambiguity: that exact
            # rule_id starts with ``package/same-`` (R7's prefix) but
            # belongs to the R8 family; the ``in family_rule_ids``
            # check above already accepts it.
            protokit_unknown.append((rule_id, path, message))
        # Non-family findings (e.g., D6a's ``package/defined`` and
        # ``package/directory-match`` from the same ``package`` pack,
        # or other rule packs loaded by BUILTIN_PACKS) are excluded
        # from the assertion — they are correct + expected for the
        # smoke fixtures. R8/R8b have only two specific rule_ids
        # (``package/same-directory`` + ``package/directory-same-package``)
        # so prefix-based typo detection is unnecessary for that family:
        # a typo'd R8/R8b rule_id would fall into the "non-family"
        # excluded bucket, not the unknown bucket. The R7 family's
        # broader 7-rule footprint motivates the prefix check.

    if protokit_unknown:
        pytest.fail(
            f"assert_parity_multi_file({fixture_scenario}): protokit emitted "
            f"finding(s) with rule_id matching a known-family prefix "
            f"(``package/same-*`` or ``package/directory-*``) that are "
            f"NOT in the family registries — possible typo or unregistered "
            f"rule. Unknown rule_ids: "
            f"{sorted({r for r, _, _ in protokit_unknown})!r}. "
            f"Known R7 rule_ids: {sorted(_PACKAGE_SAME_RULE_IDS)!r}. "
            f"Known R8/R8b rule_ids: "
            f"{sorted(_PACKAGE_DIRECTORY_RULE_IDS_FROZEN)!r}. "
            f"Fix at the @lint_rule decoration in "
            f"src/protokit/schema/lint/rules/package_same.py (R7) or "
            f"src/protokit/schema/lint/rules/package.py (R8/R8b)."
        )

    if protokit_overfire:
        pytest.fail(
            f"assert_parity_multi_file({fixture_scenario}): protokit fired "
            f"known-family rule(s) outside the per-fixture scope "
            f"{sorted(protokit_rule_ids)!r}. "
            f"Over-firing findings: {sorted(protokit_overfire)!r}. "
            f"Decision tree:\n"
            f"  If protokit's emit shape changed for the unexpected rule_id, "
            f"investigate src/protokit/schema/lint/rules/package_same.py "
            f"(R7) or src/protokit/schema/lint/rules/package.py (R8/R8b).\n"
            f"  If the fixture should now exercise multiple rules, update "
            f"the fixture's buf.yaml use:[] and the parity test's "
            f"per-fixture scope derivation (KD-7 / KTD-12)."
        )

    # ---- Build buf comparison set scoped to expected rule_ids ------
    expected_buf_types: set[str] = {
        family_proto_to_buf[rid] for rid in protokit_rule_ids
        if rid in family_proto_to_buf
    }
    buf_in_scope: list[tuple[str, str, str]] = sorted(
        (f.type, _normalize_buf_path(f.path), f.message)
        for f in buf_findings if f.type in expected_buf_types
    )
    protokit_in_scope.sort()

    # ---- Multiset equality with structured diagnostic --------------
    if protokit_in_scope != buf_in_scope:
        protokit_set = set(protokit_in_scope)
        buf_set = set(buf_in_scope)
        only_protokit = sorted(protokit_set - buf_set)
        only_buf = sorted(buf_set - protokit_set)
        pytest.fail(
            f"assert_parity_multi_file({fixture_scenario}): protokit ↔ buf "
            f"finding-set divergence within scoped rule_ids "
            f"{sorted(protokit_rule_ids)!r} "
            f"(buf-equivalent {sorted(expected_buf_types)!r}).\n"
            f"  Only-in-protokit ({len(only_protokit)}): {only_protokit!r}\n"
            f"  Only-in-buf       ({len(only_buf)}): {only_buf!r}\n"
            f"Decision tree:\n"
            f"  If protokit is correct, document via _PARITY_EXCEPTIONS + "
            f"four-site discipline (per buf-parity-divergence-documentation-"
            f"discipline-2026-05-13).\n"
            f"  If buf is correct, fix the helper at "
            f"src/protokit/schema/lint/rules/package_same.py:"
            f"_check_package_option."
        )
