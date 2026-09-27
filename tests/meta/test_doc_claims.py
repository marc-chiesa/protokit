"""Prose that makes a checkable claim about the code is checked against it (U16, audit D6).

The 2026-08-30 audit found six comments and docstrings that stated something
false with confidence. One did real harm: ``SchemaChecker._compare_map_value``
said a map's ``key`` "is always a scalar and not user-visible", which told a
reader that never comparing the key was correct, and that is how a map
key-type change came to pass at every compatibility level (V20, V27).

Each class below takes one claim that 0.16.0 rewrote and checks it from both
sides. A behavioural half measures the running library, so a behaviour change
fails even while the prose is untouched. A prose half asserts that the source
still states what the behavioural half measured, and that the original wrong
claim has not come back, so reverting the prose fails even while the behaviour
is untouched.

The prose half is a presence check, not a wording contract: each phrase is the
shortest one that states the fact, and a rewrite that keeps the fact only needs
the phrase updated here. Prose is compared with whitespace collapsed and ``#``
markers stripped, so a phrase may cross a line break and rewrapping a paragraph
never breaks a check.

The other two D6 claims are guarded elsewhere, both closed in 0.16.0 U17a:

* ``formatters/__init__.py``'s cycle-safety comment names the real invariant,
  which ``test_formatters_package_init_shape_is_present_and_not_a_cycle`` in
  ``tests/meta/test_import_layers.py`` enforces for every submodule.
* The two ``_protokit_version`` wrappers whose docstrings claimed a collapse
  that had not happened are deleted, and
  ``tests/meta/test_version_lookup_single_owner.py`` keeps the lookup at one
  owner.

A release adds the claims of the modules it touched; it does not wait for the
others.

KTD3 proof: a doc-shaped fix has no guarded branch to mutate. Each prose
check was proven instead by using ``scripts/mutation_check.py`` to rewrite the
corrected text back to the original wrong claim and watching the check fail.
Each behavioural half was proven by breaking the behaviour it measures: the
``DecodeError`` conversion, the ``TYPE_CHECKING`` gate, an importer of
``_cli_utils`` removed or added.
"""

from __future__ import annotations

import builtins
import json
import os
import re
import subprocess
import sys
import typing
from pathlib import Path

import pytest
from google.protobuf import descriptor_pb2

import protokit._pools as pools
import protokit.schema.lint._cli_utils as cli_utils
from protokit._pools import DescriptorPoolError, load_pool_from_path
from protokit.schema import CompatibilityLevel, check_compatibility
from protokit.schema.checker import SchemaChecker
from protokit.schema.lint.model import LintReport
from tests.meta.test_import_layers import _REPO_ROOT, _SRC_ROOT, PACKAGE, build_import_graph
from tests.proto_builder import ProtoBuilder

T = descriptor_pb2.FieldDescriptorProto


def _prose(text: str | None) -> str:
    """``text`` with every run of whitespace collapsed to one space."""
    assert text, "expected prose to check, found none"
    return " ".join(text.split())


def _missing(phrase: str, where: str) -> str:
    return (
        f"{where} no longer says {phrase!r}. If the prose was rewritten on purpose "
        "and still states the same fact, update the phrase in this test. If the "
        "fact itself changed, the behavioural test in the same class fails too and "
        "says what changed."
    )


def _returned(phrase: str, where: str, why: str) -> str:
    return f"{where} says {phrase!r} again, the claim this test exists to keep out: {why}"


def _loaded_by_fresh_import(importing: str, *modules: str) -> dict[str, bool]:
    """For each of ``modules``, whether ``import <importing>`` puts it in ``sys.modules``.

    Run in a subprocess because the test process has already imported most
    of ``protokit``, so ``sys.modules`` here says nothing about what one
    import pulls in. The environment matches ``import_in_fresh_interpreter``'s
    sweep of the real tree, so ``protokit`` resolves from ``src`` rather than
    from whatever is installed.
    """
    code = (
        f"import json, sys\nimport {importing}\n"
        f"print(json.dumps({{m: m in sys.modules for m in {list(modules)!r}}}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_SRC_ROOT), "PYTHONSAFEPATH": "1"},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    loaded: dict[str, bool] = json.loads(result.stdout)
    return loaded


# ---------------------------------------------------------------------------
# D6 claim 1: schema/lint/model.py, the TYPE_CHECKING import's comment
# ---------------------------------------------------------------------------

_MODEL_PATH = _SRC_ROOT / PACKAGE / "schema" / "lint" / "model.py"
_GATED_IMPORT = "from protokit.schema.compile import LintCompileDiagnostic"
_WHERE_MODEL = "The comment on schema/lint/model.py's TYPE_CHECKING import"


def _comment_above(path: Path, statement: str) -> str:
    """The contiguous ``#`` comment block directly above ``statement``."""
    lines = path.read_text(encoding="utf-8").splitlines()
    index = next(i for i, line in enumerate(lines) if line.strip() == statement)
    comment: list[str] = []
    for line in reversed(lines[:index]):
        stripped = line.strip()
        if not stripped.startswith("#"):
            break
        comment.append(stripped.lstrip("#"))
    return "\n".join(reversed(comment))


class TestLintReportTypeHintsComment:
    """The gated import helps type checkers, not ``typing.get_type_hints``.

    The comment used to say that without the import ``get_type_hints`` could
    not resolve ``LintReport``, implying that with it, it could. An import
    under ``if TYPE_CHECKING:`` never executes, so it cannot bind the name at
    runtime, and ``get_type_hints`` raises either way.
    """

    def test_get_type_hints_raises_and_localns_resolves(self) -> None:
        # Importing the defining module first does not help: the forward
        # reference is evaluated in model.py's globals, which never bind it.
        from protokit.schema.compile import LintCompileDiagnostic

        with pytest.raises(NameError, match="LintCompileDiagnostic"):
            typing.get_type_hints(LintReport)
        hints = typing.get_type_hints(
            LintReport, localns={"LintCompileDiagnostic": LintCompileDiagnostic}
        )
        assert LintCompileDiagnostic in typing.get_args(hints["diagnostics"])

    @pytest.mark.parametrize(
        "phrase",
        ["``typing.get_type_hints(LintReport)`` raises ``NameError``", "``localns``"],
    )
    def test_comment_states_the_limitation(self, phrase: str) -> None:
        comment = _prose(_comment_above(_MODEL_PATH, _GATED_IMPORT))
        assert phrase in comment, _missing(phrase, _WHERE_MODEL)

    def test_comment_does_not_credit_the_import(self) -> None:
        comment = _prose(_comment_above(_MODEL_PATH, _GATED_IMPORT))
        phrase = "Without this import"
        assert phrase not in comment, _returned(
            phrase, _WHERE_MODEL, "an import that never runs cannot help get_type_hints"
        )


# ---------------------------------------------------------------------------
# D6 claim 2: schema/checker.py, SchemaChecker._compare_map_value
# ---------------------------------------------------------------------------


_WHERE_MAP = "SchemaChecker._compare_map_value's docstring"


def _map_pool(key_type: int) -> ProtoBuilder:
    builder = ProtoBuilder()
    builder.map_message("t.M", {}, {"items": (key_type, T.TYPE_STRING, 1)})
    return builder


class TestMapKeyDocstring:
    """A map's key type is user-declared, and the checker never compares it.

    The second half is the open gap V20, scheduled for a later release. When
    that fix lands, ``test_key_type_change_passes_at_every_level`` fails; that
    is the signal to rewrite the docstring in the same change.
    """

    def test_key_type_is_declared_by_the_user(self) -> None:
        def key_type(builder: ProtoBuilder) -> int:
            items = builder.pool.FindMessageTypeByName("t.M").fields_by_name["items"]
            key: int = items.message_type.fields_by_name["key"].type
            return key

        assert key_type(_map_pool(T.TYPE_INT32)) == T.TYPE_INT32
        assert key_type(_map_pool(T.TYPE_STRING)) == T.TYPE_STRING

    def test_key_type_change_passes_at_every_level(self) -> None:
        old, new = _map_pool(T.TYPE_INT32).pool, _map_pool(T.TYPE_STRING).pool
        reported = {
            level.name: [
                f.rule_id
                for f in check_compatibility(old, "t.M", new, "t.M", level=level).findings
            ]
            for level in CompatibilityLevel
        }
        assert reported == {level.name: [] for level in CompatibilityLevel}, (
            f"a map key-type change is now reported ({reported}), so V20 is closed; "
            "SchemaChecker._compare_map_value's docstring still says the key is never "
            "compared, so rewrite it in the same change"
        )

    @pytest.mark.parametrize(
        "phrase",
        [
            "the user declares both types",
            "``key`` is never compared",
            "a key-type change passes at every level",
        ],
    )
    def test_docstring_states_the_gap(self, phrase: str) -> None:
        doc = _prose(SchemaChecker._compare_map_value.__doc__)
        assert phrase in doc, _missing(phrase, _WHERE_MAP)

    def test_docstring_does_not_call_the_key_invisible(self) -> None:
        doc = _prose(SchemaChecker._compare_map_value.__doc__)
        phrase = "not user-visible"
        assert phrase not in doc, _returned(
            phrase, _WHERE_MAP, "the user writes the key type, and it is wire-significant"
        )


# ---------------------------------------------------------------------------
# D6 claim 4: _pools.py, load_pool_from_path's exception contract
# ---------------------------------------------------------------------------


def _documented_exceptions() -> set[type[BaseException]]:
    """Exception classes ``load_pool_from_path``'s docstring names in double backticks."""
    names = re.findall(r"``(\w+)``", load_pool_from_path.__doc__ or "")
    found: set[type[BaseException]] = set()
    for name in names:
        candidate = getattr(pools, name, None) or getattr(builtins, name, None)
        if isinstance(candidate, type) and issubclass(candidate, BaseException):
            found.add(candidate)
    return found


def _unbuildable_set() -> bytes:
    """A well-formed ``FileDescriptorSet`` whose one file names an absent dependency."""
    fds = descriptor_pb2.FileDescriptorSet()
    fds.file.add(name="a.proto", dependency=["missing.proto"])
    return fds.SerializeToString()


class TestLoadPoolFromPathDocstring:
    """Every failure the docstring names is one the function raises, and vice versa.

    The docstring used to promise "a protobuf parse exception" for a malformed
    file. ``load_pool_from_bytes`` converts ``DecodeError`` to
    ``DescriptorPoolError``, so a caller catching the protobuf exception
    caught nothing.
    """

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(b"\xff\xff\xff", id="not-a-descriptor-set"),
            pytest.param(_unbuildable_set(), id="parses-but-cannot-build"),
        ],
    )
    def test_malformed_file_raises_a_documented_exception(
        self, tmp_path: Path, data: bytes
    ) -> None:
        path = tmp_path / "schema.descriptor_set"
        path.write_bytes(data)
        with pytest.raises(DescriptorPoolError) as excinfo:
            load_pool_from_path(path)
        documented = tuple(_documented_exceptions())
        assert isinstance(excinfo.value, documented), (
            f"load_pool_from_path raised {type(excinfo.value).__name__} for a malformed "
            f"file; its docstring names only {sorted(c.__name__ for c in documented)}"
        )

    def test_unreadable_path_raises_a_documented_exception(self, tmp_path: Path) -> None:
        with pytest.raises(OSError) as excinfo:
            load_pool_from_path(tmp_path / "absent.descriptor_set")
        assert isinstance(excinfo.value, tuple(_documented_exceptions()))

    def test_docstring_names_exactly_the_raised_exceptions(self) -> None:
        # The two cases above check that what is raised is documented; this
        # checks that nothing documented is stale, and fails on the original
        # docstring, which named no exception class at all.
        documented = _documented_exceptions()
        assert documented == {DescriptorPoolError, OSError}, (
            f"load_pool_from_path's docstring names {sorted(c.__name__ for c in documented)} "
            "as the exceptions it raises; it raises DescriptorPoolError for a malformed "
            "file and OSError for an unreadable path"
        )


# ---------------------------------------------------------------------------
# D6 claim 6: schema/lint/_cli_utils.py, when the module is loaded
# ---------------------------------------------------------------------------

_LINT = f"{PACKAGE}.schema.lint"
_CLI_UTILS = f"{_LINT}._cli_utils"
# The docstring's list of who imports the module at load: the CLI, which is
# where the name comes from, plus "the lint engine, the config and
# custom-rule loaders, and some built-in rules".
_DOCUMENTED_IMPORTERS = {
    f"{_LINT}.cli",
    f"{_LINT}.engine",
    f"{_LINT}._config",
    f"{_LINT}._custom_rules",
}
_DOCUMENTED_IMPORTER_PACKAGE = f"{_LINT}.rules"
_WHERE_CLI_UTILS = "schema/lint/_cli_utils.py's module docstring"


class TestLintCliUtilsDocstring:
    """Lint's ``_cli_utils`` is loaded by every lint run, not only by the CLI.

    The module docstring used to say it was loaded only when
    ``protokit.schema.lint.cli`` was. The engine imports it at module load,
    so the library path loads it without any CLI module.
    """

    def test_importers_are_the_documented_ones(self) -> None:
        graph = build_import_graph(_SRC_ROOT, PACKAGE)
        importers = {module for module, targets in graph.items() if _CLI_UTILS in targets}
        undocumented = {
            m
            for m in importers - _DOCUMENTED_IMPORTERS
            if not m.startswith(f"{_DOCUMENTED_IMPORTER_PACKAGE}.")
        }
        assert not undocumented, (
            f"{sorted(undocumented)} import {_CLI_UTILS} at module load, and its "
            "docstring's list of importers does not cover them"
        )
        missing = _DOCUMENTED_IMPORTERS - importers
        assert not missing, f"the docstring says {sorted(missing)} import it; they no longer do"
        assert any(m.startswith(f"{_DOCUMENTED_IMPORTER_PACKAGE}.") for m in importers), (
            "the docstring says some built-in rules import it; none does"
        )

    def test_engine_loads_it_without_the_cli(self) -> None:
        loaded = _loaded_by_fresh_import(f"{_LINT}.engine", _CLI_UTILS, f"{_LINT}.cli")
        assert loaded == {_CLI_UTILS: True, f"{_LINT}.cli": False}

    @pytest.mark.parametrize("importing", [f"{PACKAGE}.schema", _LINT])
    def test_cold_import_does_not_load_it(self, importing: str) -> None:
        assert _loaded_by_fresh_import(importing, _CLI_UTILS) == {_CLI_UTILS: False}

    @pytest.mark.parametrize(
        "phrase",
        [
            "the lint engine, the config and custom-rule loaders, and some built-in rules",
            "``import protokit.schema.lint.engine`` loads it without the CLI",
            "neither ``import protokit.schema`` nor ``import protokit.schema.lint`` loads it",
        ],
    )
    def test_docstring_states_the_load_path(self, phrase: str) -> None:
        assert phrase in _prose(cli_utils.__doc__), _missing(phrase, _WHERE_CLI_UTILS)

    def test_docstring_does_not_claim_cli_only(self) -> None:
        phrase = "loaded only when"
        assert phrase not in _prose(cli_utils.__doc__), _returned(
            phrase, _WHERE_CLI_UTILS, "the lint engine imports it at module load"
        )
