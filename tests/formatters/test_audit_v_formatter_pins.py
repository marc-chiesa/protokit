"""Regression pins for deferred formatter audit findings (family V, formatters).

Every ``xfail`` in this module pins a LIVE defect that a later release owns.
Each pin is
``@pytest.mark.xfail(strict=True, raises=...)`` on the test function itself,
with a ``reason`` that begins with the finding ID and names the owning unit and
release. The suite stays green while the defect exists and the pin flips to a
hard failure (XPASS under strict mode) the day the mechanism is fixed, so a fix
cannot land silently and no pin can rot into a permanently-red test.

Each pin asserts the correct outcome, and ``raises=`` names the exception that
was observed with ``--runxfail --tb=line`` under both protobuf backends, so a
pin that dies anywhere else is red rather than "expected". A passing control
sits beside every pin and shares its construction: a red control says the
harness broke, a red pin says the defect moved.

Pinned here:

* **V2** — ``register_formatter`` validates none of its arguments; only the
  pack loader (``load_formatter_pack``) checks ``callable(fn)`` and ``kind:
  FormatterKind``. A direct call registering the int ``42`` or ``None`` as the
  formatter is accepted and ``get_formatter`` hands the non-callable back; a
  ``str`` kind such as ``"DIFF"`` files an entry under a key no
  ``FormatterKind`` lookup can reach. The owner is to make each invalid
  registration raise, and does not name the exception, so the pin accepts the
  pack loader's ``TypeError`` or the registry's own ``FormatterError``; any
  other exception propagates and turns the pin red. A non-``str`` name already
  raises (a raw ``AttributeError`` from ``.lower()``) and is not pinned. Owner:
  U14a (0.19.0).
* **C12-C1, the ``--formatter-module`` twin** — ``load_formatter_packs``
  catches what a formatter pack raises while it is imported or while
  ``FORMATTERS`` is read, then formats that exception into its ``Error:`` line
  outside any guard. The text comes from the pack's own ``__str__``, third-party
  code running after the catch, so a ``__str__`` that calls ``sys.exit(0)``
  becomes the exit code: ``protokit compat check`` on a breaking pair and
  ``protokit diff`` on two different payloads both exit 0 with no output. The
  compat rule-pack loader got exactly this fix (``_pack_exception_text`` in
  ``protokit.schema.cli``); the formatter loader did not. Owner: U14a (0.19.0).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result
from google.protobuf import descriptor_pb2

from protokit.formatters import (
    FormatterContext,
    FormatterError,
    FormatterKind,
    clear_user_formatters,
    get_formatter,
    load_formatter_pack,
    register_formatter,
)
from protokit.message.cli import main as diff_main
from protokit.schema.cli import main as compat_main

T = descriptor_pb2.FieldDescriptorProto


@pytest.fixture(autouse=True)
def _isolate_formatter_registry() -> None:
    """Wipe user formatters around every test: a V2 pin that is accepted leaves junk."""
    clear_user_formatters()
    yield
    clear_user_formatters()


# ---------------------------------------------------------------------------
# V2 — register_formatter enforces none of its invariants
# ---------------------------------------------------------------------------


def _formatter(report: object, ctx: FormatterContext) -> str:
    return f"{report!r}@{ctx.subcommand}"


# Each invalid registration: (name, fn, kind). The pack loader rejects every
# one of them with a TypeError; ``register_formatter`` accepts every one.
_INVALID_REGISTRATIONS = {
    "int-fn": ("v2_int_fn", 42, FormatterKind.DIFF),
    "none-fn": ("v2_none_fn", None, FormatterKind.DIFF),
    "str-kind": ("v2_str_kind", _formatter, "DIFF"),
}


@pytest.mark.parametrize("case", sorted(_INVALID_REGISTRATIONS))
def test_v2_the_pack_loader_rejects_the_same_entry_control(case: str) -> None:
    """Control: the same ``(name, fn, kind)`` through the pack loader raises ``TypeError``.

    The registry already holds the invariant on one route; the pin asks the
    direct route for the same.
    """
    pack = type(sys)("v2_pack_" + case.replace("-", "_"))
    pack.FORMATTERS = [_INVALID_REGISTRATIONS[case]]

    with pytest.raises(TypeError, match="callable|FormatterKind"):
        load_formatter_pack(pack)


def test_v2_a_valid_registration_round_trips_control() -> None:
    """Control: a callable under a ``FormatterKind`` is accepted and found again."""
    register_formatter("v2_valid", _formatter, kind=FormatterKind.DIFF)

    assert get_formatter("V2_VALID", FormatterKind.DIFF) is _formatter


@pytest.mark.parametrize("case", sorted(_INVALID_REGISTRATIONS))
@pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,
    reason="V2: owned by U14a (0.19.0). register_formatter checks neither callable(fn) "
           "nor isinstance(kind, FormatterKind) (only load_formatter_pack does), so "
           "registering the int 42 or None as a formatter, or under the str kind 'DIFF', "
           "is accepted without an exception: get_formatter hands back the "
           "non-callable, and the str kind files an entry no lookup reaches",
)
def test_v2_an_invalid_registration_must_raise(case: str) -> None:
    """Registering a non-callable formatter or a non-``FormatterKind`` kind must raise.

    User-visible consequence: a library caller's mistake surfaces later, as a
    ``TypeError: 'int' object is not callable`` when some CLI run renders a
    report, or never, as an unknown-formatter error for a name the caller
    registered. The exception type is not settled: the pack loader's
    ``TypeError`` and the registry's ``FormatterError`` both count as fixed.
    """
    name, fn, kind = _INVALID_REGISTRATIONS[case]

    # Today: no exception, so pytest.raises fails with "DID NOT RAISE".
    with pytest.raises((TypeError, FormatterError)):
        register_formatter(name, fn, kind=kind)


# ---------------------------------------------------------------------------
# C12-C1, the --formatter-module twin — a pack exception formatted outside a guard
#
# ``load_formatter_packs`` (``protokit._cli_utils``) catches what a pack
# raises, then interpolates the exception into ``error_exit``'s message. The
# interpolation runs the pack's own ``__str__``; one that calls ``sys.exit(0)``
# replaces the exit 2 with exit 0, before the command has compared anything.
# Both commands reach the same loader. None of the packs raises a
# ``RuntimeError``: git mode turns that into exit 2 on its own.
# ---------------------------------------------------------------------------

_PACK_EXCEPTIONS = (
    "import sys\n"
    "\n"
    "class ExitsWhenFormatted(Exception):\n"
    "    def __str__(self):\n"
    "        sys.exit(0)\n"
    "\n"
    "class ExitingCode:\n"
    "    def __str__(self):\n"
    "        sys.exit(0)\n"
    "    def __repr__(self):\n"
    "        sys.exit(0)\n"
    "\n"
    "class Plain(Exception):\n"
    "    pass\n"
)


def _raising_pack(exception: str) -> dict[str, str]:
    """Pack bodies raising ``exception`` from each phase of the load.

    ``import``: from the module body. ``load``: from ``FORMATTERS.__iter__``,
    after the import returned.
    """
    return {
        "import": f"raise {exception}\nFORMATTERS = []\n",
        "load": (
            "class _Formatters:\n"
            "    def __iter__(self):\n"
            f"        raise {exception}\n"
            "FORMATTERS = _Formatters()\n"
        ),
    }


def _schema_set(path: Path, *, with_count: bool) -> Path:
    """A descriptor set declaring proto3 ``acme.Thing { name = 1; [count = 2] }``."""
    file_proto = descriptor_pb2.FileDescriptorProto(
        name="thing.proto", package="acme", syntax="proto3",
    )
    thing = file_proto.message_type.add(name="Thing")
    thing.field.add(name="name", number=1, type=T.TYPE_STRING, label=T.LABEL_OPTIONAL)
    if with_count:
        thing.field.add(name="count", number=2, type=T.TYPE_INT32, label=T.LABEL_OPTIONAL)
    path.write_bytes(descriptor_pb2.FileDescriptorSet(file=[file_proto]).SerializeToString())
    return path


def _compat_check(tmp_path: Path, *pack_args: str) -> Result:
    """``protokit compat check`` on a pair whose new side removes ``count``."""
    old = _schema_set(tmp_path / "old.desc", with_count=True)
    new = _schema_set(tmp_path / "new.desc", with_count=False)
    return CliRunner().invoke(
        compat_main,
        ["check", str(old), str(new), "--type", "acme.Thing", *pack_args],
        catch_exceptions=False,
    )


def _diff(tmp_path: Path, *pack_args: str) -> Result:
    """``protokit diff`` on two ``acme.Thing`` payloads whose ``name`` differs."""
    desc = _schema_set(tmp_path / "schema.desc", with_count=True)
    left, right = tmp_path / "left.bin", tmp_path / "right.bin"
    left.write_bytes(bytes.fromhex("0a0141"))  # name: "A"
    right.write_bytes(bytes.fromhex("0a0142"))  # name: "B"
    return CliRunner().invoke(
        diff_main,
        [str(left), str(right), "--desc", str(desc), "--message-type", "acme.Thing",
         *pack_args],
        catch_exceptions=False,
    )


_COMMANDS: dict[str, Callable[..., Result]] = {"compat-check": _compat_check, "diff": _diff}


def _run_with_pack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, pack_name: str, body: str,
) -> Result:
    """Run ``command`` with ``--formatter-module pack_name``, a real module file on ``sys.path``."""
    pack_dir = tmp_path / "packs"
    pack_dir.mkdir()
    (pack_dir / f"{pack_name}.py").write_text(_PACK_EXCEPTIONS + body)
    monkeypatch.syspath_prepend(str(pack_dir))
    try:
        return _COMMANDS[command](tmp_path, "--formatter-module", pack_name)
    finally:
        sys.modules.pop(pack_name, None)


@pytest.mark.parametrize("command", sorted(_COMMANDS))
def test_formatter_twin_the_pair_differs_without_a_pack_control(
    tmp_path: Path, command: str,
) -> None:
    """Control: without a pack both commands find a difference and exit 1.

    So exit 0 is never the right answer for the runs below.
    """
    result = _COMMANDS[command](tmp_path)

    assert result.exit_code == 1, (
        f"got exit {result.exit_code} with stdout={result.stdout!r} stderr={result.stderr!r}"
    )


@pytest.mark.parametrize("phase", ["import", "load"])
@pytest.mark.parametrize("command", sorted(_COMMANDS))
def test_formatter_twin_an_ordinary_pack_exception_exits_2_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, phase: str,
) -> None:
    """Control: the same pack raising a plain exception exits 2 and names the pack.

    Same module file, same ``sys.path`` entry, same phase; only the exception's
    ``__str__`` differs. This is the outcome the pin asks for.
    """
    pack_name = f"c12_fmt_plain_{phase}"
    body = _raising_pack("Plain('config missing')")[phase]

    result = _run_with_pack(tmp_path, monkeypatch, command, pack_name, body)

    assert result.exit_code == 2, (
        f"got exit {result.exit_code} with stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert (
        f"Error: failed to {phase} formatter pack '{pack_name}': config missing"
        in result.stderr
    )


@pytest.mark.parametrize(
    "exception", ["ExitsWhenFormatted()", "SystemExit(ExitingCode())"],
    ids=["str-exits", "exit-code-repr-exits"],
)
@pytest.mark.parametrize("phase", ["import", "load"])
@pytest.mark.parametrize("command", sorted(_COMMANDS))
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="C12-C1 (--formatter-module twin): owned by U14a (0.19.0). "
           "load_formatter_packs interpolates the pack's exception into its Error: line "
           "outside any guard (its own text, and for SystemExit the repr of its code), "
           "and the pack's own __str__ / __repr__ runs there, so an exception that exits "
           "while it is formatted, raised from the module body or from "
           "FORMATTERS.__iter__, ends compat check on a breaking pair and diff on two "
           "different payloads with exit 0 and no output",
)
def test_formatter_twin_a_pack_exception_cannot_decide_the_exit_while_it_is_formatted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str, phase: str, exception: str,
) -> None:
    """A pack that fails to load must exit 2 naming the pack, whatever its ``__str__`` does.

    User-visible consequence: a CI job that loads a third-party formatter pack
    is told exit 0 (schemas compatible, messages equal) with empty stdout and
    stderr, for a schema change that removes a field or two payloads that
    differ, because the pack failed in a way that also ends the process.
    """
    pack_name = f"c12_fmt_exits_{phase}"
    body = _raising_pack(exception)[phase]

    result = _run_with_pack(tmp_path, monkeypatch, command, pack_name, body)

    # Today: exit 0, stdout and stderr both empty. Anything that is neither that
    # nor the fix (exit 2 naming the pack) is the finding moving: fail red.
    if result.exit_code not in (0, 2) or (
        result.exit_code == 0 and (result.stdout or result.stderr)
    ):
        pytest.fail(f"the formatter-twin finding moved: exit {result.exit_code}, "
                    f"stdout={result.stdout!r} stderr={result.stderr!r}")
    assert result.exit_code == 2, (
        f"got exit {result.exit_code} with stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert f"Error: failed to {phase} formatter pack '{pack_name}'" in result.stderr
