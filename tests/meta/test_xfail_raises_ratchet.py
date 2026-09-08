"""Ratchet: every ``pytest.mark.xfail`` marker in ``tests/`` names ``raises=``.

A strict xfail without ``raises=`` accepts *any* exception as the expected
failure, so a pin can stay green while its fixture crashes before the
assertion it exists to guard — the shape U1's ``raises=`` narrowing exposed
across four audit pin files (see
``docs/solutions/best-practices/strict-xfail-pin-without-raises-accepts-any-failure.md``).
This ratchet makes that discipline structural (U22, KTD11's companion):

* every ``@pytest.mark.xfail(...)`` decorator carries a ``raises=`` keyword,
  whether or not it is ``strict``;
* a module-level ``pytestmark`` xfail, a ``pytest.param(..., marks=xfail)``,
  and an imperative ``pytest.xfail(...)`` call are forbidden outright — none
  exists today, so there is no allowlist to maintain and the first one to
  appear is a review conversation, not a silent precedent.

Markers applied at collection time by a ``conftest.py`` hook (the pure-Python
known-failure inventory, U2) are not source decorators and fall outside this
walk by construction.

The check is an ``ast`` walk over ``tests/**/*.py``; docstrings and comments
that *mention* the marker are not decorators and are ignored.
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
    """True for ``pytest.mark.xfail`` and ``pytest.mark.xfail(...)``."""
    if isinstance(node, ast.Call):
        node = node.func
    return isinstance(node, ast.Attribute) and _dotted(node) == _XFAIL_MARK


def _contains_xfail_marker(node: ast.AST) -> bool:
    return any(_is_xfail_marker(child) for child in ast.walk(node))


def _marker_has_raises(node: ast.AST) -> bool:
    return isinstance(node, ast.Call) and any(
        kw.arg == "raises" for kw in node.keywords
    )


@dataclass(frozen=True)
class ScanResult:
    markers_found: int
    offenders: tuple[Offender, ...]


def scan_source(source: str, path: str) -> ScanResult:
    """Scan one module's source. ``path`` is only used to label offenders."""
    tree = ast.parse(source, filename=path)
    found = 0
    offenders: list[Offender] = []

    for node in ast.walk(tree):
        # 1. Decorators: every xfail marker must carry raises=.
        for dec in getattr(node, "decorator_list", ()):
            if not _is_xfail_marker(dec):
                continue
            found += 1
            if not _marker_has_raises(dec):
                offenders.append(Offender(path, dec.lineno, "xfail marker without raises="))

        # 2. Module-level ``pytestmark = pytest.mark.xfail(...)`` (or a list holding one).
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            is_pytestmark = any(
                isinstance(t, ast.Name) and t.id == "pytestmark" for t in targets
            )
            if is_pytestmark and node.value is not None and _contains_xfail_marker(node.value):
                offenders.append(Offender(path, node.lineno, "pytestmark xfail"))

        if isinstance(node, ast.Call):
            head = _dotted(node.func)
            # 3. ``pytest.param(..., marks=pytest.mark.xfail(...))``.
            if head == "pytest.param":
                for kw in node.keywords:
                    if kw.arg == "marks" and _contains_xfail_marker(kw.value):
                        offenders.append(Offender(path, node.lineno, "pytest.param(marks=xfail)"))
            # 4. Imperative ``pytest.xfail(...)``.
            elif head == _IMPERATIVE_XFAIL:
                offenders.append(Offender(path, node.lineno, "imperative pytest.xfail()"))

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
        f"Every pytest.mark.xfail decorator must name raises=; pytestmark "
        f"xfails, pytest.param(marks=xfail), and imperative pytest.xfail() "
        f"are not allowed. Why: {_LEARNING}. To see what each pin actually "
        f"raises today, run: {_DISCOVERY_COMMAND}"
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

    def test_pytestmark_xfail_is_an_offender(self) -> None:
        src = "import pytest\npytestmark = pytest.mark.xfail(raises=KeyError)\n"
        assert self._offenders(src) == ["synthetic.py:2: pytestmark xfail"]

    def test_pytestmark_list_holding_xfail_is_an_offender(self) -> None:
        src = (
            "import pytest\n"
            "pytestmark = [pytest.mark.parity, pytest.mark.xfail(raises=KeyError)]\n"
        )
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

    def test_imperative_xfail_is_an_offender(self) -> None:
        src = "import pytest\ndef test_a():\n    pytest.xfail('not today')\n"
        assert self._offenders(src) == ["synthetic.py:3: imperative pytest.xfail()"]

    def test_marker_with_raises_is_allowed(self) -> None:
        src = (
            "import pytest\n"
            "@pytest.mark.xfail(strict=True, raises=AssertionError, reason='U8-1')\n"
            "def test_a():\n    assert False\n"
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
            "def test_a(item):\n"
            "    # a conftest hook applies markers at collection time, not here\n"
            "    item.add_marker(pytest.mark.xfail(strict=True, raises=KeyError))\n"
        )
        result = scan_source(src, "synthetic.py")
        assert result.offenders == ()
        assert result.markers_found == 0

    def test_failure_message_names_learning_and_discovery_command(self) -> None:
        msg = _format_failure((Offender("tests/x.py", 7, "xfail marker without raises="),))
        assert "tests/x.py:7" in msg
        assert _LEARNING in msg
        assert "--runxfail --tb=line" in msg
