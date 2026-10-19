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

The next three classes are claims 0.16.0 itself wrote and its re-audit found
too wide: that every descriptor set loads the same way on both runtimes, that
a default-valued extension always equals an unset one, and that ``complete``
and SARIF's ``executionSuccessful`` say the analysis covered its input. Their
prose lives in ``README.md`` and ``CHANGELOG.md`` as well as in the source.

The Requirements class after them is a claim nobody rewrote. The README's
Requirements section had fallen to two of the five runtime dependencies and
had lost ``protobuf``'s upper bound; it is compared with ``pyproject.toml``,
the list pip acts on.

The classes at the end of the file are claims the second re-audit found too
wide, in the release text and one docstring: that pure-Python ``compat`` and
``forensics`` no longer crash on any schema, that ``FindFileByName`` forces
every check, that ``lint --proto`` lints every file it is given, that a rule
pack can no longer decide the exit code, three before-states wider than
0.15.1 measured, and that a rule pack's text can no longer forge a line. Each
narrowed claim names what is left open, and a behavioural half that measures
an open defect is named ``..._currently_...``: it fails when the defect is
fixed, which is the signal to drop that part of the prose. The last class
checks that the release has its own ``### Known issues`` section, between the
upgrade table and Security, naming the entries the release committed to.
CHANGELOG checks there are scoped to the release section; README checks to
the upgrade note they concern.

KTD3 proof: a doc-shaped fix has no guarded branch to mutate. Each prose
check was proven instead by using ``scripts/mutation_check.py`` to rewrite the
corrected text back to the original wrong claim and watching the check fail.
Each behavioural half was proven by breaking the behaviour it measures: the
``DecodeError`` conversion, the ``TYPE_CHECKING`` gate, an importer of
``_cli_utils`` removed or added. The Requirements comparison was proven from
both files: a bound changed in the README, and a bound changed in
``pyproject.toml``.
"""

from __future__ import annotations

import builtins
import json
import re
import sys
import typing
from pathlib import Path

import pytest
import yaml
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
from google.protobuf.internal import api_implementation
from google.protobuf.message import Message
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.utils import canonicalize_name

import protokit._pools as pools
import protokit.schema.lint._cli_utils as cli_utils
from protokit._cli_utils import load_descriptor_pool
from protokit._pools import DescriptorPoolError, load_pool_from_path
from protokit.formatters import FormatterContext, FormatterKind, get_formatter
from protokit.formatters._builtin_lint import lint_sarif
from protokit.message import diff_messages
from protokit.message.model import Diagnostic, DiffResult
from protokit.schema import CompatibilityLevel, check_compatibility
from protokit.schema.checker import SchemaChecker
from protokit.schema.lint.model import LintReport
from protokit.schema.model import (
    CommitDiagnostic,
    bisect_report_to_dict,
    history_report_to_dict,
)
from tests._trust_reports import (
    bisect_report,
    compat_report,
    error_diagnostic,
    history_report,
    lint_report,
    truncated_diff_result,
    warning_diagnostic,
)
from tests.meta.test_import_layers import (
    _REPO_ROOT,
    _SRC_ROOT,
    PACKAGE,
    build_import_graph,
    import_in_fresh_interpreter,
)
from tests.meta.test_minimal_install_cell_presence_ratchet import python_floor
from tests.meta.test_upgrade_notes_presence_ratchet import (
    _changelog_release_section,
    _readme_section,
)
from tests.proto_builder import ProtoBuilder

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

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
    import pulls in. It runs through ``import_in_fresh_interpreter``, as the
    sweep of the real tree does, so ``protokit`` resolves from ``src`` rather
    than from whatever is installed.
    """
    code = (
        f"import json, sys\nimport {importing}\n"
        f"print(json.dumps({{m: m in sys.modules for m in {list(modules)!r}}}))"
    )
    result = import_in_fresh_interpreter(importing, src_root=_SRC_ROOT, cwd=_REPO_ROOT, code=code)
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

    The second half is the open gap V20, owned by U4 (0.18.0) and pinned by
    ``test_v20_map_key_type_change_is_reported_at_wire`` in the U9 compat pins;
    its fix fails ``test_key_type_change_currently_passes_at_every_level_v20``.
    """

    def test_key_type_is_declared_by_the_user(self) -> None:
        def key_type(builder: ProtoBuilder) -> int:
            items = builder.pool.FindMessageTypeByName("t.M").fields_by_name["items"]
            key: int = items.message_type.fields_by_name["key"].type
            return key

        assert key_type(_map_pool(T.TYPE_INT32)) == T.TYPE_INT32
        assert key_type(_map_pool(T.TYPE_STRING)) == T.TYPE_STRING

    def test_key_type_change_currently_passes_at_every_level_v20(self) -> None:
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


def _runtime_rejected_set() -> bytes:
    """A set that parses and sorts, but whose int32 default the runtime cannot read."""
    fds = descriptor_pb2.FileDescriptorSet()
    fdp = fds.file.add(name="a.proto", package="a", syntax="proto2")
    fdp.message_type.add(name="M").field.add(
        name="x", number=1, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL, default_value="abc"
    )
    return fds.SerializeToString()


_WHERE_POOLS = "load_pool_from_path's docstring"


class TestLoadPoolFromPathDocstring:
    """Each failure the docstring names raises the exception it names there.

    The docstring used to promise "a protobuf parse exception" for a malformed
    file. ``load_pool_from_bytes`` converts ``DecodeError`` to
    ``DescriptorPoolError``, so a caller catching the protobuf exception
    caught nothing. The prose checks tie each failure to its exception, so a
    docstring that swapped the two would fail.
    """

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(b"\xff\xff\xff", id="does-not-parse"),
            pytest.param(bytes.fromhex("0a060a01ff1a01ff"), id="name-not-utf8-in-a-cycle"),
            pytest.param(_unbuildable_set(), id="missing-dependency"),
            pytest.param(_runtime_rejected_set(), id="rejected-by-the-runtime"),
        ],
    )
    def test_file_that_does_not_parse_or_build_raises_the_typed_error(
        self, tmp_path: Path, data: bytes
    ) -> None:
        # Pure-Python rejects the last case with ValueError and upb with
        # TypeError; both must reach the caller as DescriptorPoolError.
        path = tmp_path / "schema.descriptor_set"
        path.write_bytes(data)
        with pytest.raises(DescriptorPoolError):
            load_pool_from_path(path)

    def test_unreadable_path_raises_oserror(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            load_pool_from_path(tmp_path / "absent.descriptor_set")

    @pytest.mark.parametrize(
        "phrase",
        [
            "does not parse or build raises ``DescriptorPoolError``",
            "an unreadable path raises ``OSError``",
        ],
    )
    def test_docstring_ties_each_failure_to_its_exception(self, phrase: str) -> None:
        assert phrase in _prose(load_pool_from_path.__doc__), _missing(phrase, _WHERE_POOLS)

    def test_docstring_names_no_other_exception(self) -> None:
        # Fails on the original docstring, which named no exception class at
        # all, and on one that adds a class the function does not raise.
        documented = _documented_exceptions()
        assert documented == {DescriptorPoolError, OSError}, (
            f"load_pool_from_path's docstring names {sorted(c.__name__ for c in documented)} "
            "as the exceptions it raises; it raises DescriptorPoolError for a file that "
            "does not parse or build and OSError for an unreadable path"
        )

    @pytest.mark.parametrize(
        "function",
        [load_pool_from_path, load_descriptor_pool],
        ids=["load_pool_from_path", "_cli_utils.load_descriptor_pool"],
    )
    def test_docstring_does_not_promise_a_protobuf_exception(
        self, function: typing.Callable[..., object]
    ) -> None:
        # load_descriptor_pool delegates to load_pool_from_path and repeated
        # the same promise.
        phrase = "protobuf parse exception"
        assert phrase not in _prose(function.__doc__), _returned(
            phrase,
            f"{function.__qualname__}'s docstring",
            "a DecodeError is converted to DescriptorPoolError",
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


# ---------------------------------------------------------------------------
# Re-audit claim 1: README upgrade note 9, descriptor sets and the two runtimes
# ---------------------------------------------------------------------------

_README_PATH = _REPO_ROOT / "README.md"
_CHANGELOG_PATH = _REPO_ROOT / "CHANGELOG.md"
_PURE_PYTHON = api_implementation.Type() == "python"
_WHERE_NOTE_9 = "README upgrade note 9"
_WHERE_README = "README.md"


def _as_prose(text: str) -> str:
    """``text`` with ``#`` and ``>`` line markers dropped and whitespace collapsed."""
    return _prose("\n".join(line.strip().lstrip("#>") for line in text.splitlines()))


def _file_prose(path: Path) -> str:
    return _as_prose(path.read_text(encoding="utf-8"))


def _changelog_release() -> str:
    """The CHANGELOG section that carries the 0.16.0 upgrade note, as prose.

    Found by its note, not by a ``## Unreleased`` heading, so the guards keep
    reading the same text once the release is cut and the heading is renamed.
    """
    return _as_prose(_changelog_release_section())


def _readme_upgrade_note(number: int) -> str:
    """Item ``number`` of the README's 0.16.0 pre-upgrade checklist, as prose."""
    body = _readme_section()
    start = re.search(rf"^{number}\. \*\*", body, flags=re.MULTILINE)
    assert start, f"README's 0.16.0 upgrade notes have no item numbered {number}"
    item = body[start.end():]
    end = re.search(r"^(?:\d+\. \*\*|\*\*|#)", item, flags=re.MULTILINE)
    return _prose(item[: end.start()] if end else item)


def _one_file_set(build: typing.Callable[[descriptor_pb2.FileDescriptorProto], None]) -> bytes:
    fds = descriptor_pb2.FileDescriptorSet()
    build(fds.file.add(name="a.proto", package="a", syntax="proto3"))
    return fds.SerializeToString()


def _duplicate_field_number(fdp: descriptor_pb2.FileDescriptorProto) -> None:
    message = fdp.message_type.add(name="M")
    for name in ("x", "y"):
        message.field.add(name=name, number=1, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL)


#: A set holding one file, ``a.proto``, whose only fault is a leading comment
#: of the single byte ``ff``. Written as bytes because neither runtime lets a
#: ``str`` field be assigned one, and with nothing else wrong so that only
#: the UTF-8 check can refuse it (a non-UTF-8 *name* would also break the
#: dependency sort).
_NON_UTF8_COMMENT_SET = bytes.fromhex("0a10" "0a07612e70726f746f" "4a05" "0a03" "1a01ff")
#: The same file with that comment written twice: ``ff``, then ``valid``. A
#: parser keeps the last copy of a singular field, so the parsed set holds no
#: invalid string, and only a runtime that validates while parsing refuses it.
_OVERWRITTEN_COMMENT_SET = bytes.fromhex(
    "0a17" "0a07612e70726f746f" "4a0c" "0a0a" "1a01ff" "1a0576616c6964"
)


def _dangling_type_reference(fdp: descriptor_pb2.FileDescriptorProto) -> None:
    fdp.message_type.add(name="M").field.add(
        name="x", number=1, type=T.TYPE_MESSAGE, label=T.LABEL_OPTIONAL, type_name=".a.Absent"
    )


class TestDescriptorSetLoadingNote:
    """The two runtimes refuse the same three kinds of set, not every kind.

    Note 9 used to open "Every command now loads a descriptor set the same way
    on both protobuf runtimes". 0.16.0 aligned three kinds: a missing import,
    a type reference that resolves nowhere, and a string that is not UTF-8.
    Pure-Python still builds sets upb refuses, a duplicate field number among
    them, and protokit adds no validation of its own. If that changes,
    ``test_duplicate_field_number_loads_on_pure_python_only`` fails; rewrite
    the note in the same change.
    """

    @pytest.mark.parametrize(
        "data",
        [
            pytest.param(_unbuildable_set(), id="missing-import"),
            pytest.param(_one_file_set(_dangling_type_reference), id="dangling-type-reference"),
            pytest.param(_NON_UTF8_COMMENT_SET, id="string-not-utf8"),
        ],
    )
    def test_the_three_aligned_kinds_are_refused(self, tmp_path: Path, data: bytes) -> None:
        path = tmp_path / "schema.descriptor_set"
        path.write_bytes(data)
        with pytest.raises(DescriptorPoolError):
            load_pool_from_path(path)

    def test_duplicate_field_number_loads_on_pure_python_only(self, tmp_path: Path) -> None:
        path = tmp_path / "schema.descriptor_set"
        path.write_bytes(_one_file_set(_duplicate_field_number))
        if _PURE_PYTHON:
            pool = load_pool_from_path(path)
            assert [f.name for f in pool.FindMessageTypeByName("a.M").fields] == ["x", "y"]
        else:
            with pytest.raises(DescriptorPoolError):
                load_pool_from_path(path)

    def test_string_overwritten_on_the_wire_loads_on_upb_only(self, tmp_path: Path) -> None:
        # The limit the note states: the UTF-8 check reads the parsed set.
        path = tmp_path / "schema.descriptor_set"
        path.write_bytes(_OVERWRITTEN_COMMENT_SET)
        if _PURE_PYTHON:
            with pytest.raises(DescriptorPoolError):
                load_pool_from_path(path)
        else:
            assert load_pool_from_path(path).FindFileByName("a.proto").name == "a.proto"

    @pytest.mark.parametrize(
        "phrase",
        [
            "a missing import",
            "a type reference that resolves nowhere",
            "a string that is not UTF-8",
            "a string written twice on the wire",
            "pure-Python accepts some that upb refuses, such as a duplicate field number",
        ],
    )
    def test_note_names_what_was_aligned_and_what_was_not(self, phrase: str) -> None:
        assert phrase in _readme_upgrade_note(9), _missing(phrase, _WHERE_NOTE_9)

    def test_readme_does_not_claim_every_set_loads_alike(self) -> None:
        phrase = "the same way on both"
        assert phrase not in _file_prose(_README_PATH), _returned(
            phrase, _WHERE_README, "pure-Python builds sets upb refuses to build"
        )


# ---------------------------------------------------------------------------
# Re-audit claim 2: EQUIVALENT and a default-valued extension
# ---------------------------------------------------------------------------

_DIFFER_PATH = _SRC_ROOT / PACKAGE / "message" / "differ.py"
_FOLD_IN = "if left_view.has_extension_ranges or right_view.has_extension_ranges:"
_WHERE_FOLD_IN = "The comment above the extension fold-in in message/differ.py"
_WHERE_CHANGELOG_EXTENSIONS = "CHANGELOG's entry on declared proto2 extensions"


def _presence_classes() -> tuple[type[Message], typing.Any, typing.Any]:
    """proto2 ``t.M`` with a declared and an extension twin of a scalar and a message."""
    pool = descriptor_pool.DescriptorPool()
    fdp = descriptor_pb2.FileDescriptorProto(name="t.proto", package="t", syntax="proto2")
    fdp.message_type.add(name="Sub").field.add(
        name="x", number=1, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL
    )
    message = fdp.message_type.add(name="M")
    message.field.add(
        name="sub", number=1, type=T.TYPE_MESSAGE, label=T.LABEL_OPTIONAL, type_name=".t.Sub"
    )
    message.field.add(name="num", number=2, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL)
    message.extension_range.add(start=100, end=200)
    fdp.extension.add(
        name="sub", number=100, type=T.TYPE_MESSAGE, label=T.LABEL_OPTIONAL,
        extendee=".t.M", type_name=".t.Sub",
    )
    fdp.extension.add(
        name="num", number=101, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL, extendee=".t.M"
    )
    pool.Add(fdp)
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName("t.M"))
    return cls, pool.FindExtensionByName("t.sub"), pool.FindExtensionByName("t.num")


def _reported(left: Message, right: Message) -> list[tuple[str, str]]:
    return [(str(d.path), d.change_type.name) for d in diff_messages(left, right)]


class TestEquivalentExtensionCollapse:
    """Under EQUIVALENT only a scalar at its default or an empty message equals unset.

    0.16.0's extension entry said an extension "set to its default on one side
    and unset on the other collapses". A message extension holding a sub-field
    set to its default does not: it is reported at the sub-field, which is
    what a declared message field has always done. The declared twin is
    measured beside each extension case so the two cannot drift apart
    unnoticed.
    """

    def test_scalar_at_its_default_equals_unset(self) -> None:
        cls, _sub, num = _presence_classes()
        left, right = cls(), cls()
        right.Extensions[num] = 0
        right.num = 0
        assert _reported(left, right) == []

    def test_empty_message_equals_unset(self) -> None:
        cls, sub, _num = _presence_classes()
        left, right = cls(), cls()
        right.Extensions[sub].SetInParent()
        right.sub.SetInParent()
        assert _reported(left, right) == []

    def test_message_with_a_default_valued_sub_field_is_reported(self) -> None:
        cls, sub, _num = _presence_classes()
        left, right = cls(), cls()
        right.Extensions[sub].x = 0
        right.sub.x = 0
        assert _reported(left, right) == [("(t.sub).x", "ADDED"), ("sub.x", "ADDED")]

    def test_same_sub_field_collapses_once_both_sides_hold_the_message(self) -> None:
        # The half of the old claim that is true: with the message present on
        # both sides, the default-valued sub-field is an ordinary scalar.
        cls, sub, _num = _presence_classes()
        left, right = cls(), cls()
        left.Extensions[sub].SetInParent()
        right.Extensions[sub].x = 0
        assert _reported(left, right) == []

    @pytest.mark.parametrize(
        "phrase", ["a scalar at its default or an empty message", "a sub-field set does not"]
    )
    def test_fold_in_comment_states_the_rule(self, phrase: str) -> None:
        comment = _prose(_comment_above(_DIFFER_PATH, _FOLD_IN))
        assert phrase in comment, _missing(phrase, _WHERE_FOLD_IN)

    def test_fold_in_comment_does_not_generalise(self) -> None:
        phrase = "a default-valued field equals an unset one"
        comment = _prose(_comment_above(_DIFFER_PATH, _FOLD_IN))
        assert phrase not in comment, _returned(
            phrase, _WHERE_FOLD_IN, "a message whose sub-field is set to a default is reported"
        )

    @pytest.mark.parametrize(
        "phrase",
        [
            "a scalar extension set to its default, or an empty message extension",
            "is reported field by field, as a declared message field is",
        ],
    )
    def test_changelog_states_the_rule(self, phrase: str) -> None:
        assert phrase in _changelog_release(), _missing(phrase, _WHERE_CHANGELOG_EXTENSIONS)

    def test_changelog_does_not_generalise(self) -> None:
        phrase = "(set to its default on one side and unset on the other collapses"
        assert phrase not in _changelog_release(), _returned(
            phrase,
            _WHERE_CHANGELOG_EXTENSIONS,
            "a message extension whose sub-field is set to a default is reported",
        )


# ---------------------------------------------------------------------------
# Re-audit claim 3: what ``complete`` and SARIF ``executionSuccessful`` compute
# ---------------------------------------------------------------------------


def _render(name: str, kind: FormatterKind, report: object) -> typing.Any:
    out = get_formatter(name, kind)(report, FormatterContext(subcommand="guard"))  # type: ignore[arg-type]
    return json.loads(out)


def _lint_sarif_succeeded(report: LintReport) -> bool:
    # ``lint`` renders through its own functions, not the formatter registry.
    document = json.loads(lint_sarif(report, FormatterContext(subcommand="guard")))
    succeeded: bool = document["runs"][0]["invocations"][0]["executionSuccessful"]
    return succeeded


def _unknown_field_only_pair() -> tuple[Message, Message]:
    """Two ``u.M`` messages that differ only in field 2, which ``u.M`` does not declare."""
    builder = ProtoBuilder()
    builder.message("u.M", {"a": (T.TYPE_INT32, 1)})
    cls = builder.get_message_class("u.M")
    left, right = cls(), cls()
    left.ParseFromString(bytes([0x10, 1]))
    right.ParseFromString(bytes([0x10, 2]))
    return left, right


#: Each function that emits one of the two fields, with the phrase its
#: docstring uses for what the field computes.
_COMPLETE_DOCSTRINGS: list[tuple[typing.Callable[..., object], str]] = [
    (get_formatter("json", FormatterKind.DIFF), "a difference the differ does not look for"),
    (get_formatter("json", FormatterKind.COMPAT), "it is not a coverage check"),
    (history_report_to_dict, "nothing else about the walk is checked"),
    (bisect_report_to_dict, "false when the walk recorded an error-level diagnostic"),
    (lint_sarif, "``executionSuccessful`` is false when ``protokit._trust`` distrusts the report"),
]


class TestCompleteReportsWhatTheRunRecorded:
    """``complete`` and ``executionSuccessful`` are a record, not a coverage check.

    Both are ``protokit._trust``'s answer: false when the report carries a
    reason the run knows it did not finish, true otherwise. 0.16.0's prose
    said more ("a green exit now means the analysis ran", "false whenever the
    analysis did not complete"), which reads as a promise that every input
    was analysed. An input skipped without a record leaves both true.

    The two skipped-input tests measure open gaps scheduled for later
    releases: unknown fields are not compared, and the ``extension_unresolved``
    warning is not gated. When either closes, its test fails; that is the
    signal to drop the example from the prose in the same change.
    """

    def test_a_difference_in_unknown_fields_leaves_complete_true(self) -> None:
        payload = _render("json", FormatterKind.DIFF, diff_messages(*_unknown_field_only_pair()))
        assert (payload["equal"], payload["complete"], payload["diagnostics"]) == (True, True, [])

    def test_a_depth_cut_or_an_error_diagnostic_makes_diff_incomplete(self) -> None:
        truncated = _render("json", FormatterKind.DIFF, truncated_diff_result())
        assert (truncated["equal"], truncated["complete"]) == (False, False)
        assert truncated["truncated_paths"]
        with_error = DiffResult(differences=(), diagnostics=(error_diagnostic(),))
        errored = _render("json", FormatterKind.DIFF, with_error)
        assert (errored["equal"], errored["complete"]) == (False, False)
        assert errored["truncated_paths"] == []
        with_warning = DiffResult(differences=(), diagnostics=(warning_diagnostic(),))
        warned = _render("json", FormatterKind.DIFF, with_warning)
        assert (warned["equal"], warned["complete"]) == (True, True)

    @pytest.mark.parametrize(
        ("diagnostics", "complete"),
        [
            pytest.param((), True, id="no-diagnostic"),
            pytest.param((warning_diagnostic(),), True, id="warning"),
            pytest.param((error_diagnostic(),), False, id="error"),
        ],
    )
    def test_compat_complete_is_the_absence_of_an_error_diagnostic(
        self, diagnostics: tuple[Diagnostic, ...], complete: bool
    ) -> None:
        report = compat_report(*diagnostics)
        assert _render("json", FormatterKind.COMPAT, report)["complete"] is complete

    def test_history_and_bisect_complete_follow_the_same_rule(self) -> None:
        assert history_report_to_dict(history_report())["complete"] is True
        broken = history_report(entry_diags=(error_diagnostic(),))
        assert history_report_to_dict(broken)["complete"] is False
        assert bisect_report_to_dict(bisect_report())["complete"] is True
        walk_error = CommitDiagnostic("d" * 40, "error", None, "walk broke")
        assert bisect_report_to_dict(bisect_report(walk_error))["complete"] is False

    @pytest.mark.parametrize(
        ("category", "succeeded"),
        [
            ("rule_exception", False),
            ("unloaded_rule", False),
            ("all_files_excluded", False),
            ("extension_unresolved", True),
            ("custom_annotation_extension_unresolved", True),
        ],
    )
    def test_sarif_execution_successful_follows_the_gated_categories(
        self, category: str, succeeded: bool
    ) -> None:
        assert _lint_sarif_succeeded(lint_report(categories=(category,))) is succeeded

    def test_sarif_execution_successful_is_false_for_a_compile_error(self) -> None:
        assert _lint_sarif_succeeded(lint_report(compile_error="boom")) is False
        assert _lint_sarif_succeeded(lint_report()) is True

    @pytest.mark.parametrize(
        ("function", "phrase"), _COMPLETE_DOCSTRINGS, ids=lambda v: getattr(v, "__name__", None)
    )
    def test_docstring_states_what_the_field_computes(
        self, function: typing.Callable[..., object], phrase: str
    ) -> None:
        where = f"{function.__name__}'s docstring"
        assert phrase in _prose(function.__doc__), _missing(phrase, where)

    def test_lint_sarif_docstring_does_not_credit_compile_errors_alone(self) -> None:
        phrase = '``"error"`` and flip ``executionSuccessful`` to false'
        doc = _prose(lint_sarif.__doc__)
        assert phrase not in doc, _returned(
            phrase, "lint_sarif's docstring", "a rule that raised or never loaded flips it too"
        )

    @pytest.mark.parametrize(
        "phrase",
        [
            "`complete` reports what the run recorded, not what it covered",
            "(unknown fields) are not compared",
            "A run that records it could not finish",
            "`custom_annotation_extension_unresolved` warnings leave it `true`",
        ],
    )
    def test_readme_states_what_the_fields_compute(self, phrase: str) -> None:
        assert phrase in _file_prose(_README_PATH), _missing(phrase, _WHERE_README)

    @pytest.mark.parametrize(
        "phrase",
        [
            "says nothing else about what the check covered",
            "It is not a check that every rule ran",
            "an input skipped without a record still exits 0",
        ],
    )
    def test_changelog_states_what_the_fields_compute(self, phrase: str) -> None:
        assert phrase in _changelog_release(), _missing(phrase, "The CHANGELOG's 0.16.0 section")

    @pytest.mark.parametrize(
        "prose",
        [
            pytest.param(lambda: _file_prose(_README_PATH), id="README.md"),
            # Scoped to the release that made the claim: older sections are history.
            pytest.param(_changelog_release, id="CHANGELOG.md"),
        ],
    )
    @pytest.mark.parametrize(
        "phrase",
        [
            "now means the analysis ran",
            "a green exit mean the analysis ran",
            "false whenever the analysis did not complete",
        ],
    )
    def test_prose_does_not_promise_the_analysis_covered_everything(
        self, prose: typing.Callable[[], str], phrase: str
    ) -> None:
        assert phrase not in prose(), _returned(
            phrase,
            "README.md or the CHANGELOG's 0.16.0 section",
            "an input skipped without a record still reads as success",
        )


# ---------------------------------------------------------------------------
# README Requirements: the dependencies pip installs
# ---------------------------------------------------------------------------

_PYPROJECT_PATH = _REPO_ROOT / "pyproject.toml"
_WHERE_REQUIREMENTS = "README.md's Requirements section"
_PYTHON_CLASSIFIER = re.compile(r"Programming Language :: Python :: (\d+\.\d+)")
_PYTHON_BULLET = re.compile(r"- Python (\d+\.\d+)\+")
# One bound is an operator, one space, and a version with no space inside it, so
# dropping the spaces to compare cannot join two tokens into a different version.
_BOUND = r"(?:~=|==|!=|<=|>=|<|>) \d[0-9A-Za-z.*]*"
_DEPENDENCY_BULLET = re.compile(
    rf"- `(?P<name>[A-Za-z0-9._-]+)` (?P<bounds>{_BOUND}(?:, {_BOUND})*)"
    r"(?: \(Python (?P<pythons>\d+\.\d+(?:(?:, | and )\d+\.\d+)*) only\))?"
)
# A marker on anything but the interpreter's minor version cannot be written as
# "Python X.Y only", and evaluating one here would read this machine.
_OTHER_MARKER_VARIABLE = re.compile(
    r"\b(?:os_name|sys_platform|platform_\w+|implementation_\w+|python_full_version|extra)\b"
)

# One requirement as both files state it: canonical name, version bounds, and
# the supported Python versions a conditional one is installed on. An
# unconditional requirement carries ``()``, which no conditional one can: a
# README note naming every supported version is still a condition, and it
# would wrongly rule out the next Python release.
_Stated = tuple[str, str, tuple[str, ...]]


def _project_table() -> dict[str, typing.Any]:
    table: dict[str, typing.Any] = tomllib.loads(_PYPROJECT_PATH.read_text(encoding="utf-8"))[
        "project"
    ]
    return table


def _supported_pythons() -> tuple[str, ...]:
    """Every ``X.Y`` the package's classifiers say it supports."""
    found = tuple(
        match.group(1)
        for classifier in _project_table()["classifiers"]
        if (match := _PYTHON_CLASSIFIER.fullmatch(classifier))
    )
    assert found, "pyproject.toml classifies no 'Programming Language :: Python :: X.Y'"
    return found


def _declared_requirements() -> list[_Stated]:
    """``[project].dependencies``, each with the supported Pythons its marker admits."""
    pythons = _supported_pythons()
    declared: list[_Stated] = []
    for raw in _project_table()["dependencies"]:
        requirement = Requirement(raw)
        if requirement.extras or requirement.url:
            pytest.fail(
                f"{raw!r} names an extra or a URL. Decide how {_WHERE_REQUIREMENTS} "
                "should say that, then teach this test to read it."
            )
        installed_on: tuple[str, ...] = ()
        if requirement.marker is not None:
            if _OTHER_MARKER_VARIABLE.search(str(requirement.marker)):
                pytest.fail(
                    f"{raw!r} is conditional on more than the Python version. Decide how "
                    f"{_WHERE_REQUIREMENTS} should say that, then teach this test to read it."
                )
            installed_on = tuple(
                python
                for python in pythons
                if requirement.marker.evaluate({"python_version": python})
            )
            if not installed_on:
                pytest.fail(f"{raw!r} is installed on no Python the classifiers list.")
        declared.append(
            (canonicalize_name(requirement.name), str(requirement.specifier), installed_on)
        )
    return sorted(declared)


def _requirements_lines() -> list[str]:
    """Every non-blank line of the section, sub-headings included, up to the next ``##``."""
    body = _README_PATH.read_text(encoding="utf-8")
    heading = re.search(r"^## Requirements\n", body, flags=re.MULTILINE)
    assert heading, "README.md has no '## Requirements' section"
    section = body[heading.end():]
    end = re.search(r"^#{1,2} ", section, flags=re.MULTILINE)
    lines = (section[: end.start()] if end else section).splitlines()
    return [line for line in lines if line.strip()]


def _listed_requirements() -> list[_Stated]:
    """Every dependency the README section lists; a line that is not one fails.

    The section is its bullets and nothing else. A sentence beside them, or a
    bullet in another shape, would be a claim about requirements that nothing
    here compares with ``pyproject.toml``.
    """
    pythons = _supported_pythons()
    listed: list[_Stated] = []
    for line in _requirements_lines():
        if _PYTHON_BULLET.fullmatch(line):
            continue
        match = _DEPENDENCY_BULLET.fullmatch(line)
        if match is None:
            pytest.fail(
                f"{_WHERE_REQUIREMENTS} has a line this test cannot read: {line!r}. "
                'Every line there is "- Python X.Y+" or "- `name` >= X, < Y", with '
                '" (Python X.Y only)" after the bounds when the dependency is conditional.'
            )
        only = match.group("pythons")
        installed_on = tuple(re.findall(r"\d+\.\d+", only)) if only else ()
        if unknown := [python for python in installed_on if python not in pythons]:
            pytest.fail(
                f"{_WHERE_REQUIREMENTS} conditions {match.group('name')} on Python "
                f"{unknown}, which pyproject.toml's classifiers do not list."
            )
        bounds = str(SpecifierSet(match.group("bounds").replace(" ", "")))
        listed.append((canonicalize_name(match.group("name")), bounds, installed_on))
    return sorted(listed)


class TestReadmeRequirements:
    """The README's Requirements section is what ``pip install protokit`` resolves.

    It listed ``protobuf >= 4.21.0`` and ``click`` and nothing else. A reader took
    protobuf 6 to be supported, which ``pyproject.toml`` rules out, and could not
    see ``pathspec`` or the two Python 3.10 backports at all. ``pyproject.toml`` is
    the side pip acts on, so the README is held to it: every runtime dependency,
    its bounds, and the Python versions it is installed on.
    """

    def test_every_runtime_dependency_is_listed_with_its_bounds(self) -> None:
        declared = _declared_requirements()
        assert declared, "pyproject.toml declares no runtime dependencies"
        listed = _listed_requirements()
        assert listed == declared, (
            f"{_WHERE_REQUIREMENTS} and pyproject.toml's [project].dependencies disagree "
            "(name, bounds, Python versions installed on).\n"
            f"  README only:    {[entry for entry in listed if entry not in declared]}\n"
            f"  pyproject only: {[entry for entry in declared if entry not in listed]}\n"
            "pyproject.toml is what pip acts on; change the README to match it."
        )

    def test_python_floor_is_the_one_requires_python_sets(self) -> None:
        floors = [
            match.group(1)
            for line in _requirements_lines()
            if (match := _PYTHON_BULLET.fullmatch(line))
        ]
        floor = python_floor(_PYPROJECT_PATH.read_text(encoding="utf-8"))
        assert floors == [floor], (
            f"{_WHERE_REQUIREMENTS} should carry one '- Python {floor}+' bullet, the "
            f"floor requires-python sets; it carries {floors}."
        )


# ---------------------------------------------------------------------------
# The protobuf floor: what pyproject.toml declares is what CI installs
# ---------------------------------------------------------------------------

_CI_WORKFLOW_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
_FLOOR_JOB = "storage-protobuf-floor"
_FLOOR_INSTALL = re.compile(r'pip install "protobuf==(\d+\.\d+)\.\*"')


class TestProtobufFloor:
    """The oldest protobuf ``pyproject.toml`` admits is the one a CI job installs.

    The declared floor was ``4.21.0`` while the one job on an old protobuf
    installed ``4.25.*``, so 4.21 to 4.24 were supported on paper and run by
    nothing. Under pure-Python, 4.21 to 4.23 read every custom option on a
    schema in its own pool as absent.
    """

    @staticmethod
    def _declared_floor() -> str:
        (specifier,) = [
            Requirement(raw).specifier
            for raw in _project_table()["dependencies"]
            if canonicalize_name(Requirement(raw).name) == "protobuf"
        ]
        (lower,) = [bound.version for bound in specifier if bound.operator == ">="]
        major, minor = lower.split(".")[:2]
        return f"{major}.{minor}"

    @staticmethod
    def _installed_by_the_floor_job() -> list[str]:
        workflow = yaml.safe_load(_CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
        steps = workflow["jobs"][_FLOOR_JOB]["steps"]
        return [
            match.group(1)
            for step in steps
            for match in _FLOOR_INSTALL.finditer(step.get("run", ""))
        ]

    def test_the_floor_job_runs_the_whole_suite_on_both_backends(self) -> None:
        """Not a subtree: it ran ``tests/storage`` alone while editions cases failed unseen."""
        workflow = yaml.safe_load(_CI_WORKFLOW_PATH.read_text(encoding="utf-8"))
        runs: list[tuple[str, tuple[str, ...]]] = []
        for step in workflow["jobs"][_FLOOR_JOB]["steps"]:
            backend = step.get("env", {}).get("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "default")
            for line in step.get("run", "").splitlines():
                words = line.split()
                if words[:1] == ["pytest"]:
                    runs.append((backend, tuple(word for word in words[1:] if "/" in word)))
        assert runs == [("default", ("tests/",)), ("python", ("tests/",))], (
            f"the {_FLOOR_JOB} job should run `pytest tests/` once on the default backend "
            f"and once under PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python; it runs {runs}."
        )

    def test_the_floor_job_installs_the_declared_floor(self) -> None:
        declared = self._declared_floor()
        assert self._installed_by_the_floor_job() == [declared], (
            f"pyproject.toml declares protobuf>={declared}; the {_FLOOR_JOB} job in "
            f"{_CI_WORKFLOW_PATH.name} should install exactly that line, with "
            f'pip install "protobuf=={declared}.*". Move the two together.'
        )


# ---------------------------------------------------------------------------
# Second re-audit: release text it found too wide
# ---------------------------------------------------------------------------

_WHERE_NOTE_7 = "README upgrade note 7"
_WHERE_RELEASE = "The CHANGELOG's 0.16.0 section"
_WHERE_ADD_AND_RESOLVE = "add_and_resolve's docstring"


_FileBuilder = typing.Callable[[descriptor_pb2.FileDescriptorProto], None]


def _set_file(tmp_path: Path, build: _FileBuilder) -> Path:
    """``build`` one proto3 file ``a.proto`` (package ``a``) and write it as a set."""
    path = tmp_path / "schema.desc"
    path.write_bytes(_one_file_set(build))
    return path


def _descriptor_named_field(fdp: descriptor_pb2.FileDescriptorProto) -> None:
    fdp.message_type.add(name="M").field.add(
        name="DESCRIPTOR", number=1, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL
    )


class TestPurePythonCrashNote:
    """Note 7 names the crash that is gone and the ones that are not.

    It used to say that under pure-Python ``compat`` and ``forensics`` "no
    longer crash on any schema loaded from a descriptor set or ``.proto``".
    The crash 0.16.0 removed is ``Descriptor does not contain serialization``
    (V34). A set whose edition the runtime does not implement, a field named
    ``DESCRIPTOR`` and a very long chain of nested message types still end in
    a traceback, as in 0.15.1; the note and the CHANGELOG's Known issues say
    so. When the ``DESCRIPTOR`` case is fixed,
    ``test_a_field_named_descriptor_currently_ends_forensics_match_in_a_traceback``
    fails: drop that example from the prose in the same change.
    """

    def test_a_field_named_descriptor_currently_ends_forensics_match_in_a_traceback(
        self, tmp_path: Path
    ) -> None:
        from click.testing import CliRunner

        from protokit.cli import main

        schema = _set_file(tmp_path, _descriptor_named_field)
        message = tmp_path / "m.bin"
        message.write_bytes(bytes([0x08, 0x01]))
        result = CliRunner().invoke(
            main, ["forensics", "match", "--schema", f"v={schema}", "--type", "a.M", str(message)]
        )
        if not _PURE_PYTHON:
            assert result.exit_code == 0, (result.exit_code, result.output)
            return
        assert (result.exit_code, type(result.exception)) == (1, AttributeError), (
            f"forensics match on a field named DESCRIPTOR now exits {result.exit_code} "
            f"({result.exception!r}) under pure-Python; README note 7 and the CHANGELOG's "
            "Known issues still name it as a crash, so rewrite them in the same change"
        )

    @pytest.mark.parametrize(
        "phrase",
        [
            "no longer crash with `Descriptor does not contain serialization`",
            "Not every pure-Python crash is gone",
            "a field named `DESCRIPTOR`",
        ],
    )
    def test_note_names_the_crash_that_is_gone_and_the_ones_left(self, phrase: str) -> None:
        assert phrase in _readme_upgrade_note(7), _missing(phrase, _WHERE_NOTE_7)

    def test_changelog_row_scopes_the_exit_code_to_that_crash(self) -> None:
        phrase = "that crash no longer decides the exit code"
        assert phrase in _changelog_release(), _missing(phrase, _WHERE_RELEASE)

    @pytest.mark.parametrize(
        ("prose", "phrase"),
        [
            pytest.param(
                lambda: _file_prose(_README_PATH), "no longer crash on any schema",
                id="README-any-schema",
            ),
            pytest.param(
                lambda: _file_prose(_README_PATH), "their exit code is now the check's own",
                id="README-exit-code",
            ),
            pytest.param(_changelog_release, "no longer crash on any schema",
                         id="CHANGELOG-any-schema"),
            pytest.param(_changelog_release, "the exit code is now the check's own",
                         id="CHANGELOG-exit-code"),
        ],
    )
    def test_prose_does_not_claim_every_schema(
        self, prose: typing.Callable[[], str], phrase: str
    ) -> None:
        assert phrase not in prose(), _returned(
            phrase, "README.md or the CHANGELOG's 0.16.0 section",
            "a field named DESCRIPTOR still ends forensics in a traceback under pure-Python",
        )


class TestAddAndResolveDocstring:
    """``FindFileByName`` forces resolution, not every check the runtime makes later.

    The docstring said ``FindFileByName`` "forces it here on both", read as a
    promise that a set which loads is a set the runtime accepts. Under
    pure-Python an edition-2024 file loads and raises ``TypeError`` at first
    use (C02-C1, pinned in ``tests/core/test_audit_c_pools_pins.py``). When
    that is fixed,
    ``test_an_unimplemented_edition_currently_loads_and_fails_at_first_use``
    fails: rewrite the docstring in the same change.
    """

    def test_an_unimplemented_edition_currently_loads_and_fails_at_first_use(self) -> None:
        from tests.core.test_audit_c_pools_pins import _edition_set

        data = _edition_set("EDITION_2024")  # skips where the runtime implements no editions
        if not _PURE_PYTHON:
            with pytest.raises(DescriptorPoolError):
                pools.load_pool_from_bytes(data)
            return
        pool = pools.load_pool_from_bytes(data)
        with pytest.raises(TypeError, match="EDITION_2024"):
            pools.get_message_class(pool, "auditcpools.M")

    @pytest.mark.parametrize(
        "phrase",
        [
            "``FindFileByName`` forces dependency and symbol resolution here on both, "
            "not every later check",
            "raises ``TypeError`` at first use",
        ],
    )
    def test_docstring_states_what_the_lookup_forces(self, phrase: str) -> None:
        doc = _prose(pools.add_and_resolve.__doc__)
        assert phrase in doc, _missing(phrase, _WHERE_ADD_AND_RESOLVE)

    def test_docstring_does_not_claim_the_lookup_forces_everything(self) -> None:
        phrase = "``FindFileByName`` forces it here on both"
        assert phrase not in _prose(pools.add_and_resolve.__doc__), _returned(
            phrase, _WHERE_ADD_AND_RESOLVE,
            "an edition the runtime does not implement loads under pure-Python",
        )


class TestLintProtoNamedFileNote:
    """``lint --proto`` fails on a named file it cannot match, unless the name is taken.

    0.16.0's entry was headed "``lint --proto`` lints every file it is given,
    or fails". When another input's compile emits a file under the name lint
    predicted for a ``//``-spelled path, lint lints that file instead and exits
    0 (C06-X1, pinned in ``tests/schema/test_audit_u14_compile_pins.py``).
    When that is fixed,
    ``test_a_double_slash_path_currently_lints_another_file`` fails: drop the
    Known-issues entry and the qualification in the same change.
    """

    def test_a_double_slash_path_currently_lints_another_file(self, tmp_path: Path) -> None:
        import shutil

        from tests.schema.test_audit_u14_compile_pins import (
            _double_slash,
            _lint,
            _wrong_file_layout,
        )

        if not _compile_backend_available(shutil.which):
            pytest.skip("needs protoxy or protoc to compile --proto inputs")
        proto_dir, linted, importer = _wrong_file_layout(tmp_path)
        result = _lint([str(importer), _double_slash(linted)], str(proto_dir))
        assert result.exit_code == 0, (
            f"lint now exits {result.exit_code} on the two-input '//' form; the CHANGELOG "
            "still says it lints another file in place of the named one, so rewrite it"
        )

    @pytest.mark.parametrize(
        "phrase",
        [
            "lints that file in place of the named one",
            "`lint --proto` can lint another file in place of one it was given",
        ],
    )
    def test_changelog_states_the_gap(self, phrase: str) -> None:
        assert phrase in _changelog_release(), _missing(phrase, _WHERE_RELEASE)

    def test_changelog_does_not_promise_every_file(self) -> None:
        phrase = "lints every file it is given, or fails"
        assert phrase not in _changelog_release(), _returned(
            phrase, _WHERE_RELEASE, "a '//' path can lint another file in place of the named one"
        )


def _compile_backend_available(which: typing.Callable[[str], str | None]) -> bool:
    """Whether ``lint --proto`` can compile here: protoxy is importable or protoc is on PATH."""
    from protokit import _cli_utils

    return bool(_cli_utils._has_protoxy() or which("protoc"))


def _breaking_sets(tmp_path: Path) -> tuple[Path, Path]:
    """Two sets of ``acme.Thing``: the new one removes field ``b``, which breaks."""
    def thing(fields: tuple[str, ...]) -> _FileBuilder:
        def build(fdp: descriptor_pb2.FileDescriptorProto) -> None:
            fdp.package = "acme"
            message = fdp.message_type.add(name="Thing")
            for number, name in enumerate(fields, start=1):
                message.field.add(
                    name=name, number=number, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL
                )
        return build

    old, new = tmp_path / "old.desc", tmp_path / "new.desc"
    old.write_bytes(_one_file_set(thing(("a", "b"))))
    new.write_bytes(_one_file_set(thing(("a",))))
    return old, new


_EXITS_WHEN_FORMATTED_PACK = (
    "import sys\n"
    "\n"
    "class ExitsWhenFormatted(Exception):\n"
    "    def __str__(self):\n"
    "        sys.exit(0)\n"
    "\n"
    "raise ExitsWhenFormatted()\n"
)


class TestCompatRulePackExitNote:
    """A compat rule pack cannot decide the exit at its three load-time points.

    0.16.0's entry was headed "A rule pack can no longer decide the process
    exit code". The compat loader quoted a pack's exception in its error line,
    so a ``__str__`` that called ``sys.exit(0)`` decided the exit after all
    (C12-C1, closed). lint's ``--rule-pack`` loader still exits 0 when a pack's
    ``RULES`` calls ``sys.exit(0)``, and ``--formatter-module`` has the same
    formatting case, both pinned. The prose names the compat loader and the
    three points, and the two loaders it does not cover.
    """

    def test_an_exception_that_exits_when_formatted_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from click.testing import CliRunner

        from protokit.cli import main

        old, new = _breaking_sets(tmp_path)
        pack = "doc_claims_exits_when_formatted"
        (tmp_path / f"{pack}.py").write_text(_EXITS_WHEN_FORMATTED_PACK, encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        try:
            result = CliRunner().invoke(main, [
                "compat", "check", str(old), str(new), "--type", "acme.Thing",
                "--compat-rule-pack", pack,
            ], catch_exceptions=False)
        finally:
            sys.modules.pop(pack, None)
        assert result.exit_code == 2, (result.exit_code, result.output)
        assert f"failed to import rule pack '{pack}'" in result.stderr

    @pytest.mark.parametrize(
        "phrase",
        [
            "A compat rule pack can no longer decide the exit code while it is imported, "
            "while its `RULES` are read, or while protokit formats its error",
            "This covers `--compat-rule-pack` only",
        ],
    )
    def test_changelog_names_the_loader_and_the_three_points(self, phrase: str) -> None:
        assert phrase in _changelog_release(), _missing(phrase, _WHERE_RELEASE)

    def test_readme_names_the_lint_loader_left_open(self) -> None:
        phrase = (
            "a lint `--rule-pack` whose `RULES` calls `sys.exit(0)` while it is read still exits 0"
        )
        assert phrase in _readme_upgrade_note(5), _missing(phrase, "README upgrade note 5")

    def test_changelog_does_not_cover_every_pack(self) -> None:
        phrase = "A rule pack can no longer decide the process exit code"
        assert phrase not in _changelog_release(), _returned(
            phrase, _WHERE_RELEASE, "lint's --rule-pack and --formatter-module each keep a case"
        )


def _repeated_message_option_field() -> typing.Any:
    """Field ``o.A.y`` carrying ``(o.tag) = 3`` and two ``(o.res)``, a repeated message option."""
    def varint(value: int) -> bytes:
        out = bytearray()
        while True:
            low, value = value & 0x7F, value >> 7
            out.append(low | (0x80 if value else 0))
            if not value:
                return bytes(out)

    def record(number: int, wire_type: int, payload: bytes) -> bytes:
        return varint(number << 3 | wire_type) + payload

    pool = descriptor_pool.DescriptorPool()
    pool.AddSerializedFile(descriptor_pb2.DESCRIPTOR.serialized_pb)
    fdp = descriptor_pb2.FileDescriptorProto(
        name="o.proto", package="o", syntax="proto2",
        dependency=["google/protobuf/descriptor.proto"],
    )
    fdp.message_type.add(name="Res").field.add(
        name="pattern", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL
    )
    options = ".google.protobuf.FieldOptions"
    fdp.extension.add(
        name="tag", number=50001, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL, extendee=options
    )
    fdp.extension.add(
        name="res", number=50003, type=T.TYPE_MESSAGE, label=T.LABEL_REPEATED,
        type_name=".o.Res", extendee=options,
    )
    field = fdp.message_type.add(name="A").field.add(
        name="y", number=2, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL
    )
    res = [record(1, 2, varint(len(p)) + p) for p in (b"p1", b"p2")]
    field.options.MergeFromString(
        b"".join(record(50003, 2, varint(len(r)) + r) for r in res)
        + record(50001, 0, varint(3))
    )
    pool.Add(fdp)
    return pool.FindMessageTypeByName("o.A").fields_by_name["y"]


class TestReleaseBeforeStates:
    """Three before-states 0.16.0 stated wider than 0.15.1 measured (doc-truth N1, N2, N3).

    * N1: 0.15.1's ``get_option_value`` returned ``None`` for a repeated
      message-typed option, so it never raised; its lint rules did, under
      pure-Python, so the error did ship, through ``lint``.
    * N2: a repeated message-typed extension crashed pure-Python only where
      no declared field built its element type's class first.
    * N3: on 0.15.1 under pure-Python a missing import was already refused by
      every command but ``lint``; only a type reference that resolves nowhere
      moved for all of them.

    The before-states live in a released wheel, so the behavioural halves
    measure the after-state the prose states: the option reads on both
    backends, and ``lint`` refuses a missing import on both.
    """

    def test_a_repeated_message_typed_option_reads_beside_another(self) -> None:
        from protokit.options import get_option_value

        field = _repeated_message_option_field()
        assert get_option_value(field, "o.tag") == 3
        res: typing.Any = get_option_value(field, "o.res")
        assert [r.pattern for r in res] == ["p1", "p2"]

    def test_lint_refuses_a_missing_import(self, tmp_path: Path) -> None:
        from click.testing import CliRunner

        from protokit.schema.lint.cli import main as lint_main

        path = tmp_path / "schema.desc"
        path.write_bytes(_unbuildable_set())
        result = CliRunner().invoke(lint_main, ["--no-config", str(path)])
        assert result.exit_code == 2, (result.exit_code, result.output)
        assert "error[lint-missing-imports]" in result.stderr

    @pytest.mark.parametrize(
        "phrase",
        [
            "so it never raised either error",
            "A missing import: only `lint` moves",
            "whose element type the message reaches through no declared field",
        ],
    )
    def test_changelog_states_the_measured_before_states(self, phrase: str) -> None:
        assert phrase in _changelog_release(), _missing(phrase, _WHERE_RELEASE)

    def test_readme_splits_the_two_kinds_of_set(self) -> None:
        phrase = "A set with a missing import was already refused there by every command but `lint`"
        assert phrase in _readme_upgrade_note(9), _missing(phrase, _WHERE_NOTE_9)

    @pytest.mark.parametrize(
        ("prose", "phrase"),
        [
            pytest.param(_changelog_release, "neither error shipped", id="N1"),
            pytest.param(_changelog_release, "on any payload holding such an extension", id="N2"),
            pytest.param(
                lambda: _readme_upgrade_note(9),
                "a set with a missing import or a type reference that resolves nowhere",
                id="N3",
            ),
        ],
    )
    def test_prose_does_not_widen_the_before_state(
        self, prose: typing.Callable[[], str], phrase: str
    ) -> None:
        assert phrase not in prose(), _returned(
            phrase, "README.md or the CHANGELOG's 0.16.0 section",
            "the measured 0.15.1 before-state is narrower",
        )


def _forging_profile_pack() -> typing.Any:
    """A rule pack whose one rule declares a profile name holding a newline."""
    import types

    from protokit.schema.lint.decorator import lint_rule
    from protokit.schema.lint.model import ElementKind, LintSeverity

    @lint_rule(
        rule_id="doc-claims/forge", severity=LintSeverity.WARNING,
        profiles=("strict\nerror[lint-compile-failed]: forged by a profile name",),
        element=ElementKind.MESSAGE, message_template="x",
    )
    def forge(ctx: object) -> None:
        return None

    module = types.ModuleType("doc_claims_forging_profile")
    module.RULES = (forge,)  # type: ignore[attr-defined]
    return module


class TestFindingTextForgeNote:
    """A pack's finding text is flattened; a pack's profile name is not.

    0.16.0's entry was headed "A rule pack's own text can no longer forge a
    line". Its body covers a finding's message, rule id and path. A profile
    name a pack declares still prints raw on the stderr
    ``info[lint-pack-profiles]:`` line, so a newline in it starts an
    ``error[...]`` line of its own (C18-C8). When that is fixed,
    ``test_a_profile_name_currently_starts_a_line_of_its_own`` fails: drop the
    sentence that names the channel in the same change.
    """

    def test_a_profile_name_currently_starts_a_line_of_its_own(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from click.testing import CliRunner

        from protokit.schema.lint.cli import main as lint_main

        module = _forging_profile_pack()
        monkeypatch.setitem(sys.modules, module.__name__, module)
        schema = _set_file(tmp_path, lambda fdp: fdp.message_type.add(name="M"))
        result = CliRunner().invoke(lint_main, [
            "--no-config", "--no-builtin-rules", "--rule-pack", module.__name__,
            "--profile", "nope", str(schema),
        ])
        assert result.exit_code == 2, (result.exit_code, result.output)
        forged = "error[lint-compile-failed]: forged by a profile name"
        assert any(line.startswith(forged) for line in result.stderr.splitlines()), (
            "a pack's profile name no longer starts a line of its own; the CHANGELOG still "
            "names that channel as open, so drop the sentence in the same change"
        )

    @pytest.mark.parametrize(
        "phrase",
        [
            "A rule pack's finding text can no longer forge a line",
            "a profile name the pack declares",
        ],
    )
    def test_changelog_scopes_the_headline(self, phrase: str) -> None:
        assert phrase in _changelog_release(), _missing(phrase, _WHERE_RELEASE)

    def test_changelog_does_not_claim_all_pack_text(self) -> None:
        phrase = "A rule pack's own text can no longer forge a line"
        assert phrase not in _changelog_release(), _returned(
            phrase, _WHERE_RELEASE, "a pack's profile name still prints raw on stderr"
        )


class TestKnownIssuesSection:
    """0.16.0's section has its own ``### Known issues``, between the table and Security.

    0.15.1 has a ``### Known residual`` heading, which a search over the whole
    file would accept; this looks only in the release's own section. The six
    entries the release committed to are each named in it.
    """

    @staticmethod
    def _known_issues() -> str:
        section = _changelog_release_section()
        match = re.search(r"^### Known issues$", section, flags=re.MULTILINE)
        assert match, "the CHANGELOG's 0.16.0 section has no `### Known issues` heading"
        rest = section[match.end():]
        end = re.search(r"^### ", rest, flags=re.MULTILINE)
        return _as_prose(rest[: end.start()] if end else rest)

    def test_the_heading_sits_between_the_upgrade_table_and_security(self) -> None:
        section = _changelog_release_section()
        heading = re.search(r"^### Known issues$", section, flags=re.MULTILINE)
        security = re.search(r"^### Security$", section, flags=re.MULTILINE)
        table = section.find("> | Change | What starts happening |")
        assert heading and security and table >= 0
        assert table < heading.start() < security.start()

    @pytest.mark.parametrize(
        "entry",
        [
            "C06-X1",
            "C05-C1",
            "a `get_option_value` call on it ends the interpreter",
            "On protobuf 4.25 under upb, an editions file",
            "A `lint --rule-pack` whose `RULES` calls `sys.exit(0)`",
            "a closed-enum extension holding a number its enum does not declare",
        ],
    )
    def test_each_committed_entry_is_listed(self, entry: str) -> None:
        assert entry in self._known_issues(), _missing(entry, "The 0.16.0 Known issues section")
