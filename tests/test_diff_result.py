"""Tests for DiffResult filtering and querying."""

from protokit.message.model import (
    ChangeType,
    Difference,
    DiffResult,
    FieldPath,
    Warning,
)


def _diff(path: str, change_type: ChangeType = ChangeType.MODIFIED) -> Difference:
    """Helper to create a Difference with parsed path."""
    return Difference(path=FieldPath.parse(path), change_type=change_type)


def _result(*diffs: Difference, diagnostics: tuple[Warning, ...] = ()) -> DiffResult:
    return DiffResult(differences=diffs, diagnostics=diagnostics)


class TestDiffResultBasics:
    def test_empty_result(self) -> None:
        r = DiffResult(differences=())
        assert not r.has_changes()
        assert len(r) == 0
        assert not r
        assert r.field_paths() == []
        assert r.is_complete

    def test_has_changes(self) -> None:
        r = _result(_diff("user.name"))
        assert r.has_changes()
        assert len(r) == 1
        assert r

    def test_iteration(self) -> None:
        d1 = _diff("a")
        d2 = _diff("b")
        r = _result(d1, d2)
        assert list(r) == [d1, d2]

    def test_field_paths(self) -> None:
        r = _result(_diff("user.name"), _diff("user.age"))
        paths = r.field_paths()
        assert len(paths) == 2
        assert str(paths[0]) == "user.name"
        assert str(paths[1]) == "user.age"


class TestDiffResultFiltering:
    def test_filter_by_path_prefix(self) -> None:
        r = _result(
            _diff("user.name"),
            _diff("user.age"),
            _diff("config.timeout"),
        )
        filtered = r.filter(path="user")
        assert len(filtered) == 2
        assert all(str(d.path).startswith("user") for d in filtered)

    def test_filter_does_not_match_partial_name(self) -> None:
        r = _result(_diff("user.name"), _diff("user2.name"))
        filtered = r.filter(path="user")
        assert len(filtered) == 1
        assert str(filtered.differences[0].path) == "user.name"

    def test_filter_by_change_type(self) -> None:
        r = _result(
            _diff("a", ChangeType.ADDED),
            _diff("b", ChangeType.MODIFIED),
            _diff("c", ChangeType.ADDED),
        )
        filtered = r.filter(change_type=ChangeType.ADDED)
        assert len(filtered) == 2

    def test_filter_combined(self) -> None:
        r = _result(
            _diff("user.name", ChangeType.MODIFIED),
            _diff("user.age", ChangeType.ADDED),
            _diff("config.timeout", ChangeType.MODIFIED),
        )
        filtered = r.filter(path="user", change_type=ChangeType.MODIFIED)
        assert len(filtered) == 1
        assert str(filtered.differences[0].path) == "user.name"

    def test_chained_filters(self) -> None:
        r = _result(
            _diff("user.name", ChangeType.MODIFIED),
            _diff("user.age", ChangeType.ADDED),
            _diff("config.timeout", ChangeType.MODIFIED),
        )
        filtered = r.filter(path="user").filter(change_type=ChangeType.ADDED)
        assert len(filtered) == 1
        assert str(filtered.differences[0].path) == "user.age"

    def test_filter_immutability(self) -> None:
        r = _result(_diff("user.name"), _diff("config.timeout"))
        filtered = r.filter(path="user")
        assert len(r) == 2  # original unchanged
        assert len(filtered) == 1

    def test_filter_exact_match(self) -> None:
        r = _result(_diff("user.name"), _diff("user.name.first"))
        filtered = r.filter(path="user.name", exact=True)
        assert len(filtered) == 1
        assert str(filtered.differences[0].path) == "user.name"

    def test_filter_bracket_without_bracket_matches_any(self) -> None:
        r = _result(
            _diff("items[2].name"),
            _diff("items[id=42].name"),
            _diff("other.field"),
        )
        filtered = r.filter(path="items")
        assert len(filtered) == 2

    def test_filter_bracket_with_bracket_matches_specific(self) -> None:
        r = _result(
            _diff("items[id=42].name"),
            _diff("items[id=99].name"),
        )
        filtered = r.filter(path="items[id=42]")
        assert len(filtered) == 1
        assert str(filtered.differences[0].path) == "items[id=42].name"

    def test_exact_bracketless_does_not_match_bracketed(self) -> None:
        r = _result(_diff("items[2]"))
        filtered = r.filter(path="items", exact=True)
        assert len(filtered) == 0


class TestDiffResultWarnings:
    def test_warnings_propagate(self) -> None:
        w = Warning(path="user.status", message="enum drift")
        r = DiffResult(
            differences=(_diff("user.name"),),
            diagnostics=(w,),
        )
        assert len(r.warnings) == 1

    def test_warning_filtered_by_path(self) -> None:
        r = DiffResult(
            differences=(_diff("user.name"), _diff("config.timeout")),
            diagnostics=(
                Warning(path="user.status", message="enum drift"),
                Warning(path="config.mode", message="type drift"),
                Warning(path=None, message="global warning"),
            ),
        )
        filtered = r.filter(path="user")
        assert len(filtered.warnings) == 2  # user.status + global (None)

    def test_global_warning_always_included(self) -> None:
        r = DiffResult(
            differences=(),
            diagnostics=(Warning(path=None, message="global"),),
        )
        filtered = r.filter(path="nonexistent")
        assert len(filtered.warnings) == 1


class TestDiagnosticLevels:
    """Gap 5: the ``level`` field on Diagnostic splits
    comparison caveats from tool-level failures. Properties
    ``.warnings`` and ``.errors`` filter accordingly, and the
    default level is ``"warning"`` for backward compatibility
    with pre-Gap-5 emission sites.
    """

    def test_default_level_is_warning(self) -> None:
        d = Warning(path="x", message="m")
        assert d.level == "warning"

    def test_errors_property_filters_to_error_level(self) -> None:
        r = DiffResult(
            differences=(),
            diagnostics=(
                Warning(path="a", message="caveat", level="warning"),
                Warning(path="b", message="crash", level="error"),
            ),
        )
        assert len(r.warnings) == 1
        assert r.warnings[0].message == "caveat"
        assert len(r.errors) == 1
        assert r.errors[0].message == "crash"

    def test_warning_alias_is_diagnostic(self) -> None:
        """``Warning`` is kept as a deprecated alias for ``Diagnostic``
        so external callers don't break during migration.
        """
        from protokit.message.model import Diagnostic
        assert Warning is Diagnostic

    def test_truncated_paths(self) -> None:
        tp = FieldPath.parse("deep.nested.path")
        r = DiffResult(differences=(), truncated_paths=(tp,))
        assert not r.is_complete
        assert len(r.truncated_paths) == 1
