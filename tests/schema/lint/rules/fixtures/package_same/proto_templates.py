"""Programmatic ``.proto`` source builders for R7 PACKAGE_SAME_* tests.

Mirrors the inline-fixture-strings approach used by
``tests/schema/lint/rules/options/test_deprecated_replacement.py``,
but emits proto sources programmatically because R7 needs **42**
distinct fixture-shape × rule combinations: 3 base shapes (all-agree
/ mixed-value / mixed-presence) × 7 option attrs × 2 modes (string
+ boolean) = ~42 source files, plus 5 edge-case shapes. Committing
that many near-identical .proto files would dwarf the actual rule
code and obscure the cross-rule symmetry the helpers encode.

Each builder returns a ``dict[filename, source]`` ready to hand to
``tests/schema/lint/rules/conftest._compile`` (or the local
``_run_single`` analog in the test module).

**Option-value rendering.** Boolean ``java_multiple_files`` values
are emitted as proto-source literals ``true`` / ``false`` (lowercase
keywords required by the protoc-grammar). String values are emitted
as ``"<value>"`` with the value already escaped at the proto-source
level — the only escape this module handles is backslash-quote inside
the value, since the proto grammar requires it.

**Cross-fixture invariants.**

- Every fixture uses ``syntax = "proto3";`` (D6b R7 has no proto2
  divergence; the helpers are proto3-only for now).
- File names match the buf v1.69.0 smoke fixtures' shape
  (``a.proto`` / ``b.proto`` / ``c.proto``) so the resulting
  empirical-parity tests align byte-for-byte with the
  ``_buf_smoke/recorded/*.json`` snapshots.
- Packages default to ``smoke.<scenario_slug>`` so multi-package
  test fixtures share no namespace and can be combined into a
  single compile without cross-contamination.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# ---------------------------------------------------------------------------
# Per-attr emit helpers
# ---------------------------------------------------------------------------

# The 7 PACKAGE_SAME_* attrs in canonical order, mirroring
# ``protokit.schema.lint.rules.package_same._PACKAGE_SAME_OPTION_ATTRS``.
# Local copy avoids importing the production module at fixture-build
# time (keeps fixture authoring decoupled from the rule pack's exact
# tuple ordering, so a future re-ordering doesn't shuffle test
# fixtures silently).
STRING_ATTRS: tuple[str, ...] = (
    "go_package",
    "java_package",
    "csharp_namespace",
    "php_namespace",
    "ruby_package",
    "swift_prefix",
)
BOOL_ATTR: str = "java_multiple_files"
ALL_ATTRS: tuple[str, ...] = STRING_ATTRS + (BOOL_ATTR,)


def _option_line(attr: str, value: str | bool) -> str:
    """Render one ``option <attr> = <literal>;`` line.

    String values are wrapped in double quotes; bool values render
    as the lowercase ``true`` / ``false`` keywords required by the
    proto3 grammar.

    **Backslash precondition.** This helper does NOT escape backslashes
    or quotes inside ``value`` — callers must pass a value that is
    already a valid proto3 string-literal body. A naive
    ``options={"php_namespace": "Acme\\Sub"}`` would produce
    ``option php_namespace = "Acme\\Sub";`` in the emitted source,
    where ``\\S`` is not a valid proto3 escape and protoc / protoxy
    will reject the file. The PHP-namespace fixtures intentionally
    use ASCII-only values for this reason; the
    ``TestInnerQuoteByteParity`` regression test handles quote
    escaping inline rather than relying on the builder. The assertion
    below catches the foot-gun loudly at fixture-build time instead
    of letting it surface as a confusing compile failure deep in
    ``_run_single``.
    """
    if attr == BOOL_ATTR:
        assert isinstance(value, bool), (
            f"java_multiple_files requires bool, got {type(value).__name__}"
        )
        literal = "true" if value else "false"
    else:
        assert isinstance(value, str), (
            f"{attr} requires str, got {type(value).__name__}"
        )
        assert "\\" not in value, (
            f"{attr}: ``make_proto`` does not escape backslashes inside "
            f"option-literal bodies; got {value!r}. Use ASCII-only values "
            f"here OR construct the proto source manually with explicit "
            f"proto3 escapes (e.g. ``\\\\\\\\`` for a literal backslash)."
        )
        literal = f'"{value}"'
    return f"option {attr} = {literal};"


# ---------------------------------------------------------------------------
# Single-file builder
# ---------------------------------------------------------------------------


def make_proto(
    *,
    package: str,
    options: Mapping[str, str | bool] | None = None,
) -> str:
    """Build one ``.proto`` source.

    Args:
        package: Value for ``package <X>;`` declaration. Pass an
            empty string to omit the package declaration entirely
            (matches the buf ``empty-package-mixed`` smoke fixture
            shape — ``package "";`` is invalid proto3, so the
            declaration is dropped instead).
        options: Mapping ``attr -> value`` of file-option declarations
            to emit. Omit (or pass ``None``) for a file with no
            file options.

    Returns:
        Multi-line proto source ready to write to ``tmp_path``.

    Files are emitted **without a stub message** — proto3 accepts
    options-only files, and a per-file ``message Stub {}`` would
    silently collide across the 3-file scenarios (every file would
    declare ``<package>.Stub``, triggering a pool symbol collision
    that masks the disagreement detection logic the tests target).
    """
    lines: list[str] = ['syntax = "proto3";']
    if package:
        lines.append(f"package {package};")
    if options:
        for attr, value in options.items():
            lines.append(_option_line(attr, value))
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Three-file scenario builders (sad path / happy path)
# ---------------------------------------------------------------------------


def all_agree(
    attr: str,
    *,
    value: str | bool,
    package: str = "smoke.all_agree",
    file_names: Sequence[str] = ("a.proto", "b.proto", "c.proto"),
) -> dict[str, str]:
    """Three-file package, all declaring ``attr = value`` — silent.

    Mirrors the ``_buf_smoke/all-agree`` shape.
    """
    return {
        fname: make_proto(package=package, options={attr: value})
        for fname in file_names
    }


def mixed_value(
    attr: str,
    *,
    values: Sequence[str | bool],
    package: str = "smoke.mixed_value",
    file_names: Sequence[str] | None = None,
) -> dict[str, str]:
    """N-file package, each file declaring a distinct ``attr = value``.

    Triggers the helper's ``len(declared) >= 2`` arm:
    ``'multiple values "X,Y"'`` payload (alphabetic-by-value sort).

    Args:
        attr: One of the 7 R7 attrs.
        values: One value per file; ``len(values)`` files emitted.
        package: Package declaration shared across the N files.
        file_names: Override file names; defaults to ``a.proto``,
            ``b.proto``, ... matching the smoke-fixture shape.

    Returns:
        Mapping ``filename -> proto source``.
    """
    if file_names is None:
        file_names = tuple(f"{chr(ord('a') + i)}.proto" for i in range(len(values)))
    assert len(file_names) == len(values), (
        "file_names and values must align (one value per file)"
    )
    return {
        fname: make_proto(package=package, options={attr: value})
        for fname, value in zip(file_names, values, strict=True)
    }


def mixed_presence(
    attr: str,
    *,
    declared_value: str | bool,
    declarer: str = "a.proto",
    omitters: Sequence[str] = ("b.proto", "c.proto"),
    package: str = "smoke.mixed_presence",
) -> dict[str, str]:
    """One file declares ``attr``; others omit it.

    Triggers the helper's ``len(declared) == 1 and has_omitter``
    arm: ``'both values "X" and no value'`` payload.

    The declarer file is named ``declarer`` and gets
    ``option <attr> = <declared_value>;``. The ``omitters`` files
    are emitted with NO file options (no ``option`` line for ``attr``
    or any other attr).
    """
    sources: dict[str, str] = {
        declarer: make_proto(package=package, options={attr: declared_value}),
    }
    for omitter in omitters:
        sources[omitter] = make_proto(package=package)
    return sources


# ---------------------------------------------------------------------------
# Edge-case scenario builders
# ---------------------------------------------------------------------------


def single_file_package(
    attr: str,
    *,
    value: str | bool,
    package: str = "smoke.single",
) -> dict[str, str]:
    """Lone file with a declared ``attr`` — silent (helper's
    ``len(per_file) <= 1`` early-return)."""
    return {"a.proto": make_proto(package=package, options={attr: value})}


def empty_package_mixed(
    attr: str,
    *,
    values: Sequence[str | bool],
    file_names: Sequence[str] | None = None,
) -> dict[str, str]:
    """Three no-``package`` files with disagreeing ``attr`` values.

    Mirrors the ``_buf_smoke/empty-package-mixed`` shape.
    Buf-actual: ``package = ""`` is treated as a real namespace;
    findings fire identically to a named-package mixed-value scenario.
    """
    if file_names is None:
        file_names = tuple(f"{chr(ord('a') + i)}.proto" for i in range(len(values)))
    assert len(file_names) == len(values)
    return {
        fname: make_proto(package="", options={attr: value})
        for fname, value in zip(file_names, values, strict=True)
    }


def multi_package(
    *,
    pkg_a_files: dict[str, dict[str, str | bool]],
    pkg_a_name: str = "smoke.alpha",
    pkg_b_files: dict[str, dict[str, str | bool]],
    pkg_b_name: str = "smoke.beta",
) -> dict[str, str]:
    """Two independent packages, each with its own option-value scenario.

    Verifies the helper's per-package isolation: findings scoped to
    one package do not leak to the other.
    """
    sources: dict[str, str] = {}
    for fname, options in pkg_a_files.items():
        sources[fname] = make_proto(package=pkg_a_name, options=options or None)
    for fname, options in pkg_b_files.items():
        sources[fname] = make_proto(package=pkg_b_name, options=options or None)
    return sources


def transitive_import(
    *,
    root_value: str = "github.com/x/Y",
    imported_value: str = "github.com/x/X",
    package: str = "smoke.transitive",
) -> dict[str, str]:
    """Two-file package: root file imports the second.

    Root file ``aa.proto`` is passed to the compile step as the
    only input path; ``b.proto`` lands in the pool as a transitive
    import. Both declare ``go_package`` but the values disagree.

    Per the plan's all-disagreers-fire-but-emit-on-root_files
    semantics, only ``aa.proto`` receives a finding even though
    ``b.proto`` contributed to the disagreement.

    File name ``aa.proto`` is chosen so the basename sort orders
    it AFTER ``b.proto`` — this surfaces engine-emit-ordering
    regressions that would silently pass if both root and import
    sort first.
    """
    return {
        "aa.proto": (
            'syntax = "proto3";\n'
            f"package {package};\n"
            'import "b.proto";\n'
            f'option go_package = "{root_value}";\n'
            "message Stub {}\n"
        ),
        "b.proto": (
            'syntax = "proto3";\n'
            f"package {package};\n"
            f'option go_package = "{imported_value}";\n'
            "message Imported {}\n"
        ),
    }


def reverse_order(
    *,
    package: str = "smoke.reverse_order_go",
) -> dict[str, str]:
    """Three-file package with values ``a=Y, b=X, c=Y``.

    Mirrors ``_buf_smoke/reverse-order-go`` — the sort key must be
    alphabetic-by-VALUE, not file-name-order or first-encountered.
    Buf-actual: payload is ``'multiple values "X,Y"'`` regardless
    of which file declared which value first.
    """
    return {
        "a.proto": make_proto(
            package=package, options={"go_package": "github.com/x/Y"},
        ),
        "b.proto": make_proto(
            package=package, options={"go_package": "github.com/x/X"},
        ),
        "c.proto": make_proto(
            package=package, options={"go_package": "github.com/x/Y"},
        ),
    }


def three_distinct_values(
    attr: str = "go_package",
    *,
    package: str = "smoke.three_distinct",
    values: Sequence[str | bool] = (
        "github.com/x/X",
        "github.com/x/Y",
        "github.com/x/Z",
    ),
) -> dict[str, str]:
    """Three-file package with 3 distinct declared values.

    Verifies that the alphabetic-by-value sort produces
    ``"X,Y,Z"`` (not ``"X,Z,Y"`` or any other permutation).
    """
    return mixed_value(attr, values=values, package=package)
