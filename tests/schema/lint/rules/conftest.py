"""Shared helpers for ``tests/schema/lint/rules/``.

Plain functions consumed via relative import from each consumer
test file (`from .conftest import _compile, _run_single`). The
helpers were extracted at D6a U5 once the third pack test file
(`test_imports.py`) was about to land, crossing the 3+ duplicate
threshold tracked in
``docs/solutions/best-practices/
conftest-plain-function-relative-import-2026-05-12.md``.

Per the same learning, these are deliberately **not**
``@pytest.fixture``-decorated. They are plain functions —
auto-discovery doesn't apply to non-fixture conftest contents, so
each consumer imports them explicitly. The relative-import form
keeps the test directory self-contained: if the rules-test
subtree moves, no absolute import path needs updating.

The ``_run_single`` helper now accepts the pack module as an
explicit parameter (it was hardcoded to the per-test pack in the
pre-extraction copies). This closes the D6a U3/U4 ce:review finding
that the helper hardcoded ``name="default"`` for every isolation
profile by making the pack-scope explicit at call time.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Any

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import LintProfile, LintSeverity


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
    pack: ModuleType,
) -> Any:
    """Run the engine with a profile containing only ``rule_id``.

    Args:
        tmp_path: pytest tmp_path fixture.
        sources: filename → proto source content mapping.
        rule_id: the single rule to enable in the run profile.
        pack: the rule pack module that registers ``rule_id``.
            Passed explicitly (rather than inferred from rule_id)
            so the caller sees which pack drives the test and the
            helper does not need a registry lookup of its own.

    Returns the ``LintReport``. The profile uses ``INFO``
    min-severity so the test exercises emission rather than the
    severity-gate logic (which has its own dedicated tests). The
    profile name is the constant ``"_test_isolation"`` so the name
    never silently aligns with a real pack's declared profile —
    rules opt in via ``rule_ids``, not via the profile name, so
    the explicit synthetic label removes one source of test-vs-
    production drift.
    """
    result = _compile(tmp_path, sources)
    engine = LintEngine()
    engine.load_rule_pack(pack)
    profile = LintProfile(
        name="_test_isolation",
        rule_ids=frozenset({rule_id}),
        min_severity=LintSeverity.INFO,
    )
    return engine.run(result, profile=profile)
