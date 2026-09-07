"""Regression pins for U14-1 / U14-2 — ``schema/compile.py`` pre-flight guards.

Both findings live in the two *pre-flight* detectors that
:func:`protokit.schema.compile.compile_protos_to_result` runs BEFORE any
backend is invoked:

* :func:`~protokit.schema.compile._detect_root_transitive_shadow`
  (``compile.py:305``, loop head ``for root in paths:`` at ``:339``)
* :func:`~protokit.schema.compile._detect_same_basename_collision`
  (``compile.py:356``)

Both guards reason about ``fd.name`` shadowing — but neither computes
``fd.name``. The module that does is two files over:
:func:`protokit._cli_utils._resolve_expected_name` (``_cli_utils.py:593``),
which walks ``includes = [*include_paths, *parents]`` in declared order and
returns the first prefix-relative form. That is exactly what both backends
emit as ``fd.name`` (``_cli_utils.py:406-428``). The two detectors instead
compare ``Path.name`` — the bare basename — so their verdicts diverge from
the logical names they claim to protect.

**U14-1** (``compile.py:342``, ``candidate = Path(inc) / root.name``). The
shadow guard's own docstring frames the hazard as the backend emitting "a
``FileDescriptorProto`` for that shadow instead of the root the user
passed", i.e. a *logical-name* collision. Comparing basenames gets that
wrong in both directions:

* **false positive** — root ``vendor/acme/user.proto`` with
  ``-I current -I vendor`` resolves to logical name ``acme/user.proto``;
  an unrelated ``current/user.proto`` resolves to ``user.proto``. The two
  can never collide, yet the basename comparison reports a shadow and the
  compile is refused outright (``root_files=()``, ``pool_file_names=()``).
* **false negative** — the genuine shadow ``current/acme/user.proto``
  resolves to the *same* logical name ``acme/user.proto`` as the root, and
  ``-I current`` precedes ``-I vendor`` in search order, so the backend
  really does resolve the root's name to the other physical file. The
  basenames match trivially (``user.proto`` == ``user.proto``) but the
  candidate probed is ``current/user.proto``, which does not exist — so the
  detector returns ``None`` and the guard never fires.

**U14-2** (``compile.py:356-386``). ``_detect_same_basename_collision``
takes only ``paths``; ``proto_paths`` is not a parameter and is never
consulted, and ``compile_protos_to_result`` runs it *before*
``_detect_root_transitive_shadow`` and before any backend call, so ``-I``
cannot rescue it. Its docstring justifies the refusal by claiming "the
parent-directory auto-include logic produces ambiguous ``fd.name``
resolution" — but when the user supplies ``-I /repo``, that include comes
first and ``/repo/v1/common.proto`` / ``/repo/v2/common.proto`` resolve to
the distinct names ``v1/common.proto`` / ``v2/common.proto``. There is no
ambiguity for the guard to protect against, yet the schema is refused.

Not specified, in either case. The shadow guard entered the codebase in
``4d8917c`` as adversarial-review follow-up ADV-2, described there as
detecting when the root "would silently shadow the root's
source_code_info entry" — a logical-name statement; the basename
comparison is the implementation shortcut, not the contract. Nothing in
``docs/plans/`` mandates basename semantics for either guard.

**Backend exercised: protoxy 0.7.x only.** ``protoc`` is not on PATH in
this environment, so the ``protoc`` arm is unexercised here. This costs
the pins nothing: every assertion below that can fail *today* fails inside
the pre-flight, which returns before either backend is reached, and the
detector-level pins are pure path arithmetic with no backend at all. The
two backend-guarded tests use the established
``skipif(not _cli_utils._has_protoxy())`` pattern from
``tests/schema/lint/test_compile_multi.py``.

Corroborating evidence from the backend itself (protoxy 0.7.x, pre-flight
bypassed by calling ``_compile_with_protoxy`` directly):

* U14-1 false-positive layout compiles cleanly to
  ``root_names=('acme/user.proto',)``, package ``acme``, ``['VendorUser']``.
* U14-1 false-negative layout raises
  ``ProtoxyError: path '.../vendor/acme/user.proto' is shadowed by
  '.../current/acme/user.proto' in the include paths`` — protoxy names the
  shadow the pre-flight missed, and uses logical-name semantics to do it.
* U14-2 layout compiles cleanly to
  ``root_names=('v1/common.proto', 'v2/common.proto')`` with packages
  ``v1`` and ``v2``.

``TestPreFlightBoundariesThatMustSurvive`` at the bottom is NOT a pin: it
is a live guard rail for whoever fixes these, locking the cases where each
refusal is correct so the fix relaxes the guards without deleting them.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protokit import _cli_utils
from protokit.schema.compile import (
    _detect_root_transitive_shadow,
    compile_protos_to_result,
)

_REQUIRES_PROTOXY = pytest.mark.skipif(
    not _cli_utils._has_protoxy(),
    reason="optional [compiler] extra not installed",
)


# ---------------------------------------------------------------------------
# Layout builders
# ---------------------------------------------------------------------------


def _shadow_layout(
    root_dir: Path, *, unrelated: bool, real_shadow: bool,
) -> tuple[Path, list[str]]:
    """Build the U14-1 vendor/current layout.

    Returns ``(root_proto, proto_paths)`` where ``root_proto`` is
    ``vendor/acme/user.proto`` and ``proto_paths`` is
    ``[current, vendor]`` — ``current`` FIRST, which is what makes a
    same-logical-name file under ``current`` an actual shadow.
    """
    (root_dir / "vendor" / "acme").mkdir(parents=True)
    (root_dir / "current" / "acme").mkdir(parents=True)
    root = root_dir / "vendor" / "acme" / "user.proto"
    root.write_text(
        'syntax = "proto3";\npackage acme;\n'
        "message VendorUser { int32 a = 1; }\n"
    )
    if real_shadow:
        # Same logical name as the root (acme/user.proto), reachable via
        # the FIRST -I entry — a genuine shadow.
        (root_dir / "current" / "acme" / "user.proto").write_text(
            'syntax = "proto3";\npackage acme;\n'
            "message CurrentUser { int32 a = 1; }\n"
        )
    if unrelated:
        # Logical name "user.proto" — shares the root's BASENAME but not
        # its logical name. Cannot shadow anything the root owns.
        (root_dir / "current" / "user.proto").write_text(
            'syntax = "proto3";\npackage unrelated;\n'
            "message Unrelated { int32 a = 1; }\n"
        )
    return root, [str(root_dir / "current"), str(root_dir / "vendor")]


def _multi_root_layout(root_dir: Path) -> tuple[list[Path], list[str]]:
    """Build the U14-2 ``/repo/v1`` + ``/repo/v2`` layout.

    Returns ``(paths, proto_paths)`` — two roots sharing the basename
    ``common.proto`` under a single ``-I /repo``.
    """
    repo = root_dir / "repo"
    (repo / "v1").mkdir(parents=True)
    (repo / "v2").mkdir(parents=True)
    (repo / "v1" / "common.proto").write_text(
        'syntax = "proto3";\npackage v1;\nmessage Common { int32 a = 1; }\n'
    )
    (repo / "v2" / "common.proto").write_text(
        'syntax = "proto3";\npackage v2;\n'
        "message Common { int32 a = 1; string b = 2; }\n"
    )
    return (
        [repo / "v1" / "common.proto", repo / "v2" / "common.proto"],
        [str(repo)],
    )


def _effective_includes(paths: list[Path], proto_paths: list[str]) -> list[str]:
    """Reproduce the backend's include list: user ``-I`` first, then parents.

    Mirrors ``_compile_with_protoxy`` / ``_compile_with_protoc``
    (``_cli_utils.py:406-428``): ``includes = [*include_paths, *parents]``
    with parents deduplicated in input order.
    """
    parents = list(dict.fromkeys(str(p.parent) for p in paths))
    return [*proto_paths, *parents]


# ---------------------------------------------------------------------------
# U14-1 — basename shadow detection
# ---------------------------------------------------------------------------


class TestU141BasenameShadowDetection:
    """``_detect_root_transitive_shadow`` compares basenames, not ``fd.name``."""

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "U14-1: _detect_root_transitive_shadow (compile.py:342) probes "
            "Path(inc) / root.name, so an include-path file that merely "
            "shares the root's BASENAME is reported as a shadow even when "
            "its logical fd.name (user.proto) cannot collide with the "
            "root's (acme/user.proto). False positive."
        ),
    )
    def test_unrelated_same_basename_file_is_not_a_shadow(
        self, tmp_path: Path,
    ) -> None:
        """An unrelated ``current/user.proto`` must not shadow ``acme/user.proto``.

        Mechanism: the two files resolve to DIFFERENT logical names under
        the very include list the backend uses, so no ``fd.name``
        collision is possible. Anything the detector reports here is an
        artefact of the basename comparison.
        """
        root, proto_paths = _shadow_layout(
            tmp_path, unrelated=True, real_shadow=False,
        )
        includes = _effective_includes([root], proto_paths)
        unrelated = tmp_path / "current" / "user.proto"

        # Preconditions — true today; they establish that the layout really
        # is a non-collision before the pin asserts the detector agrees.
        assert _cli_utils._resolve_expected_name(root, includes) == (
            "acme/user.proto"
        )
        assert _cli_utils._resolve_expected_name(unrelated, includes) == (
            "user.proto"
        )

        # THE PIN: distinct logical names ⇒ no shadow.
        assert _detect_root_transitive_shadow([root], proto_paths) is None

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "U14-1: the basename false positive is not merely a noisy "
            "diagnostic — compile_protos_to_result early-returns on it, so "
            "a schema both backends compile cleanly is refused with "
            "root_files=() and a root_transitive_shadow error."
        ),
    )
    @_REQUIRES_PROTOXY
    def test_false_positive_refuses_a_schema_the_backend_compiles(
        self, tmp_path: Path,
    ) -> None:
        """The refusal blocks a compile protoxy performs without complaint.

        With the pre-flight bypassed, protoxy resolves this root to
        ``acme/user.proto`` (package ``acme``, message ``VendorUser``).
        The guard must not stand in front of that.
        """
        root, proto_paths = _shadow_layout(
            tmp_path, unrelated=True, real_shadow=False,
        )

        result = compile_protos_to_result([root], proto_paths)

        assert [
            d.category for d in result.diagnostics
            if d.category == "root_transitive_shadow"
        ] == []
        assert result.root_files == ("acme/user.proto",)
        assert result.pool.FindFileByName("acme/user.proto").package == "acme"

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "U14-1: the genuine shadow is MISSED. current/acme/user.proto "
            "resolves to the root's own logical name acme/user.proto via "
            "the first -I entry, but the detector probes current/user.proto "
            "(basename only), which does not exist, so it returns None. "
            "False negative; protoxy itself raises 'is shadowed by' on this "
            "same layout."
        ),
    )
    def test_real_logical_name_shadow_is_detected(
        self, tmp_path: Path,
    ) -> None:
        """``current/acme/user.proto`` genuinely shadows the root.

        Mechanism: both files resolve to ``acme/user.proto``, and
        ``current`` precedes ``vendor`` in include order, so the backend
        binds that name to the wrong physical file. This is precisely the
        hazard ``_detect_root_transitive_shadow``'s docstring describes.
        """
        root, proto_paths = _shadow_layout(
            tmp_path, unrelated=False, real_shadow=True,
        )
        includes = _effective_includes([root], proto_paths)
        shadow = tmp_path / "current" / "acme" / "user.proto"

        # Preconditions — true today: same logical name, shadow wins the
        # include-order race.
        assert _cli_utils._resolve_expected_name(root, includes) == (
            "acme/user.proto"
        )
        assert _cli_utils._resolve_expected_name(shadow, includes) == (
            "acme/user.proto"
        )
        assert includes.index(str(shadow.parent.parent)) < includes.index(
            str(root.parent.parent)
        )

        # THE PIN: the guard must fire, and must name the shadowing file.
        findings = _detect_root_transitive_shadow([root], proto_paths)
        assert findings is not None
        reported = {c for _root, candidates in findings for c in candidates}
        assert shadow in reported


# ---------------------------------------------------------------------------
# U14-2 — same-basename collision ignores ``proto_paths``
# ---------------------------------------------------------------------------


class TestU142SameBasenameCollisionIgnoresProtoPaths:
    """``_detect_same_basename_collision`` never sees ``-I``, so it over-refuses."""

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "U14-2: _detect_same_basename_collision (compile.py:356) takes "
            "only `paths` — proto_paths is not a parameter — and "
            "compile_protos_to_result runs it before the shadow guard and "
            "before any backend, so -I /repo cannot rescue roots that "
            "resolve to the distinct names v1/common.proto and "
            "v2/common.proto."
        ),
    )
    def test_distinct_logical_names_under_shared_include_are_not_a_collision(
        self, tmp_path: Path,
    ) -> None:
        """``-I /repo`` disambiguates ``v1/`` from ``v2/``; no ambiguity exists.

        Mechanism: the guard's docstring justifies the refusal with
        "ambiguous ``fd.name`` resolution", but under the include list the
        backend actually uses the two roots resolve to different names.
        """
        paths, proto_paths = _multi_root_layout(tmp_path)
        includes = _effective_includes(paths, proto_paths)

        # Precondition — true today: no ambiguity to protect against.
        assert _cli_utils._expected_root_names_ordered(paths, includes) == [
            "v1/common.proto",
            "v2/common.proto",
        ]

        result = compile_protos_to_result(paths, proto_paths)

        # THE PIN: distinct logical names ⇒ no collision refusal.
        assert [
            d.category for d in result.diagnostics
            if d.category == "same_basename_collision"
        ] == []

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "U14-2: the collision pre-flight early-returns with "
            "root_files=() / pool_file_names=(), refusing a multi-root "
            "schema protoxy compiles cleanly to v1/common.proto (package "
            "v1) and v2/common.proto (package v2)."
        ),
    )
    @_REQUIRES_PROTOXY
    def test_both_roots_reach_the_pool_with_distinct_packages(
        self, tmp_path: Path,
    ) -> None:
        """Both versioned roots must compile, each under its own package."""
        paths, proto_paths = _multi_root_layout(tmp_path)

        result = compile_protos_to_result(paths, proto_paths)

        assert result.root_files == ("v1/common.proto", "v2/common.proto")
        assert result.pool.FindFileByName("v1/common.proto").package == "v1"
        assert result.pool.FindFileByName("v2/common.proto").package == "v2"


# ---------------------------------------------------------------------------
# Guard rails for the eventual fix — these PASS today and must keep passing.
# ---------------------------------------------------------------------------


class TestPreFlightBoundariesThatMustSurvive:
    """The cases where each pre-flight refusal is CORRECT.

    Not pins. Whoever fixes U14-1 / U14-2 must relax the guards to
    logical-name semantics, not delete them — these two layouts are
    genuinely ambiguous and must stay refused. Under a logical-name
    rewrite both still collide, because with no user ``-I`` the effective
    include list is the auto-added parents and each root resolves to its
    bare basename.
    """

    def test_no_include_paths_multi_root_collision_still_refused(
        self, tmp_path: Path,
    ) -> None:
        """Without ``-I /repo`` both roots resolve to ``common.proto``.

        protoxy agrees: with no ``-I`` it raises
        ``ProtoxyError: path '.../v2/common.proto' is shadowed by
        '.../v1/common.proto' in the include paths``.
        """
        paths, _proto_paths = _multi_root_layout(tmp_path)
        includes = _effective_includes(paths, [])

        assert _cli_utils._expected_root_names_ordered(paths, includes) == [
            "common.proto",
            "common.proto",
        ]

        result = compile_protos_to_result(paths)

        assert result.root_files == ()
        assert [d.category for d in result.diagnostics] == [
            "same_basename_collision",
        ]

    def test_true_shadow_at_include_root_still_refused(
        self, tmp_path: Path,
    ) -> None:
        """Basename and logical name coincide here, so the guard is right.

        Root ``a/shared.proto`` with ``-I b`` where ``b/shared.proto`` is a
        different physical file: both resolve to ``shared.proto`` and
        ``b`` wins the include-order race. This is the layout
        ``tests/schema/lint/test_compile_include_source_info.py``'s
        ``TestRootTransitiveShadow`` already locks; it is a TRUE positive
        and survives a logical-name rewrite unchanged.
        """
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        root = dir_a / "shared.proto"
        root.write_text(
            'syntax = "proto3";\npackage a;\nmessage Root { int32 x = 1; }\n'
        )
        (dir_b / "shared.proto").write_text(
            'syntax = "proto3";\npackage shadow;\nmessage Other {}\n'
        )
        proto_paths = [str(dir_b)]
        includes = _effective_includes([root], proto_paths)

        assert _cli_utils._resolve_expected_name(root, includes) == (
            "shared.proto"
        )
        assert _cli_utils._resolve_expected_name(
            dir_b / "shared.proto", includes,
        ) == "shared.proto"

        findings = _detect_root_transitive_shadow([root], proto_paths)

        assert findings is not None
        reported = {c for _root, candidates in findings for c in candidates}
        assert dir_b / "shared.proto" in reported
