"""``compile_where`` — the ``--where`` minimal predicate compiler (internal).

Compiles a deliberately-restricted expression into a
``Callable[[Message], bool]`` suitable for :func:`protokit.storage.scan`'s
``predicate``. The grammar is intentionally tiny — ``path op scalar`` (``op`` is
``==`` or ``!=``) plus a field-**presence** form (``has:path``). Anything richer
(``and`` / ``or`` / ordering / arithmetic / function calls / chained comparisons)
is **rejected with a clear error** pointing at the Python callable API, never
silently mis-parsed.

Design (per the plan KD-3, verified against the pinned runtime):

- **Compile once, evaluate many.** The path is validated against the descriptor,
  the field kind is checked, and the scalar is coerced — all at compile time, so
  errors are crisp and raised *before* the scan starts. The returned callable is
  pure ``getattr`` traversal plus a compare.
- **``HasField`` is gated on ``has_presence``.** It raises ``ValueError`` on
  proto3 implicit-presence scalars, repeated, and map fields — so the presence
  form refuses those at compile time with an actionable message rather than
  calling ``HasField`` speculatively.
- **Coercion is keyed on ``cpp_type``**, with ``field.type`` disambiguating
  ``TYPE_STRING`` from ``TYPE_BYTES``; enums accept a name **or** a number
  (open-enum numbers included); ``bool`` accepts only ``true`` / ``false`` (never
  ``bool(str)``, which is ``True`` for ``"false"``). A coercion failure is a
  compile-time :class:`WhereError`; a well-typed non-match is a normal ``False``.
- **Traversal through an unset intermediate message returns defaults** (protobuf
  semantics), so ``header.code == 0`` matches a record with no ``header``. This is
  documented, not worked around — ``--where`` cannot express "is-set AND equals".

The richer grammar (``and`` / ``or`` / comparisons) is deferred to CEL — see the
plan; if it ever lands, adopt ``cel-python`` rather than growing this tokenizer.

This module is internal (``--where`` is CLI sugar; the Python API takes arbitrary
callables). Only :class:`WhereError` is re-exported from ``protokit.storage``.
"""

from __future__ import annotations

from collections.abc import Callable

from google.protobuf import descriptor as _d
from google.protobuf.message import Message

from protokit import _descriptors
from protokit.storage.source import StorageError

_FD = _d.FieldDescriptor

_API_HINT = "use the Python callable API (scan(predicate=...)) for richer filters"

# Punctuation that signals a richer expression this grammar will not parse.
_RICHER_TOKENS = ("&&", "||", "<", ">", "(", ")", "+", "*", "/", "%", "^", "~", "=>")
# Word operators (matched with surrounding spaces so identifiers like
# ``android`` or ``order`` are not false positives).
_RICHER_WORDS = ("and", "or", "not")

_PRESENCE_PREFIX = "has:"


class WhereError(StorageError):
    """A ``--where`` expression could not be compiled.

    A typed library exception (a :class:`StorageError`) so a CLI layer catches it
    and translates to an exit code; the message names the supported grammar or
    points at the Python callable API for anything richer.

    Attributes:
        expr: The original expression that failed.
        reason: A human-readable explanation.
    """

    def __init__(self, expr: str, reason: str) -> None:
        self.expr = expr
        self.reason = reason
        super().__init__(f"invalid --where expression {expr!r}: {reason}")


def compile_where(
    expr: str, descriptor: _d.Descriptor
) -> Callable[[Message], bool]:
    """Compile ``expr`` against ``descriptor`` into a ``(message) -> bool`` predicate.

    Args:
        expr: A ``path == scalar`` / ``path != scalar`` comparison, or a
            ``has:path`` presence check.
        descriptor: The ``Descriptor`` of the message the predicate runs against
            (e.g. ``message_class.DESCRIPTOR``).

    Returns:
        A predicate suitable for ``scan(predicate=...)``.

    Raises:
        WhereError: the expression is malformed, names an unknown field, targets
            an unsupported field kind, has an uncoercible literal, or is richer
            than the supported grammar.
    """
    raw = expr.strip()
    if not raw:
        raise WhereError(expr, "empty expression")

    if raw.startswith(_PRESENCE_PREFIX):
        path = raw[len(_PRESENCE_PREFIX) :].strip()
        _reject_richer(path, expr)
        return _compile_presence(path, descriptor, expr)

    _reject_richer(raw, expr)
    return _compile_comparison(raw, descriptor, expr)


# --- richer-grammar rejection ---------------------------------------------


def _outside_quotes(s: str) -> str:
    """Return ``s`` with the contents of quoted spans removed.

    Used so the richer-token detector and the chained-comparison check ignore a
    legitimate string literal like ``"tom and jerry"`` while still catching an
    ``and`` that joins two comparisons.
    """
    out: list[str] = []
    quote: str | None = None
    for ch in s:
        if quote is not None:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        out.append(ch)
    return "".join(out)


def _reject_richer(text: str, expr: str) -> None:
    bare = _outside_quotes(text)
    for tok in _RICHER_TOKENS:
        if tok in bare:
            raise WhereError(expr, f"unsupported operator {tok!r}; {_API_HINT}")
    padded = f" {bare} "
    for word in _RICHER_WORDS:
        if f" {word} " in padded:
            raise WhereError(expr, f"unsupported keyword {word!r}; {_API_HINT}")


# --- comparison form ------------------------------------------------------


def _compile_comparison(
    raw: str, descriptor: _d.Descriptor, expr: str
) -> Callable[[Message], bool]:
    path_str, op, rhs = _split_operator(raw, expr)
    if "==" in _outside_quotes(rhs) or "!=" in _outside_quotes(rhs):
        raise WhereError(expr, f"chained comparison is not supported; {_API_HINT}")
    if not rhs:
        raise WhereError(
            expr, 'missing value after the operator (use "" to match an empty string)'
        )

    fields = _walk_path(path_str, descriptor, expr)
    terminal = fields[-1]
    _reject_uncomparable_terminal(terminal, expr)

    want = _coerce(rhs, terminal, expr)
    getter = _make_getter(fields)
    if op == "==":
        return lambda m: bool(getter(m) == want)
    return lambda m: bool(getter(m) != want)


def _split_operator(raw: str, expr: str) -> tuple[str, str, str]:
    """Split on the FIRST ``==`` / ``!=`` outside quotes -> ``(path, op, rhs)``.

    Quote-aware so a string literal may contain spaces or ``==``.
    """
    quote: str | None = None
    i = 0
    while i < len(raw):
        ch = raw[i]
        if quote is not None:
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            i += 1
            continue
        two = raw[i : i + 2]
        if two in ("==", "!="):
            return raw[:i].strip(), two, raw[i + 2 :].strip()
        i += 1
    raise WhereError(
        expr,
        "expected '==' or '!=' (or 'has:<path>' for a presence check)",
    )


def _reject_uncomparable_terminal(fd: _d.FieldDescriptor, expr: str) -> None:
    # Map before repeated: a map surfaces as a repeated map_entry message.
    if _descriptors.is_map_field(fd):
        raise WhereError(expr, f"cannot compare map field {fd.name!r}; {_API_HINT}")
    if _descriptors.is_repeated(fd):
        raise WhereError(
            expr, f"cannot compare repeated field {fd.name!r}; {_API_HINT}"
        )
    if fd.message_type is not None:
        raise WhereError(
            expr,
            f"cannot compare message field {fd.name!r}; descend to a scalar leaf "
            f"(e.g. {fd.name}.<subfield>) or {_API_HINT}",
        )


# --- presence form --------------------------------------------------------


def _compile_presence(
    path_str: str, descriptor: _d.Descriptor, expr: str
) -> Callable[[Message], bool]:
    fields = _walk_path(path_str, descriptor, expr)
    terminal = fields[-1]
    if not _descriptors.has_presence(terminal):
        raise WhereError(
            expr,
            f"field {terminal.name!r} has no presence (a proto3 implicit-presence "
            f"scalar, repeated, or map field); compare it instead, e.g. "
            f"'{path_str} == <value>'",
        )
    parent_getter = _make_parent_getter(fields)
    name = terminal.name
    return lambda m: bool(parent_getter(m).HasField(name))


# --- shared path walking + value access -----------------------------------


def _walk_path(
    path_str: str, descriptor: _d.Descriptor, expr: str
) -> list[_d.FieldDescriptor]:
    """Validate a dotted path against ``descriptor`` -> the field chain.

    Each non-terminal segment must be a singular message (so it can be descended
    into); an unknown segment lists the available field names.
    """
    if not path_str:
        raise WhereError(expr, "empty field path")
    segments = path_str.split(".")
    fields: list[_d.FieldDescriptor] = []
    current = descriptor
    for idx, seg in enumerate(segments):
        if not seg:
            raise WhereError(expr, f"empty path segment in {path_str!r}")
        if not seg.isidentifier():
            raise WhereError(expr, f"invalid field-path segment {seg!r}")
        field_map = _descriptors.get_field_map(current)
        fd = field_map.get(seg)
        if fd is None:
            available = ", ".join(sorted(field_map)) or "(none)"
            raise WhereError(
                expr,
                f"no field {seg!r} on {current.full_name} (available: {available})",
            )
        fields.append(fd)
        if idx != len(segments) - 1:  # not the terminal -> must be descendable
            if _descriptors.is_repeated(fd) or _descriptors.is_map_field(fd):
                raise WhereError(
                    expr, f"cannot descend into repeated/map field {seg!r}"
                )
            if fd.message_type is None:
                raise WhereError(expr, f"cannot descend into scalar field {seg!r}")
            current = fd.message_type
    return fields


def _make_getter(fields: list[_d.FieldDescriptor]) -> Callable[[Message], object]:
    parents = [f.name for f in fields[:-1]]
    terminal = fields[-1].name

    def getter(message: Message) -> object:
        current: object = message
        for name in parents:
            current = getattr(current, name)
        return getattr(current, terminal)

    return getter


def _make_parent_getter(
    fields: list[_d.FieldDescriptor],
) -> Callable[[Message], Message]:
    parents = [f.name for f in fields[:-1]]

    def getter(message: Message) -> Message:
        current = message
        for name in parents:
            current = getattr(current, name)
        return current

    return getter


# --- scalar coercion ------------------------------------------------------


def _coerce(literal: str, fd: _d.FieldDescriptor, expr: str) -> object:
    cpp = fd.cpp_type
    if cpp in (_FD.CPPTYPE_INT32, _FD.CPPTYPE_INT64):
        return _coerce_int(literal, fd, expr, signed=True)
    if cpp in (_FD.CPPTYPE_UINT32, _FD.CPPTYPE_UINT64):
        return _coerce_int(literal, fd, expr, signed=False)
    if cpp in (_FD.CPPTYPE_DOUBLE, _FD.CPPTYPE_FLOAT):
        try:
            return float(literal)
        except ValueError:
            raise WhereError(
                expr, f"{literal!r} is not a valid number for field {fd.name!r}"
            ) from None
    if cpp == _FD.CPPTYPE_BOOL:
        low = literal.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        raise WhereError(
            expr, f"{literal!r} is not a bool for field {fd.name!r} (use true/false)"
        )
    if cpp == _FD.CPPTYPE_ENUM:
        return _coerce_enum(literal, fd, expr)
    if cpp == _FD.CPPTYPE_STRING:
        value = _parse_string_literal(literal, expr)
        if fd.type == _FD.TYPE_BYTES:
            return value.encode("utf-8")
        return value
    # Should be unreachable: MESSAGE terminals are rejected earlier.
    raise WhereError(expr, f"unsupported field type for field {fd.name!r}")


def _coerce_int(
    literal: str, fd: _d.FieldDescriptor, expr: str, *, signed: bool
) -> int:
    try:
        value = int(literal)
    except ValueError:
        raise WhereError(
            expr, f"{literal!r} is not an integer for field {fd.name!r}"
        ) from None
    if not signed and value < 0:
        raise WhereError(
            expr, f"field {fd.name!r} is unsigned; {literal!r} is negative"
        )
    return value


def _coerce_enum(literal: str, fd: _d.FieldDescriptor, expr: str) -> int:
    # A bare integer compares by number (open-enum numbers, incl. unnamed, OK).
    try:
        return int(literal)
    except ValueError:
        pass
    enum_type = fd.enum_type
    value = enum_type.values_by_name.get(literal)
    if value is None:
        names = ", ".join(v.name for v in enum_type.values)
        raise WhereError(
            expr,
            f"unknown enum value {literal!r} for {enum_type.full_name} "
            f"(valid: {names})",
        )
    # Typed local to satisfy mypy --strict warn_return_any (descriptor
    # attributes are Any because the protobuf stubs are ignored).
    number: int = value.number
    return number


def _parse_string_literal(literal: str, expr: str) -> str:
    if len(literal) >= 2 and literal[0] in "\"'" and literal[-1] == literal[0]:
        return literal[1:-1]
    if literal and literal[0] in "\"'":
        raise WhereError(expr, f"unterminated string literal {literal!r}")
    return literal
