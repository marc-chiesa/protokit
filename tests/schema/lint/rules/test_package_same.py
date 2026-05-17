"""Tests for the D6b Unit 4b R7 PACKAGE_SAME_* rule family.

Covers the 7 rules registered in
:mod:`protokit.schema.lint.rules.package_same` — one per
language-specific ``FileOptions`` attr:

- ``package/same-go-package`` (``go_package``)
- ``package/same-java-package`` (``java_package``)
- ``package/same-csharp-namespace`` (``csharp_namespace``)
- ``package/same-php-namespace`` (``php_namespace``)
- ``package/same-ruby-package`` (``ruby_package``)
- ``package/same-swift-prefix`` (``swift_prefix``)
- ``package/same-java-multiple-files`` (``java_multiple_files``)

All 7 share ``_check_package_option`` + ``_PACKAGE_SAME_OPTION_ATTRS``
and the literal-identical message_template. The all-disagreers-fire
emit-shape comes from buf v1.69.0's empirical behavior, captured in
``tests/schema/lint/rules/fixtures/package_same/_buf_smoke/recorded/*.json``.

Each test class targets one architectural slice:

- :class:`TestPackShape` — RULES tuple shape + import-symbol surface.
- :class:`TestRuleSpecs` — per-rule spec metadata (severity, profile,
  element, source_spec).
- :class:`TestSharedConstants` — ``_PACKAGE_SAME_OPTION_ATTRS`` shape +
  the derived ``_PACKAGE_SAME_OPTION_ATTR_NAMES`` invariants.
- :class:`TestMessageTemplateUniformity` — all 7 templates byte-identical.
- :class:`TestPerRuleHappyAndSadPaths` — per-rule happy / mixed-value /
  mixed-presence integration runs against programmatic fixtures.
- :class:`TestEdgeCases` — single-file silent, all-omit silent,
  multi-package isolation, empty-package, transitive-import,
  3-distinct-values, reverse-order, lowercase bool render.
- :class:`TestInnerQuoteByteParity` — regression for buf's
  ``\\"``-escape of inner quote chars.
- :class:`TestAdversarialSanitization` — newline / control-char /
  U+2028 / U+2029 / multi-KB neutralization.
- :class:`TestPerRuleSeveritiesDemotion` — one method per rule_id × 7
  asserts ``rule_severity_overrides`` flows through to the finding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from protokit.schema.lint.decorator import get_lint_spec
from protokit.schema.lint.engine import LintEngine
from protokit.schema.lint.model import (
    ElementKind,
    LintProfile,
    LintReport,
    LintRuleSpec,
    LintSeverity,
)
from protokit.schema.lint.rules import package_same
from protokit.schema.lint.rules.package_same import (
    _PACKAGE_SAME_OPTION_ATTR_NAMES,
    _PACKAGE_SAME_OPTION_ATTRS,
    RULES,
    _check_package_option,
    check_same_csharp_namespace,
    check_same_go_package,
    check_same_java_multiple_files,
    check_same_java_package,
    check_same_php_namespace,
    check_same_ruby_package,
    check_same_swift_prefix,
)
from tests.schema.lint.rules.conftest import _compile, _run_single
from tests.schema.lint.rules.fixtures.package_same.proto_templates import (
    ALL_ATTRS,
    BOOL_ATTR,
    STRING_ATTRS,
    all_agree,
    empty_package_mixed,
    mixed_presence,
    mixed_value,
    multi_package,
    reverse_order,
    single_file_package,
    three_distinct_values,
    transitive_import,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Maps option_attr -> rule_id. Tests parametrize over this so the
# 7-rule symmetry is enforced at the test level — a new attr added
# to the rule pack must add its row here, otherwise the per-attr
# parametrized tests fail at the lookup.
#
# The original design carried the decorated callable as a second
# tuple element, but no call site ever used the callable (every
# unpack discarded it as ``_fn``). The simplified shape eliminates
# 7 Any-typed dead slots and 6 unused-variable bindings without
# loss of coverage; the in-RULES enforcement is preserved by
# ``test_attr_to_rule_table_matches_production``.
_ATTR_TO_RULE: dict[str, str] = {
    "go_package": "package/same-go-package",
    "java_package": "package/same-java-package",
    "csharp_namespace": "package/same-csharp-namespace",
    "php_namespace": "package/same-php-namespace",
    "ruby_package": "package/same-ruby-package",
    "swift_prefix": "package/same-swift-prefix",
    "java_multiple_files": "package/same-java-multiple-files",
}


# Maps option_attr -> two distinct sample string values for the
# mixed-value scenarios. Mirrors the per-rule smoke fixtures:
# ``mixed-value-go_package`` uses ``github.com/x/{X,Y}``;
# ``mixed-value-java-package`` uses ``com.example.{X,Y}``; etc.
_SAMPLE_STRING_VALUES: dict[str, tuple[str, str]] = {
    "go_package": ("github.com/x/X", "github.com/x/Y"),
    "java_package": ("com.example.X", "com.example.Y"),
    "csharp_namespace": ("Acme.X", "Acme.Y"),
    # PHP namespaces use ``\\`` separators, but the proto-source
    # encoder would have to double-escape to ``\\\\`` for protoxy.
    # Use ASCII-only values here to keep the fixture-builder a thin
    # f-string wrapper; the inner-quote regression test covers the
    # one edge case where escape semantics matter.
    "php_namespace": ("AcmeX", "AcmeY"),
    "ruby_package": ("Acme::X", "Acme::Y"),
    "swift_prefix": ("FX", "FY"),
}


def _findings_sorted_by_file(report: LintReport) -> list[tuple[str, dict[str, Any]]]:
    """Return ``(file, params)`` tuples sorted by the location's ``file``
    attribute.

    Engine walks ``root_files`` by basename, so the natural order is
    already ``a.proto`` -> ``b.proto`` -> ``c.proto``; this helper
    just narrows what tests assert against to keep them readable.
    """
    out: list[tuple[str, dict[str, Any]]] = []
    for f in report.findings:
        out.append((f.location.file, dict(f.params)))
    return sorted(out, key=lambda t: t[0])


# ---------------------------------------------------------------------------
# TestPackShape — RULES tuple + import surface
# ---------------------------------------------------------------------------


class TestPackShape:
    """The pack exposes RULES with all 7 R7 rules registered."""

    def test_rules_tuple_contains_seven_callables(self) -> None:
        assert isinstance(RULES, tuple)
        assert len(RULES) == 7
        for fn in RULES:
            assert hasattr(fn, "_lint_spec"), (
                f"{fn.__name__} missing _lint_spec — not @lint_rule decorated"
            )

    def test_pack_includes_all_seven_rules(self) -> None:
        assert check_same_go_package in RULES
        assert check_same_java_package in RULES
        assert check_same_csharp_namespace in RULES
        assert check_same_php_namespace in RULES
        assert check_same_ruby_package in RULES
        assert check_same_swift_prefix in RULES
        assert check_same_java_multiple_files in RULES

    def test_rules_tuple_order_is_deterministic(self) -> None:
        """Order doesn't carry public semantics but is fixed for diff stability."""
        seen_rule_ids = [get_lint_spec(fn).rule_id for fn in RULES]
        # No duplicates.
        assert len(set(seen_rule_ids)) == 7


# ---------------------------------------------------------------------------
# TestSharedConstants — the triple tuple + str-view derived constant
# ---------------------------------------------------------------------------


class TestSharedConstants:
    def test_seven_triples(self) -> None:
        assert isinstance(_PACKAGE_SAME_OPTION_ATTRS, tuple)
        assert len(_PACKAGE_SAME_OPTION_ATTRS) == 7
        for entry in _PACKAGE_SAME_OPTION_ATTRS:
            assert isinstance(entry, tuple)
            assert len(entry) == 3
            attr, rule_id, buf_alias = entry
            assert isinstance(attr, str)
            assert isinstance(rule_id, str)
            assert isinstance(buf_alias, str)

    def test_attr_names_view_matches_triples(self) -> None:
        derived = tuple(attr for attr, _, _ in _PACKAGE_SAME_OPTION_ATTRS)
        assert derived == _PACKAGE_SAME_OPTION_ATTR_NAMES

    def test_rule_id_namespace(self) -> None:
        for _attr, rule_id, _alias in _PACKAGE_SAME_OPTION_ATTRS:
            assert rule_id.startswith("package/same-"), rule_id

    def test_buf_aliases_uppercase_namespace(self) -> None:
        for _attr, _rule_id, alias in _PACKAGE_SAME_OPTION_ATTRS:
            assert alias.startswith("buf:PACKAGE_SAME_"), alias


# ---------------------------------------------------------------------------
# TestRuleSpecs — per-rule spec metadata
# ---------------------------------------------------------------------------


class TestRuleSpecs:
    """Each rule carries the expected D6b U4b spec metadata."""

    def _spec_for(self, fn: Any) -> LintRuleSpec:
        return get_lint_spec(fn)

    def test_all_rules_severity_error(self) -> None:
        for fn in RULES:
            spec = self._spec_for(fn)
            assert spec.severity is LintSeverity.ERROR, (
                f"{spec.rule_id}: expected ERROR, got {spec.severity}"
            )

    def test_all_rules_profile_recommended_and_default(self) -> None:
        for fn in RULES:
            spec = self._spec_for(fn)
            assert spec.profiles == ("recommended", "default"), (
                f"{spec.rule_id}: unexpected profiles {spec.profiles}"
            )

    def test_all_rules_element_file(self) -> None:
        for fn in RULES:
            spec = self._spec_for(fn)
            assert spec.element is ElementKind.FILE

    def test_source_spec_maps_to_buf_alias(self) -> None:
        rule_id_to_alias = {
            rule_id: alias
            for _attr, rule_id, alias in _PACKAGE_SAME_OPTION_ATTRS
        }
        for fn in RULES:
            spec = self._spec_for(fn)
            assert spec.source_spec == rule_id_to_alias[spec.rule_id], (
                f"{spec.rule_id}: source_spec {spec.source_spec!r} != "
                f"expected alias {rule_id_to_alias[spec.rule_id]!r}"
            )

    def test_go_package_spec(self) -> None:
        spec = self._spec_for(check_same_go_package)
        assert spec.rule_id == "package/same-go-package"
        assert spec.source_spec == "buf:PACKAGE_SAME_GO_PACKAGE"

    def test_java_package_spec(self) -> None:
        spec = self._spec_for(check_same_java_package)
        assert spec.rule_id == "package/same-java-package"
        assert spec.source_spec == "buf:PACKAGE_SAME_JAVA_PACKAGE"

    def test_csharp_namespace_spec(self) -> None:
        spec = self._spec_for(check_same_csharp_namespace)
        assert spec.rule_id == "package/same-csharp-namespace"
        assert spec.source_spec == "buf:PACKAGE_SAME_CSHARP_NAMESPACE"

    def test_php_namespace_spec(self) -> None:
        spec = self._spec_for(check_same_php_namespace)
        assert spec.rule_id == "package/same-php-namespace"
        assert spec.source_spec == "buf:PACKAGE_SAME_PHP_NAMESPACE"

    def test_ruby_package_spec(self) -> None:
        spec = self._spec_for(check_same_ruby_package)
        assert spec.rule_id == "package/same-ruby-package"
        assert spec.source_spec == "buf:PACKAGE_SAME_RUBY_PACKAGE"

    def test_swift_prefix_spec(self) -> None:
        spec = self._spec_for(check_same_swift_prefix)
        assert spec.rule_id == "package/same-swift-prefix"
        assert spec.source_spec == "buf:PACKAGE_SAME_SWIFT_PREFIX"

    def test_java_multiple_files_spec(self) -> None:
        spec = self._spec_for(check_same_java_multiple_files)
        assert spec.rule_id == "package/same-java-multiple-files"
        assert spec.source_spec == "buf:PACKAGE_SAME_JAVA_MULTIPLE_FILES"


# ---------------------------------------------------------------------------
# TestMessageTemplateUniformity
# ---------------------------------------------------------------------------


# Intentionally re-declared (NOT imported from production) so the test acts as
# an independent oracle. If production's ``_MESSAGE_TEMPLATE`` ever drifts,
# ``test_template_byte_identical_across_rules`` fails loudly and forces an
# explicit acknowledgement here — preventing a silent buf-parity regression
# from sliding through a production-side template edit.
_EXPECTED_TEMPLATE = (
    'Files in package "{package}" have {values_payload} '
    'for option "{option_attr}" and all values must be equal.'
)


class TestMessageTemplateUniformity:
    """All 7 rules ship the literal-identical buf v1.69.0 template."""

    def test_template_byte_identical_across_rules(self) -> None:
        templates: set[str] = set()
        for fn in RULES:
            spec = get_lint_spec(fn)
            assert isinstance(spec.message_template, str), (
                f"{spec.rule_id}: multi-kind templates not supported by R7"
            )
            templates.add(spec.message_template)
        assert templates == {_EXPECTED_TEMPLATE}, (
            f"templates diverged across rules: {templates!r}"
        )

    def test_template_contains_three_named_placeholders(self) -> None:
        template = get_lint_spec(check_same_go_package).message_template
        # All three placeholders present in the canonical template.
        assert "{package}" in template
        assert "{values_payload}" in template
        assert "{option_attr}" in template


# ---------------------------------------------------------------------------
# Per-rule happy + sad paths (7-rule × 3-shape grid)
# ---------------------------------------------------------------------------


class TestPerRuleHappyAndSadPaths:
    """Happy-path + mixed-value + mixed-presence per rule.

    Driven via the ``_ATTR_TO_RULE`` table so a new attr added to the
    pack only needs one new row to extend coverage.
    """

    # --- Happy paths (all-agree) ---

    def test_go_package_happy_path(self, tmp_path: Path) -> None:
        self._check_happy_path(tmp_path, "go_package", "github.com/x/X")

    def test_java_package_happy_path(self, tmp_path: Path) -> None:
        self._check_happy_path(tmp_path, "java_package", "com.example.X")

    def test_csharp_namespace_happy_path(self, tmp_path: Path) -> None:
        self._check_happy_path(tmp_path, "csharp_namespace", "Acme.X")

    def test_php_namespace_happy_path(self, tmp_path: Path) -> None:
        # ASCII-only value (no backslash separator) per the
        # _SAMPLE_STRING_VALUES comment — the fixture builder does NOT
        # escape backslashes inside option-literal bodies.
        self._check_happy_path(tmp_path, "php_namespace", "AcmeX")

    def test_ruby_package_happy_path(self, tmp_path: Path) -> None:
        self._check_happy_path(tmp_path, "ruby_package", "Acme::X")

    def test_swift_prefix_happy_path(self, tmp_path: Path) -> None:
        self._check_happy_path(tmp_path, "swift_prefix", "FX")

    def test_java_multiple_files_happy_path(self, tmp_path: Path) -> None:
        self._check_happy_path(tmp_path, "java_multiple_files", True)

    def _check_happy_path(
        self, tmp_path: Path, attr: str, value: str | bool,
    ) -> None:
        rule_id = _ATTR_TO_RULE[attr]
        sources = all_agree(attr, value=value)
        report = _run_single(tmp_path, sources, rule_id, package_same)
        assert len(report.findings) == 0, (
            f"{rule_id} all-agree should be silent, got {report.findings}"
        )

    # --- Mixed-value (per rule × 7) ---

    def test_go_package_mixed_value(self, tmp_path: Path) -> None:
        self._check_mixed_value_string(tmp_path, "go_package")

    def test_java_package_mixed_value(self, tmp_path: Path) -> None:
        self._check_mixed_value_string(tmp_path, "java_package")

    def test_csharp_namespace_mixed_value(self, tmp_path: Path) -> None:
        self._check_mixed_value_string(tmp_path, "csharp_namespace")

    def test_php_namespace_mixed_value(self, tmp_path: Path) -> None:
        self._check_mixed_value_string(tmp_path, "php_namespace")

    def test_ruby_package_mixed_value(self, tmp_path: Path) -> None:
        self._check_mixed_value_string(tmp_path, "ruby_package")

    def test_swift_prefix_mixed_value(self, tmp_path: Path) -> None:
        self._check_mixed_value_string(tmp_path, "swift_prefix")

    def test_java_multiple_files_mixed_value(self, tmp_path: Path) -> None:
        """Boolean attr renders lowercase ``false,true`` in alphabetic order."""
        rule_id = _ATTR_TO_RULE["java_multiple_files"]
        # Three-file package: a=true, b=false, c=true → declared={"true","false"}
        # → payload="multiple values \"false,true\"" (alphabetic, lowercase).
        sources = mixed_value(
            "java_multiple_files", values=(True, False, True),
            package="smoke.bool_mixed",
        )
        report = _run_single(tmp_path, sources, rule_id, package_same)
        # All 3 files fire (all-disagreers-fire).
        assert len(report.findings) == 3
        for fname, params in _findings_sorted_by_file(report):
            assert params["package"] == "smoke.bool_mixed"
            assert params["option_attr"] == "java_multiple_files"
            assert params["values_payload"] == 'multiple values "false,true"', (
                f"{fname}: payload {params['values_payload']!r}"
            )

    def _check_mixed_value_string(self, tmp_path: Path, attr: str) -> None:
        rule_id = _ATTR_TO_RULE[attr]
        value_x, value_y = _SAMPLE_STRING_VALUES[attr]
        # a=X, b=Y, c=X → declared={X,Y} → "multiple values \"X,Y\"".
        sources = mixed_value(
            attr, values=(value_x, value_y, value_x),
            package=f"smoke.mv_{attr}",
        )
        report = _run_single(tmp_path, sources, rule_id, package_same)
        assert len(report.findings) == 3, (
            f"{rule_id} mixed-value should fire on all 3 files, "
            f"got {len(report.findings)}"
        )
        expected_payload = (
            f'multiple values "{value_x},{value_y}"'
        )
        for fname, params in _findings_sorted_by_file(report):
            assert params["package"] == f"smoke.mv_{attr}"
            assert params["option_attr"] == attr
            assert params["values_payload"] == expected_payload, (
                f"{fname}: payload {params['values_payload']!r}"
            )

    # --- Mixed-presence (per rule × 7) ---

    def test_go_package_mixed_presence(self, tmp_path: Path) -> None:
        self._check_mixed_presence_string(tmp_path, "go_package")

    def test_java_package_mixed_presence(self, tmp_path: Path) -> None:
        self._check_mixed_presence_string(tmp_path, "java_package")

    def test_csharp_namespace_mixed_presence(self, tmp_path: Path) -> None:
        self._check_mixed_presence_string(tmp_path, "csharp_namespace")

    def test_php_namespace_mixed_presence(self, tmp_path: Path) -> None:
        self._check_mixed_presence_string(tmp_path, "php_namespace")

    def test_ruby_package_mixed_presence(self, tmp_path: Path) -> None:
        self._check_mixed_presence_string(tmp_path, "ruby_package")

    def test_swift_prefix_mixed_presence(self, tmp_path: Path) -> None:
        self._check_mixed_presence_string(tmp_path, "swift_prefix")

    def test_java_multiple_files_mixed_presence(self, tmp_path: Path) -> None:
        """Bool single-declarer + omitters: payload renders lowercase ``true``."""
        rule_id = _ATTR_TO_RULE["java_multiple_files"]
        sources = mixed_presence(
            "java_multiple_files",
            declared_value=True,
            package="smoke.bool_mp",
        )
        report = _run_single(tmp_path, sources, rule_id, package_same)
        assert len(report.findings) == 3
        for _fname, params in _findings_sorted_by_file(report):
            assert params["package"] == "smoke.bool_mp"
            assert params["option_attr"] == "java_multiple_files"
            assert params["values_payload"] == (
                'both values "true" and no value'
            )

    def _check_mixed_presence_string(self, tmp_path: Path, attr: str) -> None:
        rule_id = _ATTR_TO_RULE[attr]
        value_x, _value_y = _SAMPLE_STRING_VALUES[attr]
        sources = mixed_presence(
            attr,
            declared_value=value_x,
            package=f"smoke.mp_{attr}",
        )
        report = _run_single(tmp_path, sources, rule_id, package_same)
        assert len(report.findings) == 3
        expected_payload = f'both values "{value_x}" and no value'
        for _fname, params in _findings_sorted_by_file(report):
            assert params["package"] == f"smoke.mp_{attr}"
            assert params["option_attr"] == attr
            assert params["values_payload"] == expected_payload


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_single_file_package_silent(self, tmp_path: Path) -> None:
        sources = single_file_package(
            "go_package", value="github.com/x/X",
        )
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 0

    def test_all_omit_silent(self, tmp_path: Path) -> None:
        """Three files in the same package, none declaring the attr."""
        sources = mixed_presence(
            "go_package",
            declared_value="placeholder",
            declarer="_unused.proto",
            omitters=("a.proto", "b.proto", "c.proto"),
            package="smoke.allomit",
        )
        # Drop the declarer file so all 3 actual files are omitters.
        del sources["_unused.proto"]
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 0

    def test_multi_package_isolation(self, tmp_path: Path) -> None:
        """Disagreement in pkg_a does NOT trigger findings in pkg_b."""
        sources = multi_package(
            pkg_a_files={
                "a.proto": {"go_package": "github.com/x/X"},
                "b.proto": {"go_package": "github.com/x/Y"},
            },
            pkg_b_files={
                "c.proto": {"go_package": "github.com/x/Z"},
                "d.proto": {"go_package": "github.com/x/Z"},
            },
        )
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 2
        # Both findings are scoped to pkg_a (smoke.alpha) — pkg_b (beta) is all-agree.
        for _fname, params in _findings_sorted_by_file(report):
            assert params["package"] == "smoke.alpha", (
                f"unexpected package in finding: {params!r}"
            )

    def test_empty_package_mixed_value(self, tmp_path: Path) -> None:
        """Files with no ``package`` declaration are treated as namespace ``""``."""
        sources = empty_package_mixed(
            "go_package",
            values=(
                "github.com/x/X",
                "github.com/x/Y",
                "github.com/x/Z",
            ),
        )
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 3
        for _fname, params in _findings_sorted_by_file(report):
            assert params["package"] == ""
            assert params["values_payload"] == (
                'multiple values "github.com/x/X,'
                'github.com/x/Y,'
                'github.com/x/Z"'
            )

    def test_transitive_import_emits_only_on_root(self, tmp_path: Path) -> None:
        """Transitive imports contribute to disagreement detection but
        findings emit only on root_files."""
        sources = transitive_import(
            root_value="github.com/x/Y",
            imported_value="github.com/x/X",
        )
        # _compile passes BOTH files (whatever's in sources) as input paths,
        # so this technically tests both-files-as-roots. To exercise the
        # transitive case, we compile only the root file and let the
        # importer resolve ``b.proto`` via its --proto-path. Use a
        # bespoke setup instead of the standard _run_single helper.
        sources_root = {"aa.proto": sources["aa.proto"]}
        sources_imported = {"b.proto": sources["b.proto"]}
        # Write the imported file under tmp_path so it's discoverable.
        for fname, text in sources_imported.items():
            (tmp_path / fname).write_text(text)
        result = _compile(tmp_path, sources_root)
        # Confirm the transitive import landed in the pool.
        assert "b.proto" in result.pool_file_names
        assert "aa.proto" in result.root_files
        engine = LintEngine()
        engine.load_rule_pack(package_same)
        profile = LintProfile(
            name="_test_isolation",
            rule_ids=frozenset({"package/same-go-package"}),
            min_severity=LintSeverity.INFO,
        )
        report = engine.run(result, profile=profile)
        # Exactly one finding — on aa.proto only.
        assert len(report.findings) == 1
        assert report.findings[0].location.file == "aa.proto"
        # Payload alphabetic-by-value, so "X,Y" not "Y,X".
        assert report.findings[0].params["values_payload"] == (
            'multiple values "github.com/x/X,github.com/x/Y"'
        )

    def test_three_distinct_values_alphabetic_order(self, tmp_path: Path) -> None:
        """a=X, b=Y, c=Z renders alphabetically as ``X,Y,Z``."""
        sources = three_distinct_values()
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 3
        for _fname, params in _findings_sorted_by_file(report):
            assert params["values_payload"] == (
                'multiple values "github.com/x/X,'
                'github.com/x/Y,github.com/x/Z"'
            )

    def test_reverse_order_alphabetic_sort(self, tmp_path: Path) -> None:
        """Input declaration order a=Y, b=X, c=Y still produces ``X,Y``."""
        sources = reverse_order()
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 3
        for _fname, params in _findings_sorted_by_file(report):
            # Alphabetic-by-VALUE (X then Y) not file-order (Y first encountered).
            assert params["values_payload"] == (
                'multiple values "github.com/x/X,github.com/x/Y"'
            )

    def test_lowercase_bool_render_in_mixed_value(self, tmp_path: Path) -> None:
        """``java_multiple_files`` true/false renders as ``false,true``."""
        sources = mixed_value(
            "java_multiple_files",
            values=(True, False, True),
            package="smoke.lowercase_bool",
        )
        report = _run_single(
            tmp_path,
            sources,
            "package/same-java-multiple-files",
            package_same,
        )
        assert len(report.findings) == 3
        for _fname, params in _findings_sorted_by_file(report):
            # Lowercase, alphabetic (so ``false`` precedes ``true``).
            assert params["values_payload"] == (
                'multiple values "false,true"'
            )

    def test_disagreement_in_one_attr_does_not_fire_other_rules(
        self, tmp_path: Path,
    ) -> None:
        """A package with go_package mismatch but agreeing java_package
        only fires the go_package rule."""
        sources = {
            "a.proto": (
                'syntax = "proto3";\n'
                "package smoke.iso;\n"
                'option go_package = "github.com/x/X";\n'
                'option java_package = "com.example.shared";\n'
            ),
            "b.proto": (
                'syntax = "proto3";\n'
                "package smoke.iso;\n"
                'option go_package = "github.com/x/Y";\n'
                'option java_package = "com.example.shared";\n'
            ),
        }
        # Run the go_package rule — should fire.
        report_go = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report_go.findings) == 2
        # Run the java_package rule — should be silent.
        report_java = _run_single(
            tmp_path, sources, "package/same-java-package", package_same,
        )
        assert len(report_java.findings) == 0


# ---------------------------------------------------------------------------
# Inner-quote byte-parity regression (critical buf v1.69.0 finding)
# ---------------------------------------------------------------------------


class TestInnerQuoteByteParity:
    """Inner ``"`` in option values renders as ``\\"`` in values_payload.

    Empirical: ``_buf_smoke/recorded/mixed-value-with-inner-quote.json``
    shows buf escapes inner quotes literally. Protokit's helper must
    replicate this BEFORE composing ``values_payload`` so the rendered
    message text byte-matches buf.

    Regression gate: a future helper refactor that drops the escape
    would silently break wire-format compatibility for any
    ``option go_package = "X\\"quoted";`` declaration.
    """

    def test_inner_quote_escaped_in_mixed_value(self, tmp_path: Path) -> None:
        # Use proto-source escape syntax so the on-disk value is
        # literally ``X"quoted`` (one quote char in the value).
        sources = {
            "a.proto": (
                'syntax = "proto3";\n'
                "package smoke.iqp;\n"
                'option go_package = "github.com/x/X\\"quoted";\n'
            ),
            "b.proto": (
                'syntax = "proto3";\n'
                "package smoke.iqp;\n"
                'option go_package = "github.com/x/Y\\"quoted";\n'
            ),
            "c.proto": (
                'syntax = "proto3";\n'
                "package smoke.iqp;\n"
                'option go_package = "github.com/x/X\\"quoted";\n'
            ),
        }
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 3
        # The values_payload must contain literal backslash-quote (\")
        # surrounding each value's inner quote — matches
        # _buf_smoke/recorded/mixed-value-with-inner-quote.json.
        for _fname, params in _findings_sorted_by_file(report):
            payload = params["values_payload"]
            assert payload == (
                'multiple values "github.com/x/X\\"quoted,'
                'github.com/x/Y\\"quoted"'
            ), payload


# ---------------------------------------------------------------------------
# Adversarial sanitization
# ---------------------------------------------------------------------------


class TestAdversarialSanitization:
    """Newline / control-char / U+2028 / U+2029 / multi-KB neutralization.

    Threat model: ``module-name-newline-injection-stderr-forge`` —
    attacker-controlled option values that contain line breaks would
    let a malicious .proto file inject fake ``error[lint-CODE]:`` lines
    into protokit's stderr. The pre-walk + helper run every value
    through ``_safe_for_stderr`` so adversarial values render as
    single-line literals.
    """

    def test_newline_in_option_value_neutralized(self, tmp_path: Path) -> None:
        sources = {
            "a.proto": (
                'syntax = "proto3";\n'
                "package smoke.adv;\n"
                # Proto-source string-literal escape: \\n becomes a
                # literal newline byte in the value.
                'option go_package = "github.com/x/A\\nevil";\n'
            ),
            "b.proto": (
                'syntax = "proto3";\n'
                "package smoke.adv;\n"
                'option go_package = "github.com/x/B";\n'
            ),
        }
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 2
        for _fname, params in _findings_sorted_by_file(report):
            payload = params["values_payload"]
            # No newline survives.
            assert "\n" not in payload, (
                f"newline survived sanitization: {payload!r}"
            )
            # The visible content is still present (the A and B markers).
            assert "A" in payload
            assert "B" in payload

    def test_u2028_u2029_in_option_value_neutralized(
        self, tmp_path: Path,
    ) -> None:
        """U+2028 / U+2029 collapsed to spaces by ``_safe_for_stderr``.

        Uses explicit ``\\u2028`` / ``\\u2029`` escape sequences in
        the proto-source values AND the assertions instead of raw
        codepoints embedded in the Python source. Raw codepoints are
        visually indistinguishable from ASCII space in most editors and
        code-review tools, AND can be silently normalized away by
        overzealous editor or git-attribute settings, turning a
        security-critical sentinel into a trivially-passing space
        check. The escape-sequence form is normalization-resistant and
        self-documenting.

        Threat: U+2028 / U+2029 are Unicode line terminators that log
        aggregators (Datadog, Splunk, CloudWatch) split records on,
        even though terminals do not. An attacker-controlled option
        value containing one of these codepoints could inject a fake
        ``error[lint-CODE]:``-prefixed record into a downstream
        aggregator even when the on-disk stderr looks like a single
        line.
        """
        sources = {
            "a.proto": (
                'syntax = "proto3";\n'
                "package smoke.uni;\n"
                'option go_package = "github.com/x/A\u2028split";\n'
            ),
            "b.proto": (
                'syntax = "proto3";\n'
                "package smoke.uni;\n"
                'option go_package = "github.com/x/B\u2029split";\n'
            ),
        }
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 2
        for _fname, params in _findings_sorted_by_file(report):
            payload = params["values_payload"]
            # Explicit escape sequences keep these assertions resistant
            # to git normalization / editor save-on-format hazards.
            assert "\u2028" not in payload, payload
            assert "\u2029" not in payload, payload

    def test_multi_kb_value_truncated(self, tmp_path: Path) -> None:
        """A multi-KB option value triggers the 500-char composed cap."""
        long_value_a = "A" * 5000
        long_value_b = "B" * 5000
        sources = {
            "a.proto": (
                'syntax = "proto3";\n'
                "package smoke.bigval;\n"
                f'option go_package = "{long_value_a}";\n'
            ),
            "b.proto": (
                'syntax = "proto3";\n'
                "package smoke.bigval;\n"
                f'option go_package = "{long_value_b}";\n'
            ),
        }
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 2
        for _fname, params in _findings_sorted_by_file(report):
            # values_payload truncated to 500 chars after composition.
            assert len(params["values_payload"]) <= 500, (
                f"values_payload length {len(params['values_payload'])} "
                f"exceeds 500-char cap"
            )

    def test_truncation_never_strands_backslash_from_split_escape_pair(
        self, tmp_path: Path,
    ) -> None:
        """Regression: 500-char cap must not split a ``\\"`` escape pair.

        Adversarial/correctness convergence (D6b U4b ce:review): with a
        long string value that contains an inner quote, the per-value
        ``_escape_inner_quote`` step expands the quote to ``\\"`` (2
        chars) before composition. A naive ``[:500]`` truncation can
        land precisely between the ``\\`` and its ``"`` partner,
        leaving a stranded backslash at position 499 with no semantic
        meaning. Buf v1.69.0 never produces such an output — the rule
        helper's :func:`_truncate_values_payload` guard strips the
        trailing backslash to preserve escape-pair integrity.

        This fixture is engineered to land the truncation precisely on
        the escape pair: 482 ``A`` chars plus a trailing ``"`` produce
        an escaped value of 484 chars; with the second value of 483
        ``B`` chars, the composed string crosses 500 right at the
        ``\\"`` boundary of the first sorted value (``A`` &lt; ``B``).
        """
        # 482 'A' chars + literal '"' — proto-source escape is \" to
        # embed a literal quote in the option string.
        proto_a = (
            'syntax = "proto3";\n'
            "package smoke.boundary;\n"
            'option go_package = "' + ("A" * 482) + '\\"' + '";\n'
        )
        proto_b = (
            'syntax = "proto3";\n'
            "package smoke.boundary;\n"
            'option go_package = "' + ("B" * 483) + '";\n'
        )
        sources = {"a.proto": proto_a, "b.proto": proto_b}
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 2
        for _fname, params in _findings_sorted_by_file(report):
            payload = params["values_payload"]
            assert len(payload) <= 500, (
                f"payload length {len(payload)} exceeds cap"
            )
            # Most critical assertion: no stranded backslash at the end.
            assert not payload.endswith("\\"), (
                f"payload ends with stranded backslash from split escape "
                f"pair: ...{payload[-20:]!r}"
            )

    def test_control_chars_collapsed(self, tmp_path: Path) -> None:
        """ASCII control characters in option values become spaces."""
        sources = {
            "a.proto": (
                'syntax = "proto3";\n'
                "package smoke.ctrl;\n"
                # \\x07 (BEL) embedded via proto-source octal escape.
                'option go_package = "github.com/x/A\\007beep";\n'
            ),
            "b.proto": (
                'syntax = "proto3";\n'
                "package smoke.ctrl;\n"
                'option go_package = "github.com/x/B";\n'
            ),
        }
        report = _run_single(
            tmp_path, sources, "package/same-go-package", package_same,
        )
        assert len(report.findings) == 2
        for _fname, params in _findings_sorted_by_file(report):
            payload = params["values_payload"]
            assert "\x07" not in payload, payload


# ---------------------------------------------------------------------------
# Per-rule [severities] demotion (one method per rule × 7)
# ---------------------------------------------------------------------------


class TestPerRuleSeveritiesDemotion:
    """``rule_severity_overrides`` flows through to the finding for each rule."""

    def _run_with_demotion(
        self,
        tmp_path: Path,
        attr: str,
        target_severity: LintSeverity,
    ) -> LintReport:
        rule_id = _ATTR_TO_RULE[attr]
        # Construct a mixed-value scenario — string attr uses sample
        # strings, bool attr uses (True, False, True).
        if attr == BOOL_ATTR:
            sources = mixed_value(
                attr, values=(True, False, True),
                package=f"smoke.demote_{attr}",
            )
        else:
            value_x, value_y = _SAMPLE_STRING_VALUES[attr]
            sources = mixed_value(
                attr, values=(value_x, value_y, value_x),
                package=f"smoke.demote_{attr}",
            )
        result = _compile(tmp_path, sources)
        engine = LintEngine()
        engine.load_rule_pack(package_same)
        profile = LintProfile(
            name="_test_demotion",
            rule_ids=frozenset({rule_id}),
            min_severity=LintSeverity.INFO,
            rule_severity_overrides={rule_id: target_severity},
        )
        return engine.run(result, profile=profile)

    def test_go_package_demote_to_info(self, tmp_path: Path) -> None:
        report = self._run_with_demotion(
            tmp_path, "go_package", LintSeverity.INFO,
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.severity is LintSeverity.INFO

    def test_java_package_demote_to_info(self, tmp_path: Path) -> None:
        report = self._run_with_demotion(
            tmp_path, "java_package", LintSeverity.INFO,
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.severity is LintSeverity.INFO

    def test_csharp_namespace_demote_to_warning(self, tmp_path: Path) -> None:
        report = self._run_with_demotion(
            tmp_path, "csharp_namespace", LintSeverity.WARNING,
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.severity is LintSeverity.WARNING

    def test_php_namespace_demote_to_info(self, tmp_path: Path) -> None:
        report = self._run_with_demotion(
            tmp_path, "php_namespace", LintSeverity.INFO,
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.severity is LintSeverity.INFO

    def test_ruby_package_demote_to_warning(self, tmp_path: Path) -> None:
        report = self._run_with_demotion(
            tmp_path, "ruby_package", LintSeverity.WARNING,
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.severity is LintSeverity.WARNING

    def test_swift_prefix_demote_to_info(self, tmp_path: Path) -> None:
        report = self._run_with_demotion(
            tmp_path, "swift_prefix", LintSeverity.INFO,
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.severity is LintSeverity.INFO

    def test_java_multiple_files_demote_to_info(self, tmp_path: Path) -> None:
        report = self._run_with_demotion(
            tmp_path, "java_multiple_files", LintSeverity.INFO,
        )
        assert len(report.findings) == 3
        for f in report.findings:
            assert f.severity is LintSeverity.INFO


# ---------------------------------------------------------------------------
# Helper unit tests (synthetic ctx — no engine needed)
# ---------------------------------------------------------------------------


class _FakeFile:
    """Minimal stand-in for ``FileDescriptor`` exposing only ``package``
    + ``name``."""

    def __init__(self, package: str, name: str = "synthetic.proto") -> None:
        self.package = package
        self.name = name


class _FakeCtx:
    """Synthetic ``FileLintContext``-like object for direct helper testing.

    Captures emitted findings into a list rather than dispatching to
    the engine — lets the helper's per-arm decision logic be exercised
    in isolation from the full ``LintEngine.run`` pipeline.
    """

    def __init__(
        self,
        package_options: dict[str, dict[str, dict[str, str | None]]] | None,
        file_package: str,
    ) -> None:
        self.package_options = package_options
        self.file = _FakeFile(package=file_package)
        self.emitted: list[dict[str, Any]] = []

    def emit(
        self, *, violation_kind: str, params: dict[str, Any] | None = None,
    ) -> None:
        self.emitted.append(
            {"violation_kind": violation_kind, "params": params or {}},
        )


class TestCheckPackageOptionHelper:
    """Direct unit tests on ``_check_package_option``."""

    def test_none_package_options_silent(self) -> None:
        ctx = _FakeCtx(None, "anything")
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert ctx.emitted == []

    def test_missing_package_silent(self) -> None:
        ctx = _FakeCtx({}, "smoke.absent")
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert ctx.emitted == []

    def test_missing_attr_silent(self) -> None:
        ctx = _FakeCtx(
            {"smoke.x": {"java_package": {"a.proto": "X", "b.proto": "X"}}},
            "smoke.x",
        )
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert ctx.emitted == []

    def test_single_file_package_silent(self) -> None:
        ctx = _FakeCtx(
            {"smoke.x": {"go_package": {"a.proto": "X"}}},
            "smoke.x",
        )
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert ctx.emitted == []

    def test_all_omit_silent(self) -> None:
        ctx = _FakeCtx(
            {"smoke.x": {"go_package": {"a.proto": None, "b.proto": None}}},
            "smoke.x",
        )
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert ctx.emitted == []

    def test_all_agree_silent(self) -> None:
        ctx = _FakeCtx(
            {"smoke.x": {"go_package": {"a.proto": "X", "b.proto": "X"}}},
            "smoke.x",
        )
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert ctx.emitted == []

    def test_mixed_value_fires_alphabetic(self) -> None:
        ctx = _FakeCtx(
            {
                "smoke.x": {
                    "go_package": {
                        "a.proto": "Y",
                        "b.proto": "X",
                        "c.proto": "Y",
                    },
                },
            },
            "smoke.x",
        )
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert len(ctx.emitted) == 1
        params = ctx.emitted[0]["params"]
        assert params["values_payload"] == 'multiple values "X,Y"'
        assert params["package"] == "smoke.x"
        assert params["option_attr"] == "go_package"

    def test_mixed_presence_fires(self) -> None:
        ctx = _FakeCtx(
            {
                "smoke.x": {
                    "go_package": {
                        "a.proto": "X",
                        "b.proto": None,
                        "c.proto": None,
                    },
                },
            },
            "smoke.x",
        )
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert len(ctx.emitted) == 1
        assert ctx.emitted[0]["params"]["values_payload"] == (
            'both values "X" and no value'
        )

    def test_inner_quote_escape(self) -> None:
        ctx = _FakeCtx(
            {
                "smoke.x": {
                    "go_package": {
                        "a.proto": 'X"q',
                        "b.proto": 'Y"q',
                    },
                },
            },
            "smoke.x",
        )
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert len(ctx.emitted) == 1
        # Inner " escaped to \" before composition.
        assert ctx.emitted[0]["params"]["values_payload"] == (
            'multiple values "X\\"q,Y\\"q"'
        )

    def test_violation_kind_matches_rule_id(self) -> None:
        ctx = _FakeCtx(
            {
                "smoke.x": {
                    "go_package": {
                        "a.proto": "X",
                        "b.proto": "Y",
                    },
                },
            },
            "smoke.x",
        )
        _check_package_option(ctx, "go_package", "package/same-go-package")
        assert ctx.emitted[0]["violation_kind"] == "package/same-go-package"


# ---------------------------------------------------------------------------
# Constants sanity (table-driven cross-check vs production triple)
# ---------------------------------------------------------------------------


def test_all_attrs_helper_table_matches_production() -> None:
    """``STRING_ATTRS`` + ``BOOL_ATTR`` cover every production attr."""
    fixture_attrs = set(STRING_ATTRS) | {BOOL_ATTR}
    production_attrs = set(_PACKAGE_SAME_OPTION_ATTR_NAMES)
    assert fixture_attrs == production_attrs, (
        f"fixture coverage drifted from production: "
        f"missing {production_attrs - fixture_attrs}, "
        f"extra {fixture_attrs - production_attrs}"
    )


def test_attr_to_rule_table_matches_production() -> None:
    """``_ATTR_TO_RULE`` covers every production rule."""
    table_rule_ids = set(_ATTR_TO_RULE.values())
    production_rule_ids = {get_lint_spec(fn).rule_id for fn in RULES}
    assert table_rule_ids == production_rule_ids
    assert set(_ATTR_TO_RULE.keys()) == set(_PACKAGE_SAME_OPTION_ATTR_NAMES)


def test_all_attrs_constant_matches_production() -> None:
    assert set(ALL_ATTRS) == set(_PACKAGE_SAME_OPTION_ATTR_NAMES)
