"""Tests for ``scripts/check_dependency_drift.py``.

The reporter's whole value is that it tells the truth about a ceiling
nobody is looking at, so the cases that matter are the ones where it could
quietly say "fine": a prerelease satisfying a bound, a yanked release
looking like the latest, a lookup failure being mistaken for a clean bill
of health.

Every test injects a fake fetcher. Nothing here touches the network — a
test suite that reached PyPI would be a flake generator and would fail in
the offline sandbox CI sometimes runs in.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "check_dependency_drift.py"


def _load() -> ModuleType:
    """Import the script by path.

    ``scripts/`` is not a package and is not importable by name; the
    sibling reporter's tests take the same approach.
    """
    spec = importlib.util.spec_from_file_location("check_dependency_drift", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


drift = _load()


def _payload(
    versions: dict[str, list[dict[str, Any]]],
    info_version: str | None = None,
) -> dict[str, Any]:
    """Build a minimal PyPI JSON payload."""
    return {"info": {"version": info_version or ""}, "releases": versions}


def _files(upload: str | None = None, *, yanked: bool = False) -> list[dict[str, Any]]:
    entry: dict[str, Any] = {"yanked": yanked}
    if upload:
        entry["upload_time_iso_8601"] = upload
    return [entry]


class TestLoadDeclared:
    def test_reads_base_and_every_optional_group(self) -> None:
        """Extras are included: an extra's ceiling is what its users resolve against."""
        declared = drift.load_declared(_REPO_ROOT / "pyproject.toml")
        names = {d.requirement.name for d in declared}
        origins = {d.origin for d in declared}
        assert "protobuf" in names, "base dependency missing"
        assert "pytest" in names, "dev-extra dependency missing"
        assert "dependencies" in origins
        assert origins - {"dependencies"}, "no optional-dependency group was recorded"

    def test_origin_is_the_group_name(self) -> None:
        """A finding has to say WHERE a bound lives or it cannot be acted on."""
        declared = drift.load_declared(_REPO_ROOT / "pyproject.toml")
        by_name = {d.requirement.name: d.origin for d in declared}
        assert by_name["protobuf"] == "dependencies"


class TestLatestStable:
    def test_picks_newest_non_prerelease(self) -> None:
        latest, _ = drift._latest_stable(
            _payload({"1.0.0": _files(), "2.0.0": _files(), "3.0.0rc1": _files()})
        )
        assert str(latest) == "2.0.0"

    def test_skips_fully_yanked_releases(self) -> None:
        """A yanked release is not something a resolver will install."""
        latest, _ = drift._latest_stable(
            _payload({"1.0.0": _files(), "2.0.0": _files(yanked=True)})
        )
        assert str(latest) == "1.0.0"

    def test_prerelease_only_project_reports_nothing_rather_than_guessing(self) -> None:
        latest, _ = drift._latest_stable(_payload({"1.0.0a1": _files()}))
        assert latest is None

    def test_recovers_upload_time(self) -> None:
        _, released = drift._latest_stable(
            _payload({"1.0.0": _files("2020-01-02T03:04:05.000000Z")})
        )
        assert released is not None
        assert released.year == 2020 and released.tzinfo is not None

    def test_unparseable_version_strings_are_ignored(self) -> None:
        """PyPI carries some genuinely malformed historical versions."""
        latest, _ = drift._latest_stable(_payload({"not-a-version": _files(), "1.2.3": _files()}))
        assert str(latest) == "1.2.3"


class TestInspect:
    def _declared(self, spec: str) -> Any:
        from packaging.requirements import Requirement

        return drift.Declared(Requirement(spec), "dependencies")

    def test_bound_excluding_latest_is_behind(self) -> None:
        finding = drift.inspect(
            self._declared("protobuf>=4.21.0,<6"),
            lambda name: _payload({"5.29.6": _files(), "7.36.2": _files()}),
        )
        assert finding.is_behind()
        assert finding.latest == "7.36.2"

    def test_bound_admitting_latest_is_current(self) -> None:
        finding = drift.inspect(
            self._declared("click>=8.0"),
            lambda name: _payload({"8.3.0": _files()}),
        )
        assert finding.admits_latest is True
        assert not finding.is_behind()

    def test_prerelease_does_not_satisfy_a_bound(self) -> None:
        """Without this, a `<6` bound would look satisfied by `6.0.0rc1`."""
        finding = drift.inspect(
            self._declared("pkg<6"),
            lambda name: _payload({"5.0.0": _files(), "6.0.0rc1": _files()}),
        )
        assert finding.latest == "5.0.0"
        assert finding.admits_latest is True

    def test_lookup_failure_is_recorded_not_swallowed(self) -> None:
        """A failed lookup must not be reported as current."""

        def boom(name: str) -> dict[str, Any]:
            raise urllib.error.URLError("no network")

        finding = drift.inspect(self._declared("pkg>=1"), boom)
        assert finding.error is not None
        assert finding.admits_latest is None
        assert not finding.is_behind()

    def test_malformed_json_is_an_error_not_a_crash(self) -> None:
        def bad(name: str) -> dict[str, Any]:
            raise json.JSONDecodeError("bad", "", 0)

        finding = drift.inspect(self._declared("pkg>=1"), bad)
        assert finding.error is not None

    def test_staleness_is_independent_of_the_bound(self) -> None:
        """A package can be perfectly in-range and still be decaying."""
        old = (datetime.now(timezone.utc) - timedelta(days=700)).isoformat()
        finding = drift.inspect(
            self._declared("protoxy>=0.7"),
            lambda name: _payload({"0.7.2": _files(old)}),
        )
        assert finding.admits_latest is True
        assert finding.is_stale(365)
        assert not finding.is_behind()

    def test_fresh_release_is_not_stale(self) -> None:
        recent = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        finding = drift.inspect(
            self._declared("pkg>=1"),
            lambda name: _payload({"1.0.0": _files(recent)}),
        )
        assert not finding.is_stale(365)


class TestReport:
    def _declared(self, spec: str) -> Any:
        from packaging.requirements import Requirement

        return drift.Declared(Requirement(spec), "dependencies")

    def test_classifies_into_disjoint_buckets(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=700)).isoformat()
        new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        payloads = {
            "behind": _payload({"9.0.0": _files(new)}),
            "stale": _payload({"1.0.0": _files(old)}),
            "fine": _payload({"1.0.0": _files(new)}),
        }
        report = drift.build_report(
            [self._declared("behind<2"), self._declared("stale>=1"), self._declared("fine>=1")],
            365,
            lambda name: payloads[name],
        )
        assert [f.name for f in report.behind] == ["behind"]
        assert [f.name for f in report.stale] == ["stale"]
        assert [f.name for f in report.current] == ["fine"]
        assert report.has_drift()

    def test_a_behind_package_is_not_also_counted_stale(self) -> None:
        """Buckets are disjoint, so the totals line cannot double-count."""
        old = (datetime.now(timezone.utc) - timedelta(days=700)).isoformat()
        report = drift.build_report(
            [self._declared("pkg<2")], 365, lambda name: _payload({"9.0.0": _files(old)})
        )
        assert len(report.behind) == 1
        assert report.stale == []

    def test_no_drift_reports_no_drift(self) -> None:
        new = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        report = drift.build_report(
            [self._declared("pkg>=1")], 365, lambda name: _payload({"1.0.0": _files(new)})
        )
        assert not report.has_drift()
        assert "Nothing to do" in drift.render_markdown(report, 365)

    def test_errors_do_not_count_as_drift_but_are_rendered(self) -> None:
        """An unreachable PyPI must not silently read as 'all current'."""

        def boom(name: str) -> dict[str, Any]:
            raise urllib.error.URLError("offline")

        report = drift.build_report([self._declared("pkg>=1")], 365, boom)
        assert not report.has_drift()
        md = drift.render_markdown(report, 365)
        assert "Not checked" in md
        assert "not a clean bill of health" in md

    def test_markdown_names_the_package_and_both_versions(self) -> None:
        report = drift.build_report(
            [self._declared("protobuf>=4.21.0,<6")],
            365,
            lambda name: _payload({"7.36.2": _files()}),
        )
        md = drift.render_markdown(report, 365)
        assert "protobuf" in md and "7.36.2" in md and "<6" in md


def _one_behind(*_args: Any, **_kwargs: Any) -> Any:
    """A report with a single ceiling-drift finding, for main() tests."""
    return drift.Report(behind=[drift.Finding("p", "<1", "dependencies", "2")])


class TestMain:
    def test_offline_mode_makes_no_network_call_and_exits_zero(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def explode(name: str) -> dict[str, Any]:
            raise AssertionError("--offline must not reach the network")

        monkeypatch.setattr(drift, "_fetch", explode)
        assert drift.main(["--offline"]) == 0
        assert "Would check" in capsys.readouterr().out

    def test_exit_status_is_zero_even_with_drift(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Non-blocking is the contract; a gate would get routed around."""
        monkeypatch.setattr(
            drift, "build_report", _one_behind
        )
        assert drift.main([]) == 0
        assert "Ceiling drift" in capsys.readouterr().out

    def test_writes_the_drift_signal_for_the_workflow(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The workflow branches on this, so it is a contract, not a convenience."""
        out = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.setattr(
            drift, "build_report", _one_behind
        )
        drift.main([])
        capsys.readouterr()
        assert out.read_text(encoding="utf-8").strip() == "drift=true"

    def test_signal_is_false_when_clean(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "gh_output"
        monkeypatch.setenv("GITHUB_OUTPUT", str(out))
        monkeypatch.setattr(drift, "build_report", lambda *a, **k: drift.Report())
        drift.main([])
        capsys.readouterr()
        assert out.read_text(encoding="utf-8").strip() == "drift=false"
