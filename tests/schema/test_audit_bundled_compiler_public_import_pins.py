"""Strict-xfail pins: two faults in how protokit uses the bundled compiler.

Both were found on 2026-10-11, after the 0.16.0 re-audit, while pinning
``imports/unused`` on a chain of re-exports (``R11-C2 (two hops)`` in
``tests/schema/lint/test_audit_u20_buf_parity_pins.py``). Neither has an audit
finding ID. Both are owned by U13 (0.18.0), which already changes
``schema/compile.py``.

**A two-hop ``import public`` does not resolve.** ``import public`` is
transitive: when ``b.proto`` re-exports ``c.proto`` and ``c.proto`` re-exports
``d.proto``, a file that imports only ``b.proto`` may use ``d.D``. ``protoc``
compiles that tree. protoxy 0.7.2, the compiler ``protokit[compiler]``
installs, resolves one hop and not two, and raises
``ProtoxyError: name 'acme.d.D' is not defined``. What the user sees depends
on the command:

- ``lint`` and ``storage`` compile through ``compile_protos_to_result``, which
  falls back to ``protoc``. With ``protoc`` on ``PATH`` the tree compiles and
  the only trace is an info diagnostic (``protoxy_fallback``). Without it the
  compile fails with ``backend_missing``.
- ``compat`` and ``diff`` compile through ``compile_proto``, which has no
  fallback: they exit 2 with "protoxy compile failed" whether or not
  ``protoc`` is installed, and accept the same schema when the bundled
  compiler is absent. Installing ``protoc`` does not help.

The first pin takes ``protoc`` out of reach and asserts the tree compiles, so
only the bundled compiler can satisfy it. The pin at the end of the file runs
``compat check`` and ``diff`` with ``protoc`` on ``PATH`` and asserts they
accept the schema, so it flips whether the bundled compiler learns the second
hop or ``compile_proto`` learns to fall back.

**The parser's own message is lost.** When the bundled compiler rejects a
schema and there is no ``protoc`` to fall back to, ``compile_protos_to_result``
keeps an info diagnostic that says only "protoxy parse error" and an error
that says "compile backend missing: install protokit[compiler] or put protoc
on PATH". That holds for a real syntax error in the user's schema too. So
``lint`` and ``storage scan`` tell a user who has the compiler to install it,
and never say what is wrong with the file. ``compat check`` on the same file
prints the parser's message. ``tests/schema/lint/test_compile_protoxy_fallback.py``
locks today's two-diagnostic shape (``test_both_fail_composition_parametrized``)
and is the test the fix must update.

Every pin is narrowed to ``AssertionError``: a compile that raises is its own
exception and turns the pin red. The whole module needs the bundled compiler
and is skipped without it (the minimal install, and protobuf 4.25, where
protoxy cannot be installed).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

import protokit._cli_utils as cli_utils
import protokit.schema.compile as compile_module
from protokit.cli import main
from tests.schema.lint.rules.conftest import _compile

protoxy = pytest.importorskip("protoxy")

_TWO_HOPS_OWNER = (
    "Bundled compiler (two-hop import public): owned by U13 (0.18.0). The bundled "
    "compiler (protoxy 0.7.2) follows one `import public` hop and not two. "
)
_LOST_MESSAGE_OWNER = (
    "Bundled compiler (lost parse error): owned by U13 (0.18.0). "
    "compile_protos_to_result keeps the bundled compiler's exception type and drops "
    "its message. "
)

#: Defines the type the consumers reference.
_DEFINES_D = """\
syntax = "proto3";
package acme.d;
message D { int32 x = 1; }
"""

#: Re-exports ``acme/d/d.proto`` and declares nothing of its own.
_REEXPORTS_D = """\
syntax = "proto3";
package acme.c;
import public "acme/d/d.proto";
"""

#: Re-exports ``acme/c/c.proto``, and so ``acme/d/d.proto`` with it.
_REEXPORTS_C = """\
syntax = "proto3";
package acme.b;
import public "acme/c/c.proto";
"""


def _consumer(imported: str) -> str:
    """``acme/a/a.proto``: imports ``imported`` only and declares an ``acme.d.D`` field."""
    return (
        'syntax = "proto3";\n'
        "package acme.a;\n"
        f'import "{imported}";\n'
        "message A { acme.d.D d = 1; }\n"
    )


#: ``a -> c -(import public)-> d``: the type is one re-export away.
_ONE_HOP = {
    "acme/d/d.proto": _DEFINES_D,
    "acme/c/c.proto": _REEXPORTS_D,
    "acme/a/a.proto": _consumer("acme/c/c.proto"),
}

#: ``a -> b -(import public)-> c -(import public)-> d``: two re-exports away.
_TWO_HOPS = {
    **_ONE_HOP,
    "acme/b/b.proto": _REEXPORTS_C,
    "acme/a/a.proto": _consumer("acme/b/b.proto"),
}


def _categories(result: Any) -> list[str]:
    """The compile result's diagnostic categories, in order."""
    return [diagnostic.category for diagnostic in result.diagnostics]


@pytest.fixture
def no_protoc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Put ``protoc`` out of reach, so the bundled compiler is the only backend."""
    empty = tmp_path / "empty-path"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert shutil.which("protoc") is None


@pytest.mark.usefixtures("no_protoc")
def test_bundled_compiler_resolves_one_public_reexport_control(tmp_path: Path) -> None:
    """Control: one ``import public`` hop compiles with no ``protoc`` and no fallback.

    Same files and the same fixture as the pin, one re-export shorter. It
    shows the bundled compiler runs with ``PATH`` emptied and that the pin's
    failure is specific to the second hop.
    """
    result = _compile(tmp_path / "tree", _ONE_HOP)

    assert _categories(result) == []
    assert "acme/a/a.proto" in result.root_files


def test_protoc_compiles_the_two_hop_chain_control(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Control: the two-hop tree is a valid schema, by ``protoc``'s reading.

    Forces the ``protoc`` backend, so the answer does not come from the
    compiler under test. Skipped where no ``protoc`` is installed.
    """
    if shutil.which("protoc") is None:
        pytest.skip("needs protoc on PATH")
    monkeypatch.setattr(compile_module, "_has_protoxy", lambda: False)

    result = _compile(tmp_path / "tree", _TWO_HOPS)

    assert _categories(result) == []
    assert "acme/a/a.proto" in result.root_files


@pytest.mark.usefixtures("no_protoc")
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=_TWO_HOPS_OWNER + (
        "A file that uses a type two re-exports away fails in the bundled compiler "
        "(ProtoxyError: name 'acme.d.D' is not defined), protokit falls back to "
        "protoc, and with no protoc on PATH the compile ends in backend_missing: "
        "'install protokit[compiler] or put protoc on PATH', on a valid schema with "
        "the bundled compiler installed. Both backends."
    ),
)
def test_bundled_compiler_resolves_two_public_reexports(tmp_path: Path) -> None:
    """A valid schema must compile with the compiler ``protokit[compiler]`` installs.

    User-visible consequence: ``protokit lint --proto`` on a tree that
    ``protoc`` accepts exits 2 telling the user to install a compiler they
    already have, unless ``protoc`` happens to be on ``PATH``.
    """
    result = _compile(tmp_path / "tree", _TWO_HOPS)

    # Today: ['protoxy_fallback', 'backend_missing'] and no root files.
    assert _categories(result) == []
    assert "acme/a/a.proto" in result.root_files


# ---------------------------------------------------------------------------
# The parser's own message is lost when there is no protoc to fall back to
# ---------------------------------------------------------------------------

_BAD_SCHEMAS = pytest.mark.parametrize(
    "source",
    [
        'syntax = "proto3";\nmessage A { int32 x = ; }\n',
        'syntax = "proto3";\nmessage A { Missing m = 1; }\n',
    ],
    ids=["syntax-error", "unknown-type"],
)

#: Commands that compile ``--proto`` through ``compile_protos_to_result``.
_COMMANDS_THAT_FALL_BACK = pytest.mark.parametrize(
    "command", ["lint", "storage-scan"],
)


def _write_bad_schema(tmp_path: Path, source: str) -> Path:
    """Write ``source`` as ``bad.proto`` in its own directory and return the path."""
    tree = tmp_path / "tree"
    tree.mkdir()
    path = tree / "bad.proto"
    path.write_text(source)
    return path


def _bundled_compiler_message(path: Path) -> str:
    """What the bundled compiler itself says is wrong with the schema at ``path``."""
    try:
        protoxy.compile([str(path)], includes=[str(path.parent)])
    except protoxy.ProtoxyError as exc:
        return str(exc)
    pytest.fail(f"the bundled compiler accepted {path.name}: the pins below have no premise")


def _run(command: str, path: Path) -> Result:
    """Run ``protokit lint`` or ``protokit storage scan`` on the schema at ``path``."""
    include = ["-I", str(path.parent)]
    if command == "lint":
        argv = ["lint", "--no-config", "--proto", str(path), *include]
    else:
        data = path.parent / "empty.bin"
        data.write_bytes(b"")
        argv = ["storage", "scan", str(data), "--proto", str(path), *include, "--type", "A"]
    return CliRunner().invoke(main, argv, catch_exceptions=False)


@_BAD_SCHEMAS
def test_bundled_compiler_says_what_is_wrong_control(tmp_path: Path, source: str) -> None:
    """Control: the bundled compiler has a message for each schema, and it is not empty.

    This is the text the pin below asks ``lint`` and ``storage scan`` to show.
    """
    assert _bundled_compiler_message(_write_bad_schema(tmp_path, source)).strip()


@pytest.mark.usefixtures("no_protoc")
@_BAD_SCHEMAS
def test_compat_check_shows_the_parsers_message_control(tmp_path: Path, source: str) -> None:
    """Control: ``compat check`` on the same file, with no ``protoc``, shows the message.

    The outcome the pin asks for already exists one command away: exit 2, the
    parser's own words, and no instruction to install a compiler.
    """
    path = _write_bad_schema(tmp_path, source)
    message = _bundled_compiler_message(path)

    result = CliRunner().invoke(
        main, ["compat", "check", "--proto", str(path), str(path), "--type", "A"],
        catch_exceptions=False,
    )

    assert result.exit_code == 2, result.stdout
    assert message in result.stderr
    assert "compile backend missing" not in result.stderr


@pytest.mark.usefixtures("no_protoc")
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=_LOST_MESSAGE_OWNER + (
        "With no protoc on PATH, lint and storage scan report a schema the bundled "
        "compiler rejected as 'compile backend missing: install protokit[compiler] or "
        "put protoc on PATH' and never show the parser's message, for a real syntax "
        "error in the user's schema too. compat check on the same file prints it. "
        "Both backends."
    ),
)
@_COMMANDS_THAT_FALL_BACK
@_BAD_SCHEMAS
def test_a_rejected_schema_is_reported_in_the_parsers_words(
    tmp_path: Path, command: str, source: str,
) -> None:
    """A schema the compiler rejected must be reported as rejected, with the reason.

    User-visible consequence: someone who installed ``protokit[compiler]`` and
    mistyped a field number is told to install a compiler. Nothing in the
    output names the file's fault, so the advice sends them to fix their
    environment for an error in their schema.

    The pin asks for the bundled compiler's message as it stands. A fix that
    rewords or truncates that message has to change this assertion with it.
    """
    path = _write_bad_schema(tmp_path, source)
    message = _bundled_compiler_message(path)

    result = _run(command, path)

    if result.exit_code != 2:
        pytest.fail(
            f"a rejected schema must exit 2; got {result.exit_code} with "
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    # Today: "compile backend missing: install protokit[compiler] or put protoc on PATH".
    assert message in result.stderr, result.stderr
    assert "compile backend missing" not in result.stderr


# ---------------------------------------------------------------------------
# compat and diff have no fallback: the two-hop schema is refused outright
# ---------------------------------------------------------------------------

_COMMANDS_WITHOUT_A_FALLBACK = pytest.mark.parametrize("command", ["compat-check", "diff"])


def _write_tree(tmp_path: Path, sources: dict[str, str]) -> Path:
    """Write ``sources`` (POSIX-relative name -> text) under a fresh root and return it."""
    root = tmp_path / "tree"
    for name, text in sources.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


def _run_on_consumer(command: str, root: Path) -> Result:
    """``compat check`` of ``acme/a/a.proto`` against itself, or ``diff`` of two empty payloads.

    Either way the right answer is exit 0: a schema is compatible with
    itself, and two empty ``acme.a.A`` payloads are equal. Only the compile
    of ``acme/a/a.proto`` stands between the command and that answer.
    """
    consumer = str(root / "acme/a/a.proto")
    if command == "compat-check":
        argv = ["compat", "check", "--proto", consumer, consumer, "-I", str(root),
                "--type", "acme.a.A"]
    else:
        empty = root / "empty.bin"
        empty.write_bytes(b"")
        argv = ["diff", str(empty), str(empty), "--proto", consumer,
                "--proto-path", str(root), "--message-type", "acme.a.A"]
    return CliRunner().invoke(main, argv, catch_exceptions=False)


@pytest.fixture
def protoc_on_path() -> None:
    """Skip where no ``protoc`` is installed: these tests are about having one."""
    if shutil.which("protoc") is None:
        pytest.skip("needs protoc on PATH")


@_COMMANDS_WITHOUT_A_FALLBACK
def test_one_hop_schema_is_accepted_with_the_bundled_compiler_control(
    tmp_path: Path, command: str,
) -> None:
    """Control: one ``import public`` hop, bundled compiler, and the command exits 0.

    Same commands and the same consumer as the pin, one re-export shorter.
    """
    result = _run_on_consumer(command, _write_tree(tmp_path, _ONE_HOP))

    assert result.exit_code == 0, result.stderr


@pytest.mark.usefixtures("protoc_on_path")
@_COMMANDS_WITHOUT_A_FALLBACK
def test_two_hop_schema_is_accepted_without_the_bundled_compiler_control(
    tmp_path: Path, command: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: with the bundled compiler out of the way, the same command accepts the schema.

    Forces ``compile_proto`` onto its ``protoc`` arm. The schema is valid and
    the command handles it; the bundled compiler is the only variable between
    this and the pin below.
    """
    monkeypatch.setattr(cli_utils, "_has_protoxy", lambda: False)

    result = _run_on_consumer(command, _write_tree(tmp_path, _TWO_HOPS))

    assert result.exit_code == 0, result.stderr


@pytest.mark.usefixtures("protoc_on_path")
@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=_TWO_HOPS_OWNER + (
        "compat and diff compile through compile_proto, which has no fallback to "
        "protoc: with the bundled compiler installed they exit 2 with 'protoxy compile "
        "failed: name ... is not defined' on a valid schema even when protoc is on "
        "PATH, and accept it when the bundled compiler is absent. Both backends."
    ),
)
@_COMMANDS_WITHOUT_A_FALLBACK
def test_two_hop_schema_is_accepted_when_protoc_is_installed(
    tmp_path: Path, command: str,
) -> None:
    """Installing ``protokit[compiler]`` must not make a valid schema unusable.

    User-visible consequence: ``protokit compat check`` and ``protokit diff``
    refuse a schema ``protoc`` compiles, and the user has no way through short
    of uninstalling the bundled compiler. ``lint`` and ``storage`` on the same
    machine compile the same file.

    Either remedy flips this pin: a bundled compiler that resolves the second
    hop, or a ``compile_proto`` that falls back to ``protoc`` as
    ``compile_protos_to_result`` does.
    """
    result = _run_on_consumer(command, _write_tree(tmp_path, _TWO_HOPS))

    # Today: exit 2, "Error: protoxy compile failed: name 'acme.d.D' is not defined".
    assert result.exit_code == 0, result.stderr
