#!/usr/bin/env python3
"""Dependency-drift reporter for the declared dependency ceilings.

protokit builds on its dependencies, so a dependency's supported surface
defines protokit's — not the reverse. A declared upper bound that excludes
the current release silently stops being a safety rail and becomes an
install barrier: a user on a modern runtime cannot install protokit at all,
and the gap widens with every upstream release rather than narrowing.

This script surfaces two distinct drifts, because they call for opposite
responses:

**Ceiling drift** — the specifier in ``pyproject.toml`` does not admit the
latest release on PyPI. ``protobuf>=4.21.0,<6`` against an upstream that
shipped 6.x and 7.x is the motivating case. The response is to re-test
against the new release and lift the bound.

**Upstream staleness** — the package itself has not published in a long
time. No ceiling is drifting, but the dependency is decaying: it will pin
*protokit* to whatever it was last built against. A dependency that stops
releasing is a future ceiling, which is exactly how an unmaintained
compiler backend can hold a runtime pin two major versions back.

The script reports; it never edits ``pyproject.toml`` and never fails the
build. Deciding whether a bound is deliberate (a known incompatibility) or
merely stale is a human judgement it does not make — the same contract
``scripts/check_docs_test_refs.py`` keeps.

Usage::

    python scripts/check_dependency_drift.py [--stale-days N] [--offline]

Output goes to stdout and, when ``$GITHUB_STEP_SUMMARY`` is set, is
appended there as Markdown. When ``$GITHUB_OUTPUT`` is set, ``drift=true``
or ``drift=false`` is written so a workflow can branch without parsing
prose. The exit status is always 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised only on the 3.10 CI cell
    import tomli as tomllib

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_PYPI_URL = "https://pypi.org/pypi/{name}/json"
_TIMEOUT_SECONDS = 20

#: A package with no release in this long is reported as decaying even when
#: every declared bound still admits its latest version. One year is long
#: enough that a stable, feature-complete library is not flagged for a quiet
#: quarter, and short enough to notice abandonment before it forces a pin.
_DEFAULT_STALE_DAYS = 365


@dataclass(frozen=True)
class Declared:
    """One declared requirement and where it was declared."""

    requirement: Requirement
    origin: str  # "dependencies", or the optional-dependency group name


@dataclass
class Finding:
    """What PyPI says about one declared requirement."""

    name: str
    specifier: str
    origin: str
    latest: str | None = None
    released: datetime | None = None
    admits_latest: bool | None = None
    error: str | None = None

    @property
    def age_days(self) -> int | None:
        """Days since the latest release, or None when unknown."""
        if self.released is None:
            return None
        return (datetime.now(timezone.utc) - self.released).days

    def is_behind(self) -> bool:
        """True when the declared specifier excludes the latest release."""
        return self.admits_latest is False

    def is_stale(self, stale_days: int) -> bool:
        """True when the package itself has not published recently."""
        age = self.age_days
        return age is not None and age >= stale_days


@dataclass
class Report:
    """Every finding, split by what it asks the maintainer to do."""

    behind: list[Finding] = field(default_factory=list)
    stale: list[Finding] = field(default_factory=list)
    errors: list[Finding] = field(default_factory=list)
    current: list[Finding] = field(default_factory=list)

    def has_drift(self) -> bool:
        """True when something needs a human decision."""
        return bool(self.behind or self.stale)


def load_declared(pyproject: Path) -> list[Declared]:
    """Every requirement declared in ``[project]``, base and extras alike.

    Dev and optional groups are included deliberately: a test-only pin that
    excludes the current release still blocks contributors, and an extra's
    ceiling is what a user of that extra actually resolves against.
    """
    with open(pyproject, "rb") as fh:
        data: dict[str, Any] = tomllib.load(fh)
    project: dict[str, Any] = data.get("project", {})
    out: list[Declared] = []
    for raw in project.get("dependencies", []):
        out.append(Declared(Requirement(raw), "dependencies"))
    optional: dict[str, list[str]] = project.get("optional-dependencies", {})
    for group, entries in sorted(optional.items()):
        for raw in entries:
            out.append(Declared(Requirement(raw), group))
    return out


def _fetch(name: str) -> dict[str, Any]:
    """Return PyPI's JSON metadata for ``name``."""
    url = _PYPI_URL.format(name=name)
    with urllib.request.urlopen(url, timeout=_TIMEOUT_SECONDS) as resp:  # noqa: S310
        payload: dict[str, Any] = json.load(resp)
    return payload


def _latest_stable(payload: dict[str, Any]) -> tuple[Version | None, datetime | None]:
    """The newest non-prerelease version and its upload time.

    ``info.version`` is PyPI's own "latest", which already excludes
    pre-releases, but it is read back through ``releases`` to recover the
    upload timestamp. A yanked-only or prerelease-only project yields
    ``(None, None)`` rather than a wrong answer.
    """
    info: dict[str, Any] = payload.get("info", {})
    releases: dict[str, list[dict[str, Any]]] = payload.get("releases", {})
    candidates: list[Version] = []
    for raw in releases:
        try:
            parsed = Version(raw)
        except InvalidVersion:
            continue
        if parsed.is_prerelease or parsed.is_devrelease:
            continue
        files = releases.get(raw) or []
        if files and all(f.get("yanked") for f in files):
            continue
        candidates.append(parsed)
    if not candidates:
        declared = info.get("version")
        if not declared:
            return None, None
        try:
            return Version(str(declared)), None
        except InvalidVersion:
            return None, None
    newest = max(candidates)
    uploaded: datetime | None = None
    for entry in releases.get(str(newest)) or []:
        raw_time = entry.get("upload_time_iso_8601") or entry.get("upload_time")
        if not raw_time:
            continue
        try:
            parsed_time = datetime.fromisoformat(str(raw_time).replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed_time.tzinfo is None:
            parsed_time = parsed_time.replace(tzinfo=timezone.utc)
        if uploaded is None or parsed_time < uploaded:
            uploaded = parsed_time
    return newest, uploaded


def inspect(declared: Declared, fetcher: Any = _fetch) -> Finding:
    """Resolve one declared requirement against PyPI."""
    req = declared.requirement
    finding = Finding(
        name=req.name,
        specifier=str(req.specifier) or "(unbounded)",
        origin=declared.origin,
    )
    try:
        payload = fetcher(req.name)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        finding.error = f"{type(exc).__name__}: {exc}"
        return finding
    latest, released = _latest_stable(payload)
    if latest is None:
        finding.error = "no non-prerelease release found on PyPI"
        return finding
    finding.latest = str(latest)
    finding.released = released
    # ``prereleases=False`` keeps an alpha from satisfying a bound that a
    # real user would never resolve to.
    finding.admits_latest = req.specifier.contains(latest, prereleases=False)
    return finding


def build_report(declared: list[Declared], stale_days: int, fetcher: Any = _fetch) -> Report:
    """Classify every declared requirement."""
    report = Report()
    for item in declared:
        finding = inspect(item, fetcher)
        if finding.error is not None:
            report.errors.append(finding)
        elif finding.is_behind():
            report.behind.append(finding)
        elif finding.is_stale(stale_days):
            report.stale.append(finding)
        else:
            report.current.append(finding)
    return report


def render_markdown(report: Report, stale_days: int) -> str:
    """Render the report. Stable enough to diff between runs."""
    lines: list[str] = ["### Dependency drift", ""]
    if not report.has_drift() and not report.errors:
        lines += [
            f"Every declared bound admits its dependency's latest release, and no "
            f"dependency has been quiet for {stale_days}+ days. Nothing to do.",
            "",
        ]
        return "\n".join(lines)

    if report.behind:
        lines += [
            "#### Ceiling drift — the declared bound excludes the current release",
            "",
            "| package | declared | latest on PyPI | where |",
            "| --- | --- | --- | --- |",
        ]
        for f in sorted(report.behind, key=lambda x: x.name):
            lines.append(f"| `{f.name}` | `{f.specifier}` | `{f.latest}` | {f.origin} |")
        lines += [
            "",
            "A user resolving these cannot install the current release. Re-test "
            "against it and lift the bound, or record why the bound is deliberate.",
            "",
        ]

    if report.stale:
        lines += [
            f"#### Upstream staleness — no release in {stale_days}+ days",
            "",
            "| package | latest on PyPI | released | where |",
            "| --- | --- | --- | --- |",
        ]
        for f in sorted(report.stale, key=lambda x: x.name):
            when = f.released.date().isoformat() if f.released else "unknown"
            age = f"{f.age_days} days ago" if f.age_days is not None else "unknown"
            lines.append(f"| `{f.name}` | `{f.latest}` | {when} ({age}) | {f.origin} |")
        lines += [
            "",
            "No bound is drifting yet. The risk is that the dependency stops "
            "tracking its own dependencies and becomes a ceiling on protokit.",
            "",
        ]

    if report.errors:
        lines += ["#### Not checked", "", "| package | reason |", "| --- | --- |"]
        for f in sorted(report.errors, key=lambda x: x.name):
            lines.append(f"| `{f.name}` | {f.error} |")
        lines += ["", "A lookup failure is not a clean bill of health.", ""]

    lines += [
        f"{len(report.current)} of "
        f"{len(report.current) + len(report.behind) + len(report.stale) + len(report.errors)} "
        "declared requirements are current.",
        "",
        "(Non-blocking — this is a review prompt, not a gate.)",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Print the report; always exit 0."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stale-days", type=int, default=_DEFAULT_STALE_DAYS)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="parse pyproject and list what would be checked, without network access",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    declared = load_declared(_PYPROJECT)
    if args.offline:
        print(f"Would check {len(declared)} declared requirements:")
        for item in declared:
            print(f"  {item.requirement.name:24s} {item.requirement.specifier}  [{item.origin}]")
        return 0

    report = build_report(declared, args.stale_days)
    md = render_markdown(report, args.stale_days)
    print(md)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(md)

    gh_output = os.environ.get("GITHUB_OUTPUT")
    if gh_output:
        with open(gh_output, "a", encoding="utf-8") as fh:
            fh.write(f"drift={'true' if report.has_drift() else 'false'}\n")

    return 0  # non-blocking: report, never fail the build


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
