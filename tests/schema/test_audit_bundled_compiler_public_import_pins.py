"""Strict-xfail pin: the bundled compiler cannot resolve a two-hop ``import public``.

Found 2026-10-11, after the 0.16.0 re-audit, while pinning ``imports/unused``
on a chain of re-exports (``R11-C2 (two hops)`` in
``tests/schema/lint/test_audit_u20_buf_parity_pins.py``). No audit finding ID
and no release owns it yet.

``import public`` is transitive: when ``b.proto`` re-exports ``c.proto`` and
``c.proto`` re-exports ``d.proto``, a file that imports only ``b.proto`` may
use ``d.D``. ``protoc`` compiles that tree. protoxy 0.7.2, the compiler
``protokit[compiler]`` installs, resolves one hop and not two, and raises
``ProtoxyError: name 'acme.d.D' is not defined``. protokit then falls back to
``protoc``:

- with ``protoc`` on ``PATH`` the tree compiles, and the only trace is an
  info diagnostic (``protoxy_fallback``);
- without it the compile fails with ``backend_missing``, "compile backend
  missing: install protokit[compiler] or put protoc on PATH", on a schema that
  is valid and an install that has the bundled compiler.

The pin takes ``protoc`` out of reach and asserts the tree compiles, so only
the bundled compiler can satisfy it. It is narrowed to ``AssertionError``: a
compile that raises is its own exception and turns the pin red.

The whole module needs the bundled compiler and is skipped without it (the
minimal install, and protobuf 4.25, where protoxy cannot be installed).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import pytest

import protokit.schema.compile as compile_module
from tests.schema.lint.rules.conftest import _compile

pytest.importorskip("protoxy")

_UNOWNED = (
    "Unowned (found 2026-10-11, after the 0.16.0 re-audit; no release assigned). "
    "The bundled compiler (protoxy 0.7.2) follows one `import public` hop and not "
    "two. "
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
    reason=_UNOWNED + (
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
