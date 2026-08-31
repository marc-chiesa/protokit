"""U20 regression pins — lint rules that diverge from the buf semantics they claim.

Every rule pinned here carries ``source_spec="buf:<RULE_ID>"``, which is
protokit's machine-readable parity claim. These tests pin the *defects*
in that claim: each ``xfail(strict=True)`` test asserts the behaviour
protokit should have, currently fails, and will flip loudly to ``xpassed``
the moment the underlying rule is fixed.

**These tests pin findings; they do not fix them.** The rule sources under
``src/protokit/schema/lint/rules/`` are deliberately untouched.

Findings pinned
---------------

``U20-1`` — ``package/directory-match`` (``buf:PACKAGE_DIRECTORY_MATCH``)
silently suppresses violations that buf reports.

    *Mechanism.* The rule derives an **expected package from the
    directory** (``src/protokit/schema/lint/rules/package.py``:
    ``expected_package = ".".join(dir_parts)``) and bails out whenever
    that derivation is impossible — ``if not dir_parts: return`` for
    files at the module root, and ``if not all(_PROTO_IDENTIFIER_RE
    .match(part) ...): return`` for any directory segment that is not a
    valid protobuf identifier (hyphens, leading digits, ``..``, ``/``).

    Buf runs the comparison in the **opposite direction**: it derives an
    expected *directory* from the declared *package* and compares it to
    the actual directory, so neither a root-level file nor a hyphenated
    directory has anything to bail out of. That asymmetry is the whole
    defect: two ordinary layouts that buf reports produce zero findings
    in protokit.

    This is **not** a documented parity divergence. There is no
    ``_PARITY_EXCEPTIONS`` entry for ``package/directory-match`` in
    ``tests/parity/conftest.py``, and the rule's own docstring plus
    ``tests/schema/lint/rules/test_package.py::TestPackageDirectoryMatch
    ::test_skipped_when_file_is_top_level`` both assert the *opposite* of
    what buf does — verbatim, "Buf has the same behavior; protokit
    mirrors." Fixing the rule must also correct that false parity claim.

``U20-2`` — ``imports/unused`` (``buf:IMPORT_USED``) **false-positives**
on load-bearing imports.

    *Mechanism.* ``check_unused_imports`` builds its ``used_files`` set by
    walking only field types (``msg.fields`` → ``message_type`` /
    ``enum_type``, recursively through ``nested_types``) and method
    input/output types. It never visits option slots and never visits
    ``ctx.file.extensions_by_name``. An import whose only consumer is a
    custom option or an ``extend`` block is therefore reported unused at
    severity **ERROR**.

    This is the worst failure mode a linter has: following the advice
    deletes an import the schema needs and the tree stops compiling. The
    ``_load_bearing`` guard tests below prove that independently of any
    external tool, using protokit's own compiler.

    The rule docstring calls these "known false positives ... tracked for
    D6b". D6b shipped long ago (the tree is at 0.15.0 / D6f) and the gap
    is still open, so this is a deferred defect, not a declared posture:
    it has no ``_PARITY_EXCEPTIONS`` entry and no per-branch parity test.

Finding dropped
---------------

``U20-3`` — "explicit ``syntax = \"proto2\";`` is warned as missing
syntax" — **DROPPED, documented deliberate divergence.** ``file/syntax-
specified`` firing on explicit proto2 is declared at five sites per
``docs/solutions/best-practices/buf-parity-divergence-documentation-
discipline-2026-05-13.md``: the ``file`` module docstring, the
``check_syntax_specified`` docstring, the ``message_template``, the
per-branch tests in ``tests/schema/lint/rules/test_file.py``
(``test_sad_path_explicit_proto2_fires`` vs
``test_sad_path_no_syntax_statement_fires``), and the
``("file/syntax-specified", "explicit_proto2")`` entry in
``_PARITY_EXCEPTIONS`` (``tests/parity/conftest.py``) consumed by
``tests/parity/test_parity_file.py``. Pinning it here would put two
tests in this suite asserting opposite outcomes for the same input.

Two residues were verified but are documentation defects, not behaviour
defects, so neither is pinned: (a) the divergence's stated rationale —
"the descriptor cannot distinguish the two cases" — is stale;
``compile_protos_to_result(..., include_source_info=True)`` does
distinguish them (``source_code_info`` location path ``(12,)`` is present
for ``syntax = "proto2";`` and absent when the statement is omitted, and
survives a leading license block and single-quoted ``'proto2'``); and
(b) the finding's message is literally accurate on its first clause
("does not declare ``syntax = \"proto3\";``") but its second clause
recommends declaring syntax explicitly to a file that already does.

Evidence
--------

Both pins were reproduced against a real ``buf`` binary (**v1.69.0**,
``/opt/homebrew/bin/buf``) with ``version: v2`` module configs enabling
exactly one rule, plus positive controls proving the buf rule was live:

- U20-1: buf fires ``PACKAGE_DIRECTORY_MATCH`` on all three protokit-
  silent layouts — root (``directory "."``), ``acme-api/`` and
  ``acme-api/v1/`` — and agrees with protokit on both controls.
- U20-2: buf's ``IMPORT_USED`` is live under the same config (it fires on
  a plain unused import and on this repo's own
  ``tests/parity/fixtures/imports/unused/bad.proto``) yet is silent on
  all three load-bearing imports; ``buf build`` on the tree with those
  imports removed fails with ``cannot find ... in this scope``.

The assertions below are **protokit-side only and take no dependency on
any buf version**. That is deliberate: ``_BUF_PARITY_PIN`` in
``src/protokit/schema/lint/cli.py`` is ``v1.70.0``, the binary available
here is v1.69.0, and buf changed ``IMPORT_USED`` behaviour after the pin
— so a test encoding "buf reports nothing here" would be pinning an
unverified claim about a version this machine cannot run. Instead, U20-2
is pinned against a tool-independent oracle: the import is load-bearing
because *removing it breaks compilation*, proven with protokit's own
compiler in the ``_load_bearing`` guards. Those guards pass today and
would fail loudly if the premise ever rotted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.rules import imports as imports_pack
from protokit.schema.lint.rules import package as package_pack
from tests.schema.lint.rules.conftest import _run_single

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _findings_for(report: Any, rule_id: str) -> tuple[Any, ...]:
    """Findings in ``report`` emitted by ``rule_id``, in report order."""
    return tuple(f for f in report.findings if f.rule_id == rule_id)


def _compiles(tmp_path: Path, sources: dict[str, str]) -> bool:
    """Whether ``sources`` compile as a self-contained tree.

    Tool-independent oracle for "this import is load-bearing": write the
    tree, compile it through protokit's own entry point, and report
    whether any file descriptor came back. A tree that fails to resolve a
    custom option or an ``extend`` target yields no ``root_files`` on
    every backend (protoxy raises; protoc exits non-zero), so the check
    does not depend on which compiler happens to be installed.
    """
    paths: list[Path] = []
    for name, text in sources.items():
        p = tmp_path / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        paths.append(p)
    result = compile_protos_to_result(
        paths=paths, proto_paths=(str(tmp_path),),
    )
    return bool(result.root_files)


def _without_import(source: str, imported: str) -> str:
    """``source`` with the ``import "<imported>";`` line deleted.

    Models a user literally following the ``imports/unused`` advice
    ("drop the import"). Asserts the line was present so the helper can
    never silently no-op into a vacuous test.
    """
    line = f'import "{imported}";\n'
    assert line in source, f"{imported!r} is not imported by this source"
    return source.replace(line, "")


# ---------------------------------------------------------------------------
# U20-1 — package/directory-match suppresses violations buf reports
# ---------------------------------------------------------------------------

_ROOT_LEVEL = """\
syntax = "proto3";
package acme;
message User { string name = 1; }
"""

_HYPHEN_DIR = """\
syntax = "proto3";
package acme_api;
message User { string name = 1; }
"""

_HYPHEN_DIR_VERSIONED = """\
syntax = "proto3";
package acme_api.v1;
message User { string name = 1; }
"""

_MISMATCHED_DIR = """\
syntax = "proto3";
package wrong_pkg;
message User { string name = 1; }
"""

#: Byte-identical to ``_ROOT_LEVEL`` on purpose. The negative control
#: places this content at ``acme/users.proto`` (clean in both tools) and
#: the root-directory pin places it at ``users.proto`` (buf fires,
#: protokit is silent), so *file placement* is the only variable between
#: a clean result and a suppressed violation. Collapsing the two into one
#: constant would hide that.
_MATCHED_DIR = """\
syntax = "proto3";
package acme;
message User { string name = 1; }
"""


class TestU20PackageDirectoryMatchControls:
    """Controls proving the rule is live and path-shaped as buf sees it.

    Without these, the zero-finding results the ``xfail`` tests below
    assert against could be a harness artifact (rule not loaded, or
    ``fd.name`` recorded as an absolute path so no layout ever matches)
    rather than a genuine suppression. Both controls pass today and are
    expected to keep passing.
    """

    def test_positive_control_mismatched_directory_fires(
        self, tmp_path: Path,
    ) -> None:
        """``acme_api/users.proto`` declaring ``package wrong_pkg`` fires.

        buf v1.69.0 agrees (``PACKAGE_DIRECTORY_MATCH`` on the same
        file). Establishes that the rule runs and that ``fd.name`` is the
        pool-relative POSIX path buf also compares against.
        """
        report = _run_single(
            tmp_path,
            {"acme_api/users.proto": _MISMATCHED_DIR},
            "package/directory-match",
            package_pack,
        )
        findings = _findings_for(report, "package/directory-match")
        assert len(findings) == 1
        assert findings[0].params == {
            "file": "acme_api/users.proto",
            "package": "wrong_pkg",
            "expected": "acme_api",
        }

    def test_negative_control_matched_directory_is_clean(
        self, tmp_path: Path,
    ) -> None:
        """``acme/users.proto`` declaring ``package acme`` is clean.

        buf v1.69.0 agrees (exit 0). Establishes that a zero-finding
        result is a meaningful signal for this rule rather than the
        rule's only possible output.
        """
        report = _run_single(
            tmp_path,
            {"acme/users.proto": _MATCHED_DIR},
            "package/directory-match",
            package_pack,
        )
        assert _findings_for(report, "package/directory-match") == ()


class TestU20PackageDirectoryMatchSuppression:
    """The suppressions themselves — pinned as defects."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "U20-1: package/directory-match returns early on files at the "
            "module root (`if not dir_parts: return`), so a root-level file "
            "declaring a package is never checked. buf v1.69.0 reports "
            "PACKAGE_DIRECTORY_MATCH on this exact layout, naming the "
            'offending directory "."'
        ),
    )
    def test_root_directory_mismatch_is_suppressed(
        self, tmp_path: Path,
    ) -> None:
        """A root-level ``users.proto`` declaring ``package acme;`` must fire.

        The rule derives its expected value from the directory, so a file
        with no directory parts yields nothing to compare and the rule
        bails. Buf derives the expected *directory* from the package
        instead — ``package acme`` demands directory ``acme``, the file is
        in ``"."``, so buf fires. Nothing about the root position makes
        the violation less real; the bail-out is a mechanism artifact.
        """
        report = _run_single(
            tmp_path,
            {"users.proto": _ROOT_LEVEL},
            "package/directory-match",
            package_pack,
        )
        findings = _findings_for(report, "package/directory-match")
        assert len(findings) == 1, (
            f"expected 1 package/directory-match finding for a root-level "
            f"file declaring `package acme;`; got {len(findings)}"
        )
        assert findings[0].params["file"] == "users.proto"
        assert findings[0].params["package"] == "acme"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "U20-1: package/directory-match returns early when any directory "
            "segment fails _PROTO_IDENTIFIER_RE, so a hyphenated directory "
            "suppresses the check entirely. buf v1.69.0 reports "
            'PACKAGE_DIRECTORY_MATCH: package "acme_api" belongs in '
            '"acme_api" but the file is in "acme-api"'
        ),
    )
    def test_hyphenated_directory_mismatch_is_suppressed(
        self, tmp_path: Path,
    ) -> None:
        """``acme-api/users.proto`` declaring ``package acme_api;`` must fire.

        The identifier guard exists so the rule never renders a nonsense
        ``expected`` package — but that is an argument about *message
        content*, not about whether the violation exists. Buf's direction
        (package → expected directory) produces a perfectly sensible
        message here: ``acme_api`` belongs in ``acme_api/``, not
        ``acme-api/``. Hyphenated directories are the single most common
        way a real repo trips this rule, and protokit is silent on them.
        """
        report = _run_single(
            tmp_path,
            {"acme-api/users.proto": _HYPHEN_DIR},
            "package/directory-match",
            package_pack,
        )
        findings = _findings_for(report, "package/directory-match")
        assert len(findings) == 1, (
            f"expected 1 package/directory-match finding for "
            f"`acme-api/users.proto` declaring `package acme_api;`; got "
            f"{len(findings)}"
        )
        assert findings[0].params["file"] == "acme-api/users.proto"
        assert findings[0].params["package"] == "acme_api"

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "U20-1: the identifier guard suppresses realistic input, not "
            "only degenerate one-segment paths — a versioned "
            "`acme-api/v1/` layout is silently skipped where buf v1.69.0 "
            "reports PACKAGE_DIRECTORY_MATCH"
        ),
    )
    def test_hyphenated_versioned_directory_mismatch_is_suppressed(
        self, tmp_path: Path,
    ) -> None:
        """``acme-api/v1/users.proto`` with ``package acme_api.v1;`` must fire.

        Separate from the single-segment case on purpose: it forecloses
        the "only a degenerate path triggers this" reading. One bad
        segment out of two disables the rule for the whole file, and
        ``<hyphenated-service>/v1/`` is an entirely ordinary monorepo
        shape.
        """
        report = _run_single(
            tmp_path,
            {"acme-api/v1/users.proto": _HYPHEN_DIR_VERSIONED},
            "package/directory-match",
            package_pack,
        )
        findings = _findings_for(report, "package/directory-match")
        assert len(findings) == 1, (
            f"expected 1 package/directory-match finding for "
            f"`acme-api/v1/users.proto` declaring `package acme_api.v1;`; "
            f"got {len(findings)}"
        )
        assert findings[0].params["file"] == "acme-api/v1/users.proto"
        assert findings[0].params["package"] == "acme_api.v1"


# ---------------------------------------------------------------------------
# U20-2 — imports/unused false-positives on load-bearing imports
# ---------------------------------------------------------------------------

#: proto2 file defining a custom method option. Its import of
#: ``descriptor.proto`` is consumed only by the ``extend`` block.
_OPTS = """\
syntax = "proto2";
package acme.opts;
import "google/protobuf/descriptor.proto";
extend google.protobuf.MethodOptions {
  optional string my_option = 50000;
}
"""

#: proto3 service whose import of ``opts.proto`` is consumed only by a
#: custom method option — no field or method type references it.
_SVC = """\
syntax = "proto3";
package acme.v1;
import "acme/opts/opts.proto";
message Req {}
message Res {}
service S {
  rpc Do(Req) returns (Res) {
    option (acme.opts.my_option) = "x";
  }
}
"""

#: proto2 message with an extension range, extended from another file.
_BASE = """\
syntax = "proto2";
package acme.base;
message Base {
  extensions 100 to 200;
}
"""

#: proto2 file whose import of ``base.proto`` is consumed only by the
#: ``extend`` declaration — no field type references ``acme.base.Base``.
_EXT = """\
syntax = "proto2";
package acme.ext;
import "acme/base/base.proto";
extend acme.base.Base {
  optional string note = 100;
}
"""

#: (label, sources, importing file, imported file) for each load-bearing
#: import that ``imports/unused`` currently reports.
_LOAD_BEARING_CASES: tuple[tuple[str, dict[str, str], str, str], ...] = (
    (
        "custom-method-option",
        {"acme/opts/opts.proto": _OPTS, "acme/v1/svc.proto": _SVC},
        "acme/v1/svc.proto",
        "acme/opts/opts.proto",
    ),
    (
        "proto2-extend-declaration",
        {"acme/base/base.proto": _BASE, "acme/ext/ext.proto": _EXT},
        "acme/ext/ext.proto",
        "acme/base/base.proto",
    ),
    (
        "extend-descriptor-proto",
        {"acme/opts/opts.proto": _OPTS},
        "acme/opts/opts.proto",
        "google/protobuf/descriptor.proto",
    ),
)


class TestU20ImportsUnusedLoadBearingGuards:
    """Tool-independent proof that each flagged import is genuinely used.

    These tests carry the weight of the ``imports/unused`` pins: they
    establish, without buf and without any version claim, that following
    the rule's advice ("drop the import") breaks the schema. They pass
    today and must keep passing — if one ever fails, the corresponding
    ``xfail`` below has lost its premise and should be re-triaged rather
    than kept.
    """

    @pytest.mark.parametrize(
        ("label", "sources", "importer", "imported"),
        _LOAD_BEARING_CASES,
        ids=[c[0] for c in _LOAD_BEARING_CASES],
    )
    def test_import_is_load_bearing(
        self,
        tmp_path: Path,
        label: str,
        sources: dict[str, str],
        importer: str,
        imported: str,
    ) -> None:
        """The tree compiles with the import and stops compiling without it."""
        assert _compiles(tmp_path / "with", sources), (
            f"{label}: baseline tree must compile before the removal half "
            f"of this test means anything"
        )
        stripped = dict(sources)
        stripped[importer] = _without_import(sources[importer], imported)
        assert not _compiles(tmp_path / "without", stripped), (
            f"{label}: {imported!r} was expected to be load-bearing for "
            f"{importer!r}, but the tree still compiled without it — the "
            f"imports/unused xfail pin for this case is no longer justified"
        )


class TestU20ImportsUnusedFalsePositives:
    """The false positives themselves — pinned as defects."""

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "U20-2: imports/unused false-positives on an import used only by "
            "a custom method option. check_unused_imports walks field types "
            "and method input/output types only; it never visits option "
            "slots, so `import \"acme/opts/opts.proto\";` is reported unused "
            "at severity ERROR even though deleting it breaks compilation"
        ),
    )
    def test_import_used_only_by_custom_method_option(
        self, tmp_path: Path,
    ) -> None:
        """An import consumed only by ``option (acme.opts.my_option)`` is clean.

        This is the highest-cost class of linter bug: the finding is an
        ERROR, the advice is "drop the import", and the advice is wrong.
        The load-bearing guard above proves the import is needed.
        """
        report = _run_single(
            tmp_path,
            {"acme/opts/opts.proto": _OPTS, "acme/v1/svc.proto": _SVC},
            "imports/unused",
            imports_pack,
        )
        offending = [
            f
            for f in _findings_for(report, "imports/unused")
            if f.params.get("imported") == "acme/opts/opts.proto"
        ]
        assert offending == [], (
            f"imports/unused must not report 'acme/opts/opts.proto' — it is "
            f"used by the custom method option on acme.v1.S.Do; got "
            f"{[f.params for f in offending]}"
        )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "U20-2: imports/unused false-positives on an import used only by "
            "a proto2 extension declaration. check_unused_imports never "
            "visits ctx.file.extensions_by_name, so the import that supplies "
            "the `extend` target is reported unused at severity ERROR even "
            "though deleting it breaks compilation"
        ),
    )
    def test_import_used_only_by_proto2_extend_declaration(
        self, tmp_path: Path,
    ) -> None:
        """An import consumed only by ``extend acme.base.Base`` is clean."""
        report = _run_single(
            tmp_path,
            {"acme/base/base.proto": _BASE, "acme/ext/ext.proto": _EXT},
            "imports/unused",
            imports_pack,
        )
        offending = [
            f
            for f in _findings_for(report, "imports/unused")
            if f.params.get("imported") == "acme/base/base.proto"
        ]
        assert offending == [], (
            f"imports/unused must not report 'acme/base/base.proto' — it "
            f"supplies the target of `extend acme.base.Base`; got "
            f"{[f.params for f in offending]}"
        )

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "U20-2: imports/unused false-positives on "
            "google/protobuf/descriptor.proto in every file that defines a "
            "custom option — the import is consumed only by the `extend "
            "google.protobuf.MethodOptions` block, which the walker does not "
            "visit. This makes the rule fire an ERROR on the canonical "
            "custom-option definition file shape"
        ),
    )
    def test_descriptor_proto_import_in_a_custom_option_file(
        self, tmp_path: Path,
    ) -> None:
        """``descriptor.proto`` imported to extend ``MethodOptions`` is clean.

        Broken out from the ``extend``-declaration case because of its
        blast radius: this is the shape of *every* file that declares a
        custom option, so the false positive is not an edge case in
        practice — it fires on the standard way of defining options.
        """
        report = _run_single(
            tmp_path,
            {"acme/opts/opts.proto": _OPTS},
            "imports/unused",
            imports_pack,
        )
        offending = [
            f
            for f in _findings_for(report, "imports/unused")
            if f.params.get("imported") == "google/protobuf/descriptor.proto"
        ]
        assert offending == [], (
            f"imports/unused must not report "
            f"'google/protobuf/descriptor.proto' — it supplies "
            f"google.protobuf.MethodOptions for the extend block; got "
            f"{[f.params for f in offending]}"
        )
