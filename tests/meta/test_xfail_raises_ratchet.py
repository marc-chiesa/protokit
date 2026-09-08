"""Ratchet: every ``pytest.mark.xfail`` marker in ``tests/`` names ``raises=``.

A strict xfail without ``raises=`` accepts *any* exception as the expected
failure, so a pin can stay green while its fixture crashes before the
assertion it exists to guard — the shape U1's ``raises=`` narrowing exposed
across four audit pin files (see
``docs/solutions/best-practices/strict-xfail-pin-without-raises-accepts-any-failure.md``).
This ratchet makes that discipline structural (U22, KTD11's companion):

* every construction of ``pytest.mark.xfail`` — as a decorator, an
  ``add_marker``/``applymarker`` argument, a ``marks=`` value, an assignment
  value, anywhere in the module — names a *specific* ``raises=``: the keyword
  is present and is not ``None``, ``Exception`` or ``BaseException`` (alone
  or inside a tuple), any of which leaves pytest's exception filter off;
* a module-level ``pytestmark`` xfail, a ``pytest.param(..., marks=xfail)``,
  and an imperative ``pytest.xfail(...)`` call are forbidden outright — none
  exists today, so there is no allowlist to maintain and the first one to
  appear is a review conversation, not a silent precedent;
* the literal ``pytest.mark.xfail`` spelling is the only accepted one:
  ``import pytest as ...``, ``from pytest import mark|xfail|param``, and
  ``name = pytest.mark.xfail`` aliases are forbidden, so no spelling of the
  marker can sit where this walk cannot see it.

Markers applied at collection time by a ``conftest.py`` hook (the pure-Python
known-failure inventory, U2) are constructions like any other —
``item.add_marker(pytest.mark.xfail(...))`` is a ``pytest.mark.xfail(...)``
call in source — so the same ``raises=`` check covers them.

The check is an ``ast`` walk over ``tests/**/*.py``; docstrings and comments
that *mention* the marker are not constructions and are ignored.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_ROOT = _REPO_ROOT / "tests"
_LEARNING = (
    "docs/solutions/best-practices/"
    "strict-xfail-pin-without-raises-accepts-any-failure.md"
)
_DISCOVERY_COMMAND = (
    ".venv/bin/python -m pytest <file> --runxfail --tb=line"
)

_XFAIL_MARK = "pytest.mark.xfail"
_IMPERATIVE_XFAIL = "pytest.xfail"
# ``raises=`` values that match every exception, i.e. no filter at all.
_CATCH_ALL_RAISES = frozenset({"None", "Exception", "BaseException"})
# ``from pytest import <name>`` forms that let the marker be spelled without ``pytest.``.
_ALIASABLE_PYTEST_NAMES = frozenset({"mark", "xfail", "param", "*"})
_ALIAS_KIND = "aliased pytest marker import"


@dataclass(frozen=True)
class Offender:
    path: str
    line: int
    kind: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind}"


def _dotted(node: ast.AST) -> str:
    """``ast.unparse`` for the call/attribute head, tolerant of odd nodes."""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - defensive, ast.unparse is total
        return ""


def _is_xfail_marker(node: ast.AST) -> bool:
    """True for the literal ``pytest.mark.xfail`` attribute chain."""
    return isinstance(node, ast.Attribute) and _dotted(node) == _XFAIL_MARK


def _contains_xfail_marker(node: ast.AST) -> bool:
    return any(_is_xfail_marker(child) for child in ast.walk(node))


def _is_catch_all_raises(value: ast.expr) -> bool:
    """True when ``raises=`` names no real filter: ``None``, ``Exception``,
    ``BaseException``, or a tuple/list holding any of them.
    """
    elts = value.elts if isinstance(value, (ast.Tuple, ast.List)) else [value]
    return any(_dotted(elt) in _CATCH_ALL_RAISES for elt in elts)


def _raises_offence(marker: ast.expr) -> str | None:
    """Offender kind for one marker construction, or None when it names a
    specific ``raises=``. A bare ``pytest.mark.xfail`` carries no keywords.
    """
    if not isinstance(marker, ast.Call):
        return "xfail marker without raises="
    for kw in marker.keywords:
        if kw.arg == "raises":
            if _is_catch_all_raises(kw.value):
                return "xfail marker with catch-all raises="
            return None
    return "xfail marker without raises="


@dataclass(frozen=True)
class ScanResult:
    markers_found: int
    offenders: tuple[Offender, ...]


def scan_source(source: str, path: str) -> ScanResult:
    """Scan one module's source. ``path`` is only used to label offenders."""
    tree = ast.parse(source, filename=path)
    found = 0
    offenders: list[Offender] = []
    # A marker heading a call is that call's construction; an attribute that
    # is *not* a call head is a bare ``pytest.mark.xfail`` used as a value.
    call_heads = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}

    def flag(node: ast.AST, kind: str) -> None:
        offenders.append(Offender(path, node.lineno, kind))

    for node in ast.walk(tree):
        # 1. Every construction of the marker, wherever it sits (decorator,
        #    add_marker/applymarker argument, marks= value, assignment value),
        #    must name a specific raises=.
        is_construction = (isinstance(node, ast.Call) and _is_xfail_marker(node.func)) or (
            _is_xfail_marker(node) and id(node) not in call_heads
        )
        if is_construction:
            found += 1
            kind = _raises_offence(node)
            if kind is not None:
                flag(node, kind)

        # 2. ``pytestmark = pytest.mark.xfail(...)`` (or a list holding one) is
        #    forbidden; any other name bound to the marker is an alias that
        #    hides its later uses from this walk.
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            value = node.value
            if value is not None and _contains_xfail_marker(value):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                is_pytestmark = any(
                    isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets
                )
                flag(node, "pytestmark xfail" if is_pytestmark else _ALIAS_KIND)

        # 3. Aliased imports: the literal ``pytest.mark.xfail`` spelling is the
        #    only one this walk can see, so every other spelling is forbidden.
        if isinstance(node, ast.Import) and any(
            a.name == "pytest" and a.asname not in (None, "pytest") for a in node.names
        ):
            flag(node, _ALIAS_KIND)
        if (
            isinstance(node, ast.ImportFrom)
            and node.module == "pytest"
            and any(a.name in _ALIASABLE_PYTEST_NAMES for a in node.names)
        ):
            flag(node, _ALIAS_KIND)

        if isinstance(node, ast.Call):
            head = _dotted(node.func)
            # 4. ``pytest.param(..., marks=pytest.mark.xfail(...))``.
            if head == "pytest.param":
                for kw in node.keywords:
                    if kw.arg == "marks" and _contains_xfail_marker(kw.value):
                        flag(node, "pytest.param(marks=xfail)")
            # 5. Imperative ``pytest.xfail(...)``.
            elif head == _IMPERATIVE_XFAIL:
                flag(node, "imperative pytest.xfail()")

    # ``ast.walk`` order is unspecified; report in source order.
    offenders.sort(key=lambda o: (o.line, o.kind))
    return ScanResult(found, tuple(offenders))


def scan_tree(root: Path = _TESTS_ROOT) -> ScanResult:
    found = 0
    offenders: list[Offender] = []
    for path in sorted(root.rglob("*.py")):
        rel = str(path.relative_to(_REPO_ROOT))
        result = scan_source(path.read_text(encoding="utf-8"), rel)
        found += result.markers_found
        offenders.extend(result.offenders)
    return ScanResult(found, tuple(offenders))


def _format_failure(offenders: tuple[Offender, ...]) -> str:
    lines = "\n".join(f"  {o}" for o in offenders)
    return (
        "xfail markers that can pass for the wrong reason:\n"
        f"{lines}\n"
        "Every pytest.mark.xfail construction (decorator, add_marker/applymarker "
        "argument, marks= value, assignment) must name a specific raises= — not "
        "None, Exception or BaseException; pytestmark xfails, "
        "pytest.param(marks=xfail), imperative pytest.xfail(), and aliased "
        "spellings (import pytest as ..., from pytest import mark/xfail/param, "
        f"name = pytest.mark.xfail) are not allowed. Why: {_LEARNING}. To see "
        f"what each pin actually raises today, run: {_DISCOVERY_COMMAND}"
    )


class TestXfailRaisesRatchet:
    def test_every_xfail_marker_in_tests_names_raises(self) -> None:
        result = scan_tree()
        # A walk that finds no markers at all would pass vacuously; the tree
        # carries the U1 audit pins, so zero found means the walk is broken.
        assert result.markers_found > 0, "ratchet walk found no xfail markers"
        assert not result.offenders, _format_failure(result.offenders)


class TestXfailRaisesRatchetSelfCheck:
    """Injected-violation self-tests (KTD3): each forbidden shape is caught
    with ``file:line`` in the message, and each allowed shape is not.
    """

    def _offenders(self, source: str) -> list[str]:
        return [str(o) for o in scan_source(source, "synthetic.py").offenders]

    # -- rule 1: every construction names a specific raises= ------------------

    def test_strict_marker_without_raises_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.xfail(strict=True, reason='X-1: no raises')\n"
            "def test_a():\n    assert False\n"
        )
        assert self._offenders(src) == ["synthetic.py:2: xfail marker without raises="]

    def test_non_strict_marker_without_raises_is_an_offender(self) -> None:
        src = "import pytest\n@pytest.mark.xfail(reason='soft')\ndef test_a():\n    pass\n"
        assert self._offenders(src) == ["synthetic.py:2: xfail marker without raises="]

    def test_bare_marker_without_call_is_an_offender(self) -> None:
        src = "import pytest\n@pytest.mark.xfail\ndef test_a():\n    pass\n"
        assert self._offenders(src) == ["synthetic.py:2: xfail marker without raises="]

    def test_marker_on_class_is_checked(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.xfail(strict=True)\n"
            "class TestX:\n    def test_a(self):\n        pass\n"
        )
        assert self._offenders(src) == ["synthetic.py:2: xfail marker without raises="]

    def test_applymarker_in_test_body_without_raises_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "def test_a(request):\n"
            "    request.applymarker(pytest.mark.xfail(strict=True, reason='late'))\n"
            "    assert False\n"
        )
        assert self._offenders(src) == ["synthetic.py:3: xfail marker without raises="]

    def test_add_marker_in_test_body_without_raises_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "def test_a(request):\n"
            "    request.node.add_marker(pytest.mark.xfail(strict=True))\n"
            "    assert False\n"
        )
        assert self._offenders(src) == ["synthetic.py:3: xfail marker without raises="]

    def test_raises_none_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.xfail(strict=True, raises=None)\n"
            "def test_a():\n    pass\n"
        )
        assert self._offenders(src) == ["synthetic.py:2: xfail marker with catch-all raises="]

    def test_raises_exception_is_an_offender(self) -> None:
        src = "import pytest\n@pytest.mark.xfail(raises=Exception)\ndef test_a():\n    pass\n"
        assert self._offenders(src) == ["synthetic.py:2: xfail marker with catch-all raises="]

    def test_raises_base_exception_is_an_offender(self) -> None:
        src = "import pytest\n@pytest.mark.xfail(raises=BaseException)\ndef test_a():\n    pass\n"
        assert self._offenders(src) == ["synthetic.py:2: xfail marker with catch-all raises="]

    def test_raises_tuple_holding_catch_all_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.xfail(strict=True, raises=(KeyError, Exception))\n"
            "def test_a():\n    pass\n"
        )
        assert self._offenders(src) == ["synthetic.py:2: xfail marker with catch-all raises="]

    # -- rules 2, 4, 5: forbidden shapes, raises= or not ----------------------

    def test_pytestmark_xfail_is_an_offender(self) -> None:
        src = "import pytest\npytestmark = pytest.mark.xfail(raises=KeyError)\n"
        assert self._offenders(src) == ["synthetic.py:2: pytestmark xfail"]

    def test_pytestmark_list_holding_xfail_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "pytestmark = [pytest.mark.parity, pytest.mark.xfail(raises=KeyError)]\n"
        )
        assert self._offenders(src) == ["synthetic.py:2: pytestmark xfail"]

    def test_annotated_pytestmark_holding_xfail_is_an_offender(self) -> None:
        src = "import pytest\npytestmark: list = [pytest.mark.xfail(raises=KeyError)]\n"
        assert self._offenders(src) == ["synthetic.py:2: pytestmark xfail"]

    def test_param_marks_xfail_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.parametrize('x', [\n"
            "    pytest.param(1, marks=pytest.mark.xfail(raises=ValueError)),\n"
            "])\n"
            "def test_a(x):\n    pass\n"
        )
        assert self._offenders(src) == ["synthetic.py:3: pytest.param(marks=xfail)"]

    def test_param_marks_list_holding_xfail_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.parametrize('x', [\n"
            "    pytest.param(1, marks=[pytest.mark.xfail(raises=ValueError)]),\n"
            "])\n"
            "def test_a(x):\n    pass\n"
        )
        assert self._offenders(src) == ["synthetic.py:3: pytest.param(marks=xfail)"]

    def test_imperative_xfail_is_an_offender(self) -> None:
        src = "import pytest\ndef test_a():\n    pytest.xfail('not today')\n"
        assert self._offenders(src) == ["synthetic.py:3: imperative pytest.xfail()"]

    # -- rule 3: the literal spelling is the only one ------------------------

    def test_import_pytest_as_alias_is_an_offender(self) -> None:
        src = "import pytest as pt\n@pt.mark.xfail(strict=True)\ndef test_a():\n    pass\n"
        assert self._offenders(src) == ["synthetic.py:1: aliased pytest marker import"]

    def test_from_pytest_import_mark_is_an_offender(self) -> None:
        src = "from pytest import mark\n@mark.xfail(strict=True)\ndef test_a():\n    pass\n"
        assert self._offenders(src) == ["synthetic.py:1: aliased pytest marker import"]

    def test_from_pytest_import_xfail_is_an_offender(self) -> None:
        src = "from pytest import xfail\ndef test_a():\n    xfail('not today')\n"
        assert self._offenders(src) == ["synthetic.py:1: aliased pytest marker import"]

    def test_marker_bound_to_a_name_is_an_offender(self) -> None:
        # The binding is the alias; the bare marker it binds is also a
        # construction without raises=, so both fire on the same line.
        src = (
            "import pytest\n"
            "xfail = pytest.mark.xfail\n"
            "@xfail(strict=True)\n"
            "def test_a():\n    pass\n"
        )
        assert self._offenders(src) == [
            "synthetic.py:2: aliased pytest marker import",
            "synthetic.py:2: xfail marker without raises=",
        ]

    # -- allowed shapes -------------------------------------------------------

    def test_marker_with_raises_is_allowed(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.xfail(strict=True, raises=AssertionError, reason='U8-1')\n"
            "def test_a():\n    assert False\n"
        )
        result = scan_source(src, "synthetic.py")
        assert result.offenders == ()
        assert result.markers_found == 1

    def test_marker_with_tuple_of_specific_raises_is_allowed(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.xfail(strict=True, raises=(KeyError, ValueError))\n"
            "def test_a():\n    pass\n"
        )
        result = scan_source(src, "synthetic.py")
        assert result.offenders == ()
        assert result.markers_found == 1

    def test_conftest_style_add_marker_with_raises_is_allowed(self) -> None:
        # U2's known-failure inventory applies markers from a conftest hook;
        # the construction is checked like a decorator and passes with raises=.
        src = (
            "import pytest\n"
            "def pytest_collection_modifyitems(items):\n"
            "    for item in items:\n"
            "        item.add_marker(pytest.mark.xfail(strict=True, raises=KeyError, reason='x'))\n"
        )
        result = scan_source(src, "synthetic.py")
        assert result.offenders == ()
        assert result.markers_found == 1

    def test_other_markers_and_mentions_are_ignored(self) -> None:
        src = (
            "import pytest\n"
            "'''Docstring mentioning @pytest.mark.xfail(strict=True) is prose.'''\n"
            "pytestmark = pytest.mark.parity\n"
            "@pytest.mark.skipif(True, reason='x')\n"
            "def test_a():\n"
            "    pass  # pytest.mark.xfail(strict=True) in a comment is prose too\n"
        )
        result = scan_source(src, "synthetic.py")
        assert result.offenders == ()
        assert result.markers_found == 0

    def test_failure_message_names_learning_and_discovery_command(self) -> None:
        msg = _format_failure((Offender("tests/x.py", 7, "xfail marker without raises="),))
        assert "tests/x.py:7" in msg
        assert _LEARNING in msg
        assert "--runxfail --tb=line" in msg
