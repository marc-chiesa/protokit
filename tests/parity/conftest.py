"""Buf-parity test harness — D6a Unit 8 Phase A.

This conftest powers ``tests/parity/`` — the in-repo harness that
runs every D6a buf-equivalent rule's fixtures through both
``protokit lint`` and ``buf lint`` and asserts equivalent findings.
Tests under this tree are gated by ``@pytest.mark.parity`` (each
module sets ``pytestmark = pytest.mark.parity``); default
``pytest tests/`` skips the entire tree because the marker is not
selected by default.

Resolved decisions (see ``docs/plans/2026-05-13-001-feat-d6a-u8-parity-test-infra-plan.md``):

- **Rule-id mapping is derived from ``LintRuleSpec.source_spec``.**
  Walking ``BUILTIN_PACKS`` at collection time stays in lockstep
  with rule additions in future deliveries.
- **Canary parity is functional, not nominal.** The D2 canary's
  ``source_spec="https://google.aip.dev/122"`` is the correct
  provenance (aip.dev defines the original spec). The
  ``_CANARY_PARITY_OVERRIDE`` map below adds a behavior-only
  equivalence to buf's ``FIELD_LOWER_SNAKE_CASE``. **Any future
  change to the canary's ``_SNAKE_CASE_RE`` regex requires
  re-validating buf parity against the pinned buf version.**
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
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any, Literal, NoReturn

import pytest

from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.rules import BUILTIN_PACKS

#: Type alias for the parity-exceptions mapping. Keys are
#: ``(protokit_rule_id, fixture_stem)``; values are
#: ``(posture, reason)`` where posture is one of
#: ``"protokit_stricter"`` or ``"protokit_looser"``.
ParityPosture = Literal["protokit_stricter", "protokit_looser"]
ParityExceptionsMap = Mapping[tuple[str, str], tuple[ParityPosture, str]]
_VALID_POSTURES: frozenset[str] = frozenset({"protokit_stricter", "protokit_looser"})

#: Functional buf-parity override for the D2 canary
#: ``naming/snake-case-fields``. The canary's ``source_spec`` is
#: AIP-122 (the original spec), not ``buf:FIELD_LOWER_SNAKE_CASE``.
#: Behavior is functionally equivalent (lower_snake_case
#: enforcement with synthetic map-entry fields excluded), so the
#: parity test maps the canary to buf's rule via this override
#: rather than rewriting the canary's provenance metadata.
#:
#: If the canary's regex (``_SNAKE_CASE_RE`` in
#: ``src/protokit/schema/lint/rules/naming.py``) changes,
#: re-validate buf parity against the pinned buf version before
#: shipping the change.
_CANARY_PARITY_OVERRIDE: Mapping[str, str] = {
    "naming/snake-case-fields": "FIELD_LOWER_SNAKE_CASE",
}

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


def _build_rule_id_map() -> Mapping[str, str]:
    """Walk ``BUILTIN_PACKS`` and derive ``protokit_id -> buf_id``.

    Drops rules whose ``source_spec`` is neither ``buf:*`` nor
    listed in ``_CANARY_PARITY_OVERRIDE`` — those rules are
    protokit-only and not part of the parity contract.

    Uses ``get_lint_spec()`` (the documented external-caller
    accessor) so a malformed RULES tuple raises a clear
    ``TypeError`` rather than an opaque ``AttributeError``.
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
            elif protokit_id in _CANARY_PARITY_OVERRIDE:
                if protokit_id in mapping:
                    raise AssertionError(
                        f"_CANARY_PARITY_OVERRIDE entry {protokit_id!r} "
                        f"collides with a buf:-sourced rule already in "
                        f"BUILTIN_PACKS. The override is dead code; "
                        f"either remove it or change the rule's "
                        f"source_spec away from a buf: prefix."
                    )
                mapping[protokit_id] = _CANARY_PARITY_OVERRIDE[protokit_id]
            # else: rule is protokit-only — excluded from parity.
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
    """Resolve the buf binary from $BUF_BINARY then PATH; skip the test otherwise.

    Returning a Path makes downstream subprocess invocations clean
    (str-coerced at the boundary). A missing binary triggers
    ``pytest.skip(...)`` so the parity tests are graceful in
    default ``pytest tests/`` runs on machines without buf
    installed (the ``@pytest.mark.parity`` marker is documentary;
    CI's dedicated parity job installs buf and runs the tests
    with the marker explicitly selected). $BUF_BINARY pointing at
    a non-existent file is a misconfiguration, not a missing
    install, so it fails loudly instead of skipping.
    """
    env_var = os.environ.get("BUF_BINARY")
    if env_var:
        path = Path(env_var)
        if not path.is_file():
            pytest.fail(
                f"$BUF_BINARY is set to {env_var!r} but the file does not exist. "
                "Set BUF_BINARY to a valid buf executable, or unset it to fall "
                "back to PATH lookup."
            )
        return path
    resolved = shutil.which("buf")
    if resolved is None:
        pytest.skip(
            "buf binary not found: $BUF_BINARY is unset and `buf` is not on "
            "PATH. Install buf v1.69.0 from "
            "https://github.com/bufbuild/buf/releases/tag/v1.69.0 (or set "
            "BUF_BINARY to a local install) to run parity tests."
        )
    return Path(resolved)


@pytest.fixture(scope="session")
def fixtures_root() -> Path:
    """Absolute path to ``tests/parity/fixtures/``."""
    return Path(__file__).resolve().parent / "fixtures"


# ---- Subprocess helpers -----------------------------------------------------


def _fail_subprocess(msg: str) -> NoReturn:
    """``pytest.fail`` typed as ``NoReturn`` so mypy/readers see the
    contract: ``_run_subprocess``'s except arms never fall through."""
    pytest.fail(msg)
    raise AssertionError("unreachable")  # pragma: no cover -- defense vs stub rot


def _stderr_repr(stderr: bytes | str | None) -> str:
    """Render ``TimeoutExpired.stderr`` regardless of bytes/str/None.

    On POSIX, ``subprocess.TimeoutExpired.stderr`` is ``bytes`` even
    when the subprocess.run call passed ``text=True`` (the decode
    path runs only on the normal-exit branch). Normalize to a clean
    str repr so diagnostic messages don't show ``b'...'`` prefixes.
    """
    if stderr is None or stderr == b"" or stderr == "":
        return "(empty)"
    if isinstance(stderr, bytes):
        return repr(stderr.decode("utf-8", errors="replace"))
    return repr(stderr)


def _run_subprocess(
    argv: list[str], cwd: Path, label: str
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with a 30s wall-clock cap and triple-arm guard.

    The triple-arm guard ensures a Ctrl-C mid-invocation surfaces
    cleanly to pytest rather than corrupting session state. Errors
    re-raise as pytest failures with the tool's stderr attached
    for diagnostic context.
    """
    try:
        return subprocess.run(  # noqa: S603 -- argv is constructed in-test, never user input
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        _fail_subprocess(
            f"{label} invocation exceeded 30s wall-clock cap "
            f"(cwd={cwd}, argv={argv!r}). stderr so far: {_stderr_repr(exc.stderr)}"
        )
    except KeyboardInterrupt:
        raise
    except SystemExit:
        raise
    except Exception as exc:
        _fail_subprocess(
            f"{label} subprocess raised {type(exc).__name__}: {exc} "
            f"(cwd={cwd}, argv={argv!r})"
        )


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
    result = _run_subprocess(
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
    result = _run_subprocess(
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
