"""Strict-xfail regression pins for the U15 CLI-exit-path audit family.

Unit U1 of the 0.16.0 correctness plan *pins* confirmed findings; it
never fixes them. Every pin here asserts the behaviour the CLI's own
documented contract promises, so each test **fails today** and is
marked ``xfail(strict=True)``: the suite stays green while the defect
is live, and the moment U7/U8 land the fix the test ``xpass``es and
strict mode turns that into a loud failure. The ``reason=`` string of
every pin starts with its finding ID.

The contract these pins measure against is the one the project states
about itself:

* ``protokit compat`` — README.md: ``0 = compatible, 1 = incompatible,
  2 = error``, restated in ``schema/git.py``'s ``_git_failure_exit``
  docstring ("an escaping traceback exits 1, which a pipeline reads as
  a compatibility BREAK that never happened").
* ``protokit diff`` — ``message/cli.py`` module docstring and
  ``--help``: ``0 = equal, 1 = different, 2 = error``.
* ``docs/plans/2026-08-30-001-fix-0160-stability-release-plan.md``
  (U8): "Reserve exit 1 for 'the tool ran and found a problem'; use
  exit 2 for 'the tool could not run'"; (U7/V24) a truncated
  comparison "prints an INCOMPLETE verdict and emits ``equal: false``".

Two pins live in this schema-side file even though they exercise
``protokit.message.cli`` (U15-6, U15-7): the audit family is "CLI exit
paths", and the 0.16.0 plan assigns both of those call sites to U8
alongside the compat ones.

**Every pin names the exception it fails with.** Each ``xfail`` carries
``raises=`` and every ``CliRunner.invoke`` passes
``catch_exceptions=False``. Without both, Click folds any unhandled
exception into ``exit_code == 1`` and an unrestricted strict xfail
accepts the resulting assertion failure -- so an unrelated crash in a
subcommand, or a broken fixture, would keep a pin "green" for the wrong
reason. With them, the three pins whose defect *is* an escaping
exception (U15-2's iteration failure, U15-4's missing git, U15-6's
differ ``ValueError``) see that exact exception propagate out of the
runner and are narrowed to it; everything else is narrowed to the
assertion (or ``pytest.fail``) on its named line. Anything else is red.

**Deliberately not pinned — closed by 0.15.1.** The original U15-1
claim also covered a malformed ``--ignore`` on ``history`` / ``bisect``
(including on an empty commit range, which skipped checker
construction entirely). ``SchemaChecker.ignore`` now rejects it: on an
empty range both ``--ignore ''`` and ``--ignore 'bad..path'`` exit 2
with a clean ``Error: invalid --ignore path ...``. Pinning it would
``xpass``. The same release closed compat stderr forgery and the
``lint`` exit-0-on-crashed-rule gate; none of those are pinned here.

**Still live, deliberately left unpinned.** On an *empty* commit range,
``history`` / ``bisect`` also skip validation of ``--type`` and
``--compat-rule-pack``: ``--type acme.NoSuchType`` and
``--compat-rule-pack no.such.module`` both exit 0 with "no commits
touch", where ``check`` exits 2 for either. That is the same shape
0.15.1 fixed for ``--ignore`` (see the "V31" comment in
``schema/cli.py``), but the 0.16.0 plan only commits to validating
``--proto-file``, so asserting a specific outcome for those two flags
would be pinning behaviour this unit cannot defend. Reported, not
pinned.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
from click.testing import CliRunner

from protokit.message.cli import main as diff_main
from protokit.schema.cli import main as compat_main

# ---------------------------------------------------------------------------
# Git fixtures — same shape as tests/schema/test_cli.py's git_repo /
# _commit / _invoke_in_repo, duplicated rather than imported so this
# pin file does not depend on another test module's internals.
# ---------------------------------------------------------------------------

_USER_V1 = (
    'syntax = "proto3";\n'
    "package acme;\n"
    "message User { string name = 1; int32 age = 2; }\n"
)
_USER_V2_DROP = (
    'syntax = "proto3";\n'
    "package acme;\n"
    "message User { string name = 1; }\n"  # age removed — a real break
)


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialise a git repo with deterministic identity."""
    _git("init", "-q", "-b", "main", cwd=tmp_path)
    _git("config", "user.email", "t@t", cwd=tmp_path)
    _git("config", "user.name", "Test", cwd=tmp_path)
    _git("config", "commit.gpgsign", "false", cwd=tmp_path)
    return tmp_path


def _commit(repo: Path, path: str, contents: str, *, msg: str) -> str:
    full = repo / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(contents)
    _git("add", path, cwd=repo)
    _git("commit", "-q", "-m", msg, cwd=repo)
    return _git("rev-parse", "HEAD", cwd=repo)


@contextlib.contextmanager
def _temp_rule_pack(pack_name: str, rules: object):
    """Register a synthetic rule pack in ``sys.modules`` for one test.

    Three pins here need a rule pack that misbehaves in a different way,
    and each needs it visible to ``--compat-rule-pack``'s importlib
    lookup. Registering and popping by hand three times invites one of
    them to leak into a later test if an assertion raises, so the
    register/pop pair lives here behind ``try/finally``.
    """
    module = types.ModuleType(pack_name)
    module.RULES = rules
    sys.modules[pack_name] = module
    try:
        yield pack_name
    finally:
        sys.modules.pop(pack_name, None)


def _noisy_rule(ctx):
    """A rule whose only effect is writing to stdout.

    Used by the pins that show a rule pack's ``print`` corrupting
    ``--format json`` and leaking past ``--quiet``.
    """
    print("noisy_rule: examining field")
    return None


def _invoke_in_repo(repo: Path, args: list[str]):
    """Run the compat CLI with cwd=repo so git commands resolve."""
    import os

    runner = CliRunner()
    cwd = os.getcwd()
    try:
        os.chdir(repo)
        return runner.invoke(compat_main, args, catch_exceptions=False)
    finally:
        os.chdir(cwd)


@pytest.fixture
def breaking_repo(git_repo: Path) -> Path:
    """A repo whose HEAD~1..HEAD range contains a real field removal."""
    _commit(git_repo, "acme/user.proto", _USER_V1, msg="v1")
    _commit(git_repo, "acme/user.proto", _USER_V2_DROP, msg="v2")
    return git_repo


# ---------------------------------------------------------------------------
# .proto fixtures for the rule-pack pins (compat) and the diff pins
# ---------------------------------------------------------------------------

_THING_OLD = (
    'syntax = "proto3";\n'
    "package acme;\n"
    "message Thing { string name = 1; int32 count = 2; }\n"
)
_THING_NEW = (
    'syntax = "proto3";\n'
    "package acme;\n"
    "message Thing { string name = 1; }\n"  # count removed — a real break
)


@pytest.fixture
def breaking_protos(tmp_path: Path) -> tuple[Path, Path]:
    """OLD/NEW .proto pair whose only difference is a removed field."""
    old = tmp_path / "old.proto"
    old.write_text(_THING_OLD)
    new = tmp_path / "new.proto"
    new.write_text(_THING_NEW)
    return old, new


_ORDER_PROTO = """
syntax = "proto3";
package acme;
message Inner { string label = 1; }
message Mid { Inner inner = 1; }
message Item { string id = 1; string v = 2; }
message Order {
  string trailing = 1;
  repeated Item items = 2;
  Mid mid = 3;
}
"""


@pytest.fixture
def order_proto(tmp_path: Path) -> Path:
    p = tmp_path / "order.proto"
    p.write_text(_ORDER_PROTO)
    return p


@pytest.fixture
def flat_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Two acme.Order text-format payloads differing at the top level."""
    left = tmp_path / "left.txt"
    left.write_text('trailing: "L"\nitems { id: "a" v: "1" }\n')
    right = tmp_path / "right.txt"
    right.write_text('trailing: "R"\nitems { id: "a" v: "2" }\n')
    return left, right


@pytest.fixture
def nested_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Two acme.Order payloads differing ONLY below the top level."""
    left = tmp_path / "nested_left.txt"
    left.write_text('mid { inner { label: "L" } }\n')
    right = tmp_path / "nested_right.txt"
    right.write_text('mid { inner { label: "R" } }\n')
    return left, right


def _diff(args: list[str]):
    return CliRunner().invoke(diff_main, args, catch_exceptions=False)


# ---------------------------------------------------------------------------
# U15-1 — history / bisect report a misspelled --proto-file as clean
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subcommand,extra",
    [
        ("history", ["--range", "HEAD~1..HEAD"]),
        ("bisect", ["--old", "HEAD~1", "--new", "HEAD"]),
    ],
)
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U15-1: history/bisect never pre-flight --proto-file, so a path "
        "that does not exist at NEW enumerates zero commits and exits 0 "
        "with '# <range>: no commits touch <path>', hiding a real break "
        "inside the range. _verify_proto_file_at_ref (schema/cli.py) "
        "exists but is called only from the check/ci path."
    ),
)
def test_u15_1_history_bisect_typoed_proto_file_is_not_clean(
    breaking_repo: Path, subcommand: str, extra: list[str],
) -> None:
    """A ``--proto-file`` that does not resolve must not read as compatible.

    Mechanism: ``history`` (schema/cli.py) and ``bisect`` ask
    ``commits_affecting_dep_tree`` which commits touched the path,
    get an empty list for a path that exists nowhere, and take the
    ``if not commits:`` early return — rendering "no commits touch"
    and ``sys.exit(0)``. No code between the flag and that return
    ever asks whether the path resolves at the NEW endpoint.

    Observed on 0.15.1 (both subcommands): exit 0, stdout
    ``# HEAD~1..HEAD: no commits touch acme/typo.proto``, stderr
    empty — over a range whose real ``acme/user.proto`` reports
    ``field_removed`` and exits 1 (see the control test below).
    ``check --since`` on the identical typo exits 2 with
    ``Error: --proto-file 'acme/typo.proto' not found at ref 'HEAD'
    ...``, so the fix and its wording already exist one call site
    away. No typo is even required: a proto renamed in-repo while a
    checked-in CI yaml still names the old path fails clean forever.

    Not pinned here: on an *empty* range the same two subcommands
    also skip ``--type`` and ``--compat-rule-pack`` validation (see
    the module docstring).
    """
    result = _invoke_in_repo(breaking_repo, [
        subcommand, *extra,
        "--proto-file", "acme/typo.proto",
        "--type", "acme.User",
    ])
    assert result.exit_code == 2, (
        f"{subcommand}: an unresolvable --proto-file must be a tooling "
        f"error (exit 2), got exit {result.exit_code} with "
        f"stdout={result.stdout!r}"
    )
    assert "no commits touch" not in result.stdout, (
        f"{subcommand}: reported a clean walk for a path that does not "
        f"exist at HEAD: {result.stdout!r}"
    )


# ---------------------------------------------------------------------------
# U15-2 — a rule pack can exit the process, or crash it, past the guards
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U15-2: _load_rule_packs wraps importlib.import_module in "
        "`except Exception`, but SystemExit derives from BaseException, "
        "so a rule pack whose module body calls sys.exit(0) passes "
        "straight through Click and becomes the process exit code — "
        "exit 0 with empty stdout and stderr on a genuinely breaking "
        "schema."
    ),
)
def test_u15_2_rule_pack_calling_sys_exit_does_not_forge_exit_0(
    breaking_protos: tuple[Path, Path], tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rule pack that exits during import must not decide the verdict.

    Mechanism: ``_load_rule_packs`` (schema/cli.py) catches
    ``Exception`` around ``importlib.import_module``. ``SystemExit``
    is not an ``Exception``, so it unwinds through Click's
    ``standalone_mode`` — which only traps ``ClickException`` /
    ``Abort`` — and terminates the process with the pack's own code.

    Observed on 0.15.1: ``check`` over a pair whose only change is a
    removed field (control: exit 1, INCOMPATIBLE) exits **0** with
    completely empty stdout and stderr once the pack is loaded. The
    break is never reported and never rendered.

    This is not an adversarial-only shape: an ordinary pack that
    imports a shared org helper which early-outs with ``sys.exit(0)``
    when a feature flag is off produces exactly this — an
    environment-conditional silent gate, the same class 0.15.1 shipped
    a patch release to close for ``--ignore``.
    """
    old, new = breaking_protos
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    pack_name = "u15_exit_rule_pack"
    (pack_dir / f"{pack_name}.py").write_text(
        "import sys\n"
        "sys.exit(0)\n"
        "RULES = []\n"
    )
    monkeypatch.syspath_prepend(str(pack_dir))
    try:
        result = CliRunner().invoke(compat_main, [
            "check", "--proto", str(old), str(new), "--type", "acme.Thing",
            "--compat-rule-pack", pack_name,
        ], catch_exceptions=False)
        assert result.exit_code == 2, (
            "a rule pack that calls sys.exit() during import is a broken "
            "pack (exit 2), not a compatible verdict; got exit "
            f"{result.exit_code} with stdout={result.stdout!r} "
            f"stderr={result.stderr!r}"
        )
    finally:
        sys.modules.pop(pack_name, None)


@pytest.mark.xfail(
    strict=True,
    raises=RuntimeError,
    reason=(
        "U15-2: _load_rule_packs guards checker.load_rule_pack with "
        "`except (AttributeError, TypeError)`, so any other exception "
        "raised while RULES is iterated (iter_rule_pack's `for entry in "
        "rules`) escapes as a traceback and exits 1 — the code reserved "
        "for INCOMPATIBLE — turning a broken pack into a schema break."
    ),
)
def test_u15_2_rule_pack_iteration_failure_is_not_reported_as_incompatible(
    breaking_protos: tuple[Path, Path],
) -> None:
    """A pack that raises while its RULES are read must exit 2, not 1.

    Mechanism: ``iter_rule_pack`` (schema/plugins.py) does ``for entry
    in rules``. Any exception from that iteration that is neither
    ``AttributeError`` nor ``TypeError`` — a lazily-built ``RULES``
    generator that raises ``ValueError("config missing")`` is the
    non-adversarial form — is not caught by the ``except
    (AttributeError, TypeError)`` in ``_load_rule_packs`` and unwinds
    out of Click.

    Observed on 0.15.1: exit 1 with a raw traceback ending
    ``RuntimeError: boom from __iter__`` and empty stdout. A pipeline
    reading the documented contract (0/1/2) sees "incompatible" for a
    run in which no comparison ever happened.
    """
    old, new = breaking_protos
    pack_name = "u15_bad_rules_pack"

    class _BadRules:
        def __iter__(self):
            raise RuntimeError("boom from __iter__")

    with _temp_rule_pack(pack_name, _BadRules()):
        result = CliRunner().invoke(compat_main, [
            "check", "--proto", str(old), str(new), "--type", "acme.Thing",
            "--compat-rule-pack", pack_name,
        ], catch_exceptions=False)
        assert result.exit_code == 2, (
            "a rule pack that raises while its RULES are iterated is a "
            "tooling error (exit 2), not an incompatibility verdict "
            f"(exit 1); got exit {result.exit_code}, "
            f"exception={result.exception!r}"
        )


# ---------------------------------------------------------------------------
# U15-3 — rule-pack stdout corrupts --format json and defeats --quiet
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason=(
        "U15-3: rule-pack code writes to the same stdout the CLI uses "
        "for its machine payload, so a print() inside a rule function "
        "prefixes the --format json document and json.loads fails on "
        "the CLI's own output."
    ),
)
def test_u15_3_rule_pack_print_does_not_corrupt_json_stdout(
    breaking_protos: tuple[Path, Path],
) -> None:
    """``--format json`` stdout must be parseable JSON, pack or no pack.

    Mechanism: plugin rule functions are called in-process while the
    CLI is building the report, and nothing redirects or captures
    their stdout. ``click.echo`` then appends the JSON document to
    whatever the pack already wrote.

    Observed on 0.15.1: stdout is
    ``noisy_rule: examining field\\n{\\n  "compatible": false, ...``
    and ``json.loads`` fails with ``Expecting value: line 1 column 1``.
    The identical invocation without ``--compat-rule-pack`` produces
    valid JSON (see the control test), so the corruption is
    attributable to the pack and to nothing else. A CI job that pipes
    ``--format json`` into a parser gets a hard parse error rather
    than the verdict it asked for.
    """
    old, new = breaking_protos
    pack_name = "u15_print_rule_pack"

    with _temp_rule_pack(pack_name, [("noisy", _noisy_rule)]):
        result = CliRunner().invoke(compat_main, [
            "check", "--proto", str(old), str(new), "--type", "acme.Thing",
            "--format", "json",
            "--compat-rule-pack", pack_name,
        ], catch_exceptions=False)
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"--format json stdout is not valid JSON ({exc}); "
                f"stdout={result.stdout[:200]!r}"
            )
        assert payload["compatible"] is False


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U15-3: --quiet documents 'Suppress output; return exit code "
        "only.' but only gates the CLI's own click.echo calls; a "
        "rule-pack print() still reaches stdout."
    ),
)
def test_u15_3_rule_pack_print_does_not_leak_under_quiet(
    breaking_protos: tuple[Path, Path],
) -> None:
    """``--quiet`` must mean exit-code-only, including for plugin output.

    Mechanism: ``--quiet`` is implemented as ``if not quiet:`` guards
    around the CLI's own rendering. Plugin code runs before that
    branch and writes to stdout directly, so the flag cannot suppress
    it.

    Observed on 0.15.1: exit 1, stderr empty, but stdout carries
    ``noisy_rule: examining field`` — against the flag's own help
    text in ``schema/cli.py`` ("Suppress output; return exit code
    only."; ``history``'s wording adds "Diagnostics still stream to
    stderr", making stdout's emptiness the explicit promise).
    """
    old, new = breaking_protos
    pack_name = "u15_print_rule_pack_quiet"

    with _temp_rule_pack(pack_name, [("noisy", _noisy_rule)]):
        result = CliRunner().invoke(compat_main, [
            "check", "--proto", str(old), str(new), "--type", "acme.Thing",
            "--quiet",
            "--compat-rule-pack", pack_name,
        ], catch_exceptions=False)
        assert result.stdout == "", (
            "--quiet promises exit-code-only, but stdout carried "
            f"{result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# U15-4 — a missing git binary is reported as INCOMPATIBLE
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "args",
    [
        pytest.param(
            ["check", "--since", "HEAD~1",
             "--proto-file", "acme/user.proto", "--type", "acme.User"],
            id="check-since",
        ),
        pytest.param(
            ["ci", "--base", "HEAD~1",
             "--proto-file", "acme/user.proto", "--type", "acme.User"],
            id="ci-base",
        ),
        pytest.param(
            ["bisect", "--old", "HEAD~1", "--new", "HEAD",
             "--proto-file", "acme/user.proto", "--type", "acme.User"],
            id="bisect",
        ),
    ],
)
@pytest.mark.xfail(
    strict=True,
    raises=RuntimeError,
    reason=(
        "U15-4: _run_git translates a missing binary into "
        "RuntimeError('git not found on PATH; ...'), but only "
        "_resolve_range_endpoints (history-only) catches RuntimeError. "
        "On check --since / ci --base / bisect it escapes as a "
        "traceback and exits 1 — the code reserved for INCOMPATIBLE — "
        "so a missing tool is reported as a schema break."
    ),
)
def test_u15_4_missing_git_is_a_tooling_error_not_a_break(
    breaking_repo: Path, monkeypatch: pytest.MonkeyPatch, args: list[str],
) -> None:
    """git absent from PATH must exit 2 on every git-aware subcommand.

    Mechanism: ``schema/git.py::_run_git`` converts
    ``FileNotFoundError`` from ``subprocess.run(["git", ...])`` into a
    ``RuntimeError``. The ``@_git_error_boundary`` decorator on the
    subcommands catches ``subprocess.CalledProcessError`` only, and
    the ``error_exit``-on-``RuntimeError`` handler lives inside
    ``_resolve_range_endpoints``, which only ``history`` calls.

    Observed on 0.15.1: ``check --since``, ``ci --base`` and
    ``bisect`` each exit 1 with an escaping ``RuntimeError`` and empty
    stdout, while ``history`` exits 2 with the single clean line
    ``Error: git not found on PATH; ...`` (control test below). The
    project states the harm itself in ``schema/git.py``'s
    ``_git_failure_exit`` docstring: "an escaping traceback exits 1,
    which a pipeline reads as a compatibility BREAK that never
    happened".
    """
    empty_bin = breaking_repo / "empty_bin"
    empty_bin.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(empty_bin))
    result = _invoke_in_repo(breaking_repo, args)
    assert result.exit_code == 2, (
        "a missing git binary must be a tooling error (exit 2), not the "
        f"INCOMPATIBLE code; got exit {result.exit_code}, "
        f"exception={result.exception!r}"
    )


# ---------------------------------------------------------------------------
# U15-5 — history charges a commit with its walk-predecessor's changes
# ---------------------------------------------------------------------------


@pytest.fixture
def merged_repo(git_repo: Path) -> dict[str, str]:
    """A genuinely merged, purely additive history.

    ``O`` declares ``Thing.name``; branch ``A`` adds ``a_field`` and
    branch ``B`` — branched from ``O``, not from ``A`` — adds
    ``b_field``. Both branches are merged into main. Every merge
    auto-resolves (the two edits sit eight filler lines apart), so no
    conflict resolution and no "evil merge" is involved. No commit
    anywhere in ``O..HEAD`` removes a field.
    """
    header = (
        'syntax = "proto3";\n'
        "package acme;\n"
        "message Thing {\n"
        "  string name = 1;\n"
    )
    filler = "".join(f"  // filler {i}\n" for i in range(8))

    def body(a: str = "", b: str = "") -> str:
        return (
            header
            + (f"  {a}\n" if a else "")
            + filler
            + (f"  {b}\n" if b else "")
            + "}\n"
        )

    o_sha = _commit(git_repo, "acme/thing.proto", body(), msg="base")
    _git("checkout", "-q", "-b", "branch-a", cwd=git_repo)
    a_sha = _commit(
        git_repo, "acme/thing.proto",
        body(a="string a_field = 2;"), msg="A: add a_field",
    )
    _git("checkout", "-q", o_sha, cwd=git_repo)
    _git("checkout", "-q", "-b", "branch-b", cwd=git_repo)
    b_sha = _commit(
        git_repo, "acme/thing.proto",
        body(b="string b_field = 3;"), msg="B: add b_field",
    )
    _git("checkout", "-q", "main", cwd=git_repo)
    _git("merge", "-q", "--no-ff", "-m", "merge A", "branch-a", cwd=git_repo)
    _git("merge", "-q", "--no-ff", "-m", "merge B", "branch-b", cwd=git_repo)
    return {"repo": str(git_repo), "O": o_sha, "A": a_sha, "B": b_sha}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U15-5: history pairs commits by chaining the flat "
        "`git log --reverse` enumeration (anchor = commits[0]^, then "
        "prev = sha), so HistoryEntry.parent_sha is 'the previously "
        "walked commit', which on a merged history is not a parent. "
        "Branch B is compared against branch A and charged with "
        "field_removed:a_field — a removal no commit in the range "
        "performed."
    ),
)
def test_u15_5_history_does_not_attribute_a_siblings_change_to_a_commit(
    merged_repo: dict[str, str],
) -> None:
    """Every entry's recorded parent must be a real parent of its commit.

    Mechanism: ``commits_in_range`` is ``git log --reverse
    --format=%H <range>``, i.e. commit-date order over the DAG, not a
    parent walk. ``history`` then builds pairs as
    ``anchor = f"{commits[0]}^"; prev = anchor; for sha in commits:
    pairs.append((prev, sha)); prev = sha`` and records
    ``HistoryEntry(commit_sha=new_ref, parent_sha=old_ref)``.

    Observed on 0.15.1 over the purely additive fixture below (``git
    log --reverse`` yields A, B, merge):

    * ``new=B old=A`` → ``['field_removed:a_field',
      'field_added:b_field']``.

    B branched from O and never touched ``a_field``; its real change
    against its real parent is a single ``field_added:b_field``. The
    range as a whole only ever adds fields, yet ``history`` prints
    ``<B> BROKEN`` and exits 1 — a break that exists nowhere in the
    repository. ``bisect`` shares the enumeration, so the same
    chaining can name the wrong "first breaking commit".
    """
    repo = Path(merged_repo["repo"])
    result = _invoke_in_repo(repo, [
        "history", "--range", f"{merged_repo['O']}..HEAD",
        "--proto-file", "acme/thing.proto", "--type", "acme.Thing",
        "--level", "strict", "--format", "json",
    ])
    payload = json.loads(result.stdout)
    assert payload["entries"], "fixture produced no history entries"

    for entry in payload["entries"]:
        child = entry["new"]
        recorded = entry["old"]
        real_parents = _git(
            "rev-list", "--parents", "-n", "1", child, cwd=repo,
        ).split()[1:]
        resolved = _git("rev-parse", f"{recorded}^{{commit}}", cwd=repo)
        assert resolved in real_parents, (
            f"commit {child[:12]} was compared against {resolved[:12]}, "
            f"which is not one of its parents {[p[:12] for p in real_parents]}"
        )

    removals = [
        (entry["new"][:12], f["path"])
        for entry in payload["entries"]
        for f in entry["findings"]
        if f["rule_id"] == "field_removed"
    ]
    assert not removals, (
        "no commit in this purely additive history removes a field, but "
        f"history charged: {removals}"
    )


# ---------------------------------------------------------------------------
# U15-6 — diff's differ configuration raises outside the guarded block
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra,expected_error",
    [
        pytest.param(
            ["--ignore", "bad.trailing."],
            "Trailing '.'",
            id="trailing-dot-ignore",
        ),
        pytest.param(
            ["--ignore", "items", "--treat-as-map", "items", "id"],
            "already ignored",
            id="ignore-plus-treat-as-map",
        ),
    ],
)
@pytest.mark.xfail(
    strict=True,
    raises=ValueError,
    reason=(
        "U15-6: message/cli.py configures the differ "
        "(differ.ignore_fields / differ.treat_as_map) BEFORE the "
        "`try: differ.compare(...) except ValueError: _error(...)` "
        "block, so a malformed --ignore path or an ignore/treat-as-map "
        "conflict raises ValueError past every handler — traceback and "
        "exit 1, the code reserved for 'messages differ'."
    ),
)
def test_u15_6_diff_flag_validation_errors_exit_2_not_1(
    order_proto: Path, flat_pair: tuple[Path, Path],
    extra: list[str], expected_error: str,
) -> None:
    """A bad ``--ignore`` is a usage error, not a "messages differ" verdict.

    Mechanism: in ``message/cli.py`` the ``if ignore:
    differ.ignore_fields(*ignore)`` and ``for field, key in
    treat_as_map: differ.treat_as_map(...)`` statements sit above the
    ``try`` that guards ``differ.compare``. ``FieldPath.parse``
    (message/model.py) raises ``ValueError("Trailing '.' in ...")``
    from there, outside any handler.

    Observed on 0.15.1: exit 1, empty stdout, raw traceback on stderr.
    The sibling errors that *are* raised inside the guarded block —
    ``--treat-as-map items nosuchkey`` — exit 2 with a clean
    ``Error: key field 'nosuchkey' not found in descriptor for
    acme.Item``, as does ``--format nope`` (control test below). The
    CLI's own ``--help`` and module docstring state ``0 = equal,
    1 = different, 2 = error``, and exit 1 here claims a comparison
    verdict the tool never computed.
    """
    left, right = flat_pair
    result = _diff([
        "--proto", str(order_proto), "--message-type", "acme.Order",
        "--text-format", *extra, str(left), str(right),
    ])
    assert result.exit_code == 2, (
        "invalid differ configuration must exit 2 (error), not 1 "
        f"(different); got exit {result.exit_code}, "
        f"exception={result.exception!r}"
    )
    assert "Error:" in result.stderr, (
        "expected a clean one-line usage error on stderr, got "
        f"{result.stderr[:200]!r}"
    )
    assert expected_error in result.stderr


# ---------------------------------------------------------------------------
# U15-7 — a truncated comparison is reported as equality
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("depth", ["0", "1"])
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "U15-7: with --max-depth truncating before the differing "
        "subtree, DiffResult.has_changes() is False and the truncation "
        "is only a warning-level diagnostic, so message/cli.py's "
        "`not result.has_changes() and not result.errors and not "
        "verbose` short-circuit prints 'Messages are equal.' and exits "
        "0 on genuinely differing payloads."
    ),
)
def test_u15_7_truncated_comparison_is_not_reported_as_equal(
    order_proto: Path, nested_pair: tuple[Path, Path], depth: str,
) -> None:
    """``--max-depth`` must not turn "did not look" into "are equal".

    Mechanism: the truncation is recorded as a ``warning``
    diagnostic, and the human short-circuit in ``message/cli.py``
    only refuses to print the green stub for ``result.errors``.
    ``_diff_exit_code`` then sees no differences and returns 0.

    Observed on 0.15.1 for payloads differing only at
    ``mid.inner.label``: ``--max-depth 0`` and ``--max-depth 1`` both
    print ``Messages are equal.`` and exit 0; ``--quiet`` exits 0
    silently; ``--format json`` emits ``"equal": true`` with the
    truncation demoted to a warning; ``--verbose`` still leads with
    ``Messages are equal.`` before the warning. Without the flag the
    same pair reports ``~ mid.inner.label: 'L' -> 'R'`` and exits 1
    (control test below). The 0.16.0 plan (U7/V24) specifies the fix:
    "a max_depth-truncated comparison of genuinely-differing nested
    messages prints an INCOMPLETE verdict and emits ``equal: false``".

    The pin deliberately does not fix an exact non-zero code: U8
    ("no CLI exits 0 on a run that did not complete") leaves the
    choice between 1 (different) and 2 (could not run) to the fix.
    """
    left, right = nested_pair
    result = _diff([
        "--proto", str(order_proto), "--message-type", "acme.Order",
        "--text-format", "--max-depth", depth, str(left), str(right),
    ])
    assert "Messages are equal." not in result.stdout, (
        f"--max-depth {depth} truncated the comparison above the only "
        f"difference yet claimed equality: {result.stdout!r}"
    )
    assert result.exit_code != 0, (
        f"--max-depth {depth} exited 0 on genuinely differing messages"
    )


# ---------------------------------------------------------------------------
# Controls — these PASS today. They guard the pins above against fixture
# rot: without them an xfail could be "passing" for a reason unrelated
# to the finding it claims to pin.
# ---------------------------------------------------------------------------


class TestU15Controls:
    def test_history_on_the_real_path_reports_the_break(
        self, breaking_repo: Path,
    ) -> None:
        """U15-1 control: the pinned range genuinely contains a break."""
        result = _invoke_in_repo(breaking_repo, [
            "history", "--range", "HEAD~1..HEAD",
            "--proto-file", "acme/user.proto", "--type", "acme.User",
        ])
        assert result.exit_code == 1
        assert "field_removed" in result.stdout

    def test_check_without_a_rule_pack_is_incompatible_and_valid_json(
        self, breaking_protos: tuple[Path, Path],
    ) -> None:
        """U15-2 / U15-3 control: the pack is the only variable."""
        old, new = breaking_protos
        human = CliRunner().invoke(compat_main, [
            "check", "--proto", str(old), str(new), "--type", "acme.Thing",
        ], catch_exceptions=False)
        assert human.exit_code == 1
        assert "INCOMPATIBLE" in human.stdout

        structured = CliRunner().invoke(compat_main, [
            "check", "--proto", str(old), str(new), "--type", "acme.Thing",
            "--format", "json",
        ], catch_exceptions=False)
        assert json.loads(structured.stdout)["compatible"] is False

        quiet = CliRunner().invoke(compat_main, [
            "check", "--proto", str(old), str(new), "--type", "acme.Thing",
            "--quiet",
        ], catch_exceptions=False)
        assert quiet.exit_code == 1
        assert quiet.stdout == ""

    def test_history_alone_handles_a_missing_git_binary(
        self, breaking_repo: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """U15-4 control: the correct shape already exists in-tree."""
        empty_bin = breaking_repo / "empty_bin_control"
        empty_bin.mkdir(exist_ok=True)
        monkeypatch.setenv("PATH", str(empty_bin))
        result = _invoke_in_repo(breaking_repo, [
            "history", "--range", "HEAD~1..HEAD",
            "--proto-file", "acme/user.proto", "--type", "acme.User",
        ])
        assert result.exit_code == 2
        assert result.stderr.strip() == (
            "Error: git not found on PATH; install git or run from a "
            "git-aware environment"
        )

    def test_diff_usage_errors_reached_through_the_guard_exit_2(
        self, order_proto: Path, flat_pair: tuple[Path, Path],
    ) -> None:
        """U15-6 control: diff's clean usage-error shape."""
        left, right = flat_pair
        bad_format = _diff([
            "--proto", str(order_proto), "--message-type", "acme.Order",
            "--text-format", "--format", "nope", str(left), str(right),
        ])
        assert bad_format.exit_code == 2
        assert "unknown formatter 'nope'" in bad_format.stderr

        bad_key = _diff([
            "--proto", str(order_proto), "--message-type", "acme.Order",
            "--text-format", "--treat-as-map", "items", "nosuchkey",
            str(left), str(right),
        ])
        assert bad_key.exit_code == 2
        assert "not found in descriptor" in bad_key.stderr

    def test_diff_without_max_depth_reports_the_nested_difference(
        self, order_proto: Path, nested_pair: tuple[Path, Path],
    ) -> None:
        """U15-7 control: the pinned payloads genuinely differ."""
        left, right = nested_pair
        result = _diff([
            "--proto", str(order_proto), "--message-type", "acme.Order",
            "--text-format", str(left), str(right),
        ])
        assert result.exit_code == 1
        assert "mid.inner.label" in result.stdout
