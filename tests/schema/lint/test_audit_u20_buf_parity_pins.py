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

``R11-C2`` (``imports/unused`` on an import used only through ``import
public``) and ``R25-C3`` (the ``package/same-*`` rules on an empty-string
option value) were found by the 0.16.0 re-audit, cycle 1. Neither is a U20
finding, and both are owned by the same unit as the U20 pins. They are
pinned in the last section of this file; the comment block that opens the
section gives each one's mechanism and evidence.

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

from protokit.schema.lint.rules import imports as imports_pack
from protokit.schema.lint.rules import package as package_pack
from protokit.schema.lint.rules import package_same as package_same_pack
from tests.schema.lint.rules.conftest import _compile, _run_single

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
    return bool(_compile(tmp_path, sources).root_files)


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
        raises=AssertionError,
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
        raises=AssertionError,
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
        raises=AssertionError,
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
        raises=AssertionError,
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
        raises=AssertionError,
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
        raises=AssertionError,
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


# ---------------------------------------------------------------------------
# 0.16.0 re-audit, cycle 1 — R11-C2 and R25-C3, owned by U15 (0.18.0)
# ---------------------------------------------------------------------------
#
# Two more places where a rule diverges from the buf rule its ``source_spec``
# names. Neither is a U20 finding, and U15's planned fixes do not reach either
# mechanism, so each has pins of its own. Every pin in this section is
# ``xfail(strict=True)`` with a specific ``raises=``, its ``reason`` leads with
# the finding ID, and it flips to XPASS (a hard failure under strict mode) the
# day the rule is fixed. A passing control or guard sits beside each pin and
# shares its construction.
#
# ``R11-C2`` — ``imports/unused`` (``buf:IMPORT_USED``) reports an import that
# is used only through ``import public``.
#
#     *Mechanism.* ``check_unused_imports`` records the file that DEFINES each
#     referenced type and compares that set with the importing file's own
#     ``dependency`` list. When ``a.proto`` imports ``b.proto`` and ``b.proto``
#     re-exports ``c.proto`` with ``import public``, a reference to ``c.C``
#     records ``c.proto``. ``b.proto`` is never in the set, so the import is
#     reported unused at severity ERROR, and it is the import that makes
#     ``c.C`` visible: delete it and the tree stops compiling. The advice is as
#     destructive as U20-2's and the mechanism is different. Tracing options
#     and extensions, which is U15's planned fix for U20-2, does not follow
#     ``public_dependency``.
#
#     *Evidence.* buf v1.69.0 with ``lint.use: [IMPORT_USED]`` is silent on the
#     consumer's import, and ``buf build`` on the tree without it fails with
#     "cannot find `c.C` in this scope". On the same chain with nothing
#     referenced buf reports ``Import "b.proto" is unused.``, which is the
#     control below. As with U20-2 the assertions take no dependency on buf:
#     the guard proves the import load-bearing with protokit's own compiler.
#
# ``R25-C3`` — the six string-valued ``package/same-*`` rules
# (``buf:PACKAGE_SAME_GO_PACKAGE`` and its siblings) count
# ``option go_package = "";`` as a declared value, and choose the message arm
# from the number of declared values alone.
#
#     *Mechanism.* ``_check_package_option`` builds ``declared_set`` from every
#     value that ``is not None``, so an explicit empty string is a value, and
#     it says ``multiple values`` whenever ``len(declared_set) >= 2`` without
#     consulting ``has_omitter``. buf reads an empty string as "not set", and
#     says ``both values "..." and no value`` whenever some file sets nothing.
#     Three inputs diverge (package ``smoke.p``, one file per value):
#
#     - ``""`` and a file omitting the option: buf reports nothing and exits
#       0; protokit reports two ERRORs, ``both values "" and no value``. Under
#       the default ``recommended`` profile that is a false ERROR and exit 1.
#     - ``x/X``, ``x/Y`` and an omitter: buf says ``both values "x/X,x/Y" and
#       no value``; protokit says ``multiple values "x/X,x/Y"``.
#     - ``""`` and ``x/X``: buf says ``both values "x/X" and no value``;
#       protokit says ``multiple values ",x/X"``.
#
#     *Evidence.* Unlike U20-2 and R11-C2 there is no tool-independent oracle:
#     what an empty string means here is buf's decision. The expected values
#     are buf v1.69.0's output, verbatim, from ``version: v2`` module configs
#     enabling one ``PACKAGE_SAME_*`` rule each. For every one of the six
#     string options buf is clean on ``""`` plus an omitter and fires on a
#     non-empty value plus an omitter, so that pin and its control are
#     parametrized over the six rules; the message-arm rows were run for
#     ``go_package``. v1.69.0 is the version the pack's recorded snapshots
#     are locked to (``rules/fixtures/package_same/_buf_smoke/recorded/``).
#     ``_BUF_PARITY_PIN`` is v1.70.0, which was not available to run, and no
#     test here runs buf. The fix should record ``empty-string`` and
#     ``mixed-value-with-omitter`` snapshots at the pinned version; if they
#     disagree with a value asserted below, the snapshot wins.

# ---------------------------------------------------------------------------
# R11-C2 — imports/unused on an import used only through `import public`
# ---------------------------------------------------------------------------

#: Defines the type the consumer references.
_REEXPORTED = """\
syntax = "proto3";
package acme.c;
message C { int32 x = 1; }
"""

#: Re-exports ``acme/c/c.proto`` and declares nothing of its own.
_REEXPORTER = """\
syntax = "proto3";
package acme.b;
import public "acme/c/c.proto";
"""

#: Imports only the re-exporter and references the re-exported type.
_REEXPORT_CONSUMER = """\
syntax = "proto3";
package acme.a;
import "acme/b/b.proto";
message A { acme.c.C c = 1; }
"""

#: The same import with nothing from the chain referenced: genuinely unused.
_REEXPORT_NON_CONSUMER = """\
syntax = "proto3";
package acme.a;
import "acme/b/b.proto";
message A { int32 x = 1; }
"""


def _reexport_tree(consumer: str) -> dict[str, str]:
    """The three-file re-export chain with ``consumer`` as ``acme/a/a.proto``."""
    return {
        "acme/c/c.proto": _REEXPORTED,
        "acme/b/b.proto": _REEXPORTER,
        "acme/a/a.proto": consumer,
    }


class TestR11C2ImportsUnusedPublicReexport:
    """``imports/unused`` on ``a -> b -(import public)-> c`` where ``a`` uses ``c.C``."""

    def test_guard_reexporting_import_is_load_bearing(
        self, tmp_path: Path,
    ) -> None:
        """The chain compiles with the consumer's import and not without it.

        Carries the weight of the pin, the way the U20-2 guards do: no buf
        and no version claim, only the fact that following the rule's
        advice breaks the schema. If this ever fails the pin has lost its
        premise and needs re-triage.
        """
        sources = _reexport_tree(_REEXPORT_CONSUMER)
        assert _compiles(tmp_path / "with", sources), (
            "the re-export chain must compile before the removal half of "
            "this test means anything"
        )
        stripped = dict(sources)
        stripped["acme/a/a.proto"] = _without_import(
            _REEXPORT_CONSUMER, "acme/b/b.proto",
        )
        assert not _compiles(tmp_path / "without", stripped), (
            "'acme/b/b.proto' was expected to be load-bearing for "
            "'acme/a/a.proto', but the tree still compiled without it — the "
            "R11-C2 pin is no longer justified"
        )

    def test_control_unreferenced_reexporting_import_is_reported(
        self, tmp_path: Path,
    ) -> None:
        """The same chain with nothing referenced: the import IS unused.

        buf v1.69.0 agrees (``Import "b.proto" is unused.``). Whether the
        consumer references the re-exported type is the only variable
        between this correct finding and the false positive pinned below,
        and it shows the rule runs on this tree.
        """
        report = _run_single(
            tmp_path,
            _reexport_tree(_REEXPORT_NON_CONSUMER),
            "imports/unused",
            imports_pack,
        )
        findings = _findings_for(report, "imports/unused")
        assert [(f.location.file, f.params) for f in findings] == [
            ("acme/a/a.proto", {"imported": "acme/b/b.proto"}),
        ]

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "R11-C2: owned by U15 (0.18.0). imports/unused compares the files "
            "that define the referenced types with the importing file's own "
            "dependency list and never follows public_dependency, so an "
            "import whose types arrive through `import public` is reported "
            "unused at severity ERROR even though deleting it breaks "
            "compilation. buf v1.69.0 IMPORT_USED is silent"
        ),
    )
    def test_import_used_only_through_a_public_reexport(
        self, tmp_path: Path,
    ) -> None:
        """``import "acme/b/b.proto";`` supplying ``acme.c.C`` is clean."""
        report = _run_single(
            tmp_path,
            _reexport_tree(_REEXPORT_CONSUMER),
            "imports/unused",
            imports_pack,
        )
        _require_the_rule_ran(report)
        offending = [
            f
            for f in _findings_for(report, "imports/unused")
            if f.params.get("imported") == "acme/b/b.proto"
        ]
        assert offending == [], (
            f"imports/unused must not report 'acme/b/b.proto' — it re-exports "
            f"'acme/c/c.proto', which supplies acme.c.C to acme.a.A; got "
            f"{[f.params for f in offending]}"
        )


# ---------------------------------------------------------------------------
# R25-C3 — package/same-* on an empty-string value and on values + omitter
# ---------------------------------------------------------------------------

#: (option, rule id) for the six string-valued ``package/same-*`` rules.
#: ``java_multiple_files`` is a bool and presence-based in buf too.
_STRING_OPTION_RULES: tuple[tuple[str, str], ...] = (
    ("go_package", "package/same-go-package"),
    ("java_package", "package/same-java-package"),
    ("csharp_namespace", "package/same-csharp-namespace"),
    ("php_namespace", "package/same-php-namespace"),
    ("ruby_package", "package/same-ruby-package"),
    ("swift_prefix", "package/same-swift-prefix"),
)
_STRING_OPTION_IDS = [option for option, _ in _STRING_OPTION_RULES]


def _require_the_rule_ran(report: Any) -> None:
    """Fail outright when the lint run did not complete.

    The engine catches a rule that raises and records a runtime warning, so
    a broken rule leaves no findings, which is exactly what the pins below
    that expect a clean result assert. ``pytest.fail`` is outside their
    ``raises=AssertionError``, so that outcome turns the pin red instead of
    reading as the defect fixed.
    """
    errors = [d for d in report.diagnostics if d.level == "error"]
    if report.runtime_warnings or errors:
        pytest.fail(
            f"the lint run did not complete: runtime_warnings="
            f"{list(report.runtime_warnings)}, compile errors={errors}"
        )


def _package_same_payloads(
    tmp_path: Path,
    option: str,
    rule_id: str,
    values: dict[str, str | None],
) -> list[str]:
    """Lint one ``smoke.p`` package; return each finding's ``values_payload``.

    ``values`` maps a file stem to the value that file declares for
    ``option``, or to ``None`` for a file that omits the option. One
    finding is emitted per file of a disagreeing package, so the length of
    the result is part of what each caller asserts.
    """
    sources: dict[str, str] = {}
    for stem, value in values.items():
        declaration = "" if value is None else f'option {option} = "{value}";\n'
        sources[f"smoke/p/{stem}.proto"] = (
            f'syntax = "proto3";\npackage smoke.p;\n{declaration}'
        )
    report = _run_single(tmp_path, sources, rule_id, package_same_pack)
    _require_the_rule_ran(report)
    return [f.params["values_payload"] for f in _findings_for(report, rule_id)]


class TestR25C3PackageSameControls:
    """Inputs where protokit and buf v1.69.0 agree, built the way the pins are.

    They show each rule is live in this harness, that both message arms are
    reachable, and that a zero-finding result is a meaningful signal — so the
    pins below fail on the empty string and the omitter, not on the harness.
    """

    @pytest.mark.parametrize(
        ("option", "rule_id"), _STRING_OPTION_RULES, ids=_STRING_OPTION_IDS,
    )
    def test_control_one_value_plus_omitter_reports_both_values_and_no_value(
        self, tmp_path: Path, option: str, rule_id: str,
    ) -> None:
        """A non-empty value beside an omitter fires, for each string option."""
        payloads = _package_same_payloads(
            tmp_path, option, rule_id, {"a": "x/X", "b": None},
        )
        assert payloads == ['both values "x/X" and no value'] * 2

    def test_control_two_values_without_an_omitter_reports_multiple_values(
        self, tmp_path: Path,
    ) -> None:
        """Two declared values and no omitter is the ``multiple values`` arm."""
        payloads = _package_same_payloads(
            tmp_path, "go_package", "package/same-go-package",
            {"a": "x/X", "b": "x/Y"},
        )
        assert payloads == ['multiple values "x/X,x/Y"'] * 2

    def test_control_every_file_omitting_the_option_is_clean(
        self, tmp_path: Path,
    ) -> None:
        """No file declares the option: nothing to disagree about."""
        payloads = _package_same_payloads(
            tmp_path, "go_package", "package/same-go-package",
            {"a": None, "b": None},
        )
        assert payloads == []


class TestR25C3PackageSameEmptyStringAndOmitter:
    """The divergences themselves — pinned as defects."""

    @pytest.mark.parametrize(
        ("option", "rule_id"), _STRING_OPTION_RULES, ids=_STRING_OPTION_IDS,
    )
    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "R25-C3: owned by U15 (0.18.0). _check_package_option counts an "
            'explicit empty string as a declared value, so `option X = "";` '
            "beside a file that omits X is reported as two ERRORs (`both "
            'values "" and no value`). buf v1.69.0 reads an empty string as '
            "unset and reports nothing"
        ),
    )
    def test_empty_string_plus_omitter_is_clean(
        self, tmp_path: Path, option: str, rule_id: str,
    ) -> None:
        """``option X = "";`` in one file and no option in the other is clean."""
        payloads = _package_same_payloads(
            tmp_path, option, rule_id, {"a": "", "b": None},
        )
        assert payloads == [], (
            f"{rule_id} must not report a package whose only declared "
            f"{option} is the empty string; got {payloads}"
        )

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "R25-C3: owned by U15 (0.18.0). _check_package_option says "
            "`multiple values` whenever two or more values are declared and "
            "never consults has_omitter. With an omitter present buf v1.69.0 "
            'says `both values "x/X,x/Y" and no value`'
        ),
    )
    def test_two_values_plus_omitter_reports_both_values_and_no_value(
        self, tmp_path: Path,
    ) -> None:
        """Two values and an omitter take the ``and no value`` arm, on all three files."""
        payloads = _package_same_payloads(
            tmp_path, "go_package", "package/same-go-package",
            {"a": "x/X", "b": "x/Y", "c": None},
        )
        assert payloads == ['both values "x/X,x/Y" and no value'] * 3, (
            f"two go_package values beside a file that omits the option must "
            f"be reported as values and no value, once per file; got {payloads}"
        )

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "R25-C3: owned by U15 (0.18.0). An empty string beside a real "
            'value is counted as a second value (`multiple values ",x/X"`). '
            "buf v1.69.0 reads it as unset, which makes this one value plus "
            'an omitter: `both values "x/X" and no value`'
        ),
    )
    def test_empty_string_plus_one_value_reports_that_value_and_no_value(
        self, tmp_path: Path,
    ) -> None:
        """``""`` beside ``x/X`` reads as an omitter beside ``x/X``."""
        payloads = _package_same_payloads(
            tmp_path, "go_package", "package/same-go-package",
            {"a": "", "b": "x/X"},
        )
        assert payloads == ['both values "x/X" and no value'] * 2, (
            f"an empty-string go_package beside \"x/X\" must be reported as "
            f"one value and no value, once per file; got {payloads}"
        )
