"""End-to-end CLI tests for the R7 PACKAGE_SAME_* family.

D6b U4b shipped the R7 PACKAGE_SAME_* family (7 rules covering
cross-language namespace consistency). D6b U7 (0.3.0) flipped the
default by adding ``package_same`` to :data:`BUILTIN_PACKS`, so
bare ``protokit lint --profile recommended <inputs>`` now fires R7
on disagreeing fixtures.

Exercises:

- ``--rule-pack=protokit.schema.lint.rules.package_same`` is now an
  idempotent explicit-load path (the engine's module-name short-
  circuit + ``LintProfile.compose``'s frozenset union both absorb
  the duplicate registration).
- ``--proto`` mode + ``--descriptor-set`` mode produce identical R7
  findings on the same fixture (input-mode parity per SC 14 of the
  per-unit plan).
- ``--profile recommended`` and ``--profile default`` both fire R7
  per the ``@lint_rule`` metadata.
- Rendered message string byte-matches buf v1.69.0's emit (recorded
  at ``_buf_smoke/recorded/mixed-value.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
from google.protobuf import descriptor_pb2

from protokit.schema.compile import compile_protos_to_result
from protokit.schema.lint.cli import main as lint_main
from tests.schema.lint.rules.fixtures.package_same.proto_templates import (
    mixed_value,
)

# ---------------------------------------------------------------------------
# Fixture helpers (per-test scope so each test gets a fresh tmp dir)
# ---------------------------------------------------------------------------


def _write_sources(tmp_path: Path, sources: dict[str, str]) -> Path:
    """Materialize a multi-file ``sources`` dict under ``tmp_path``.

    Returns the parent directory so callers can pass it to
    ``--proto-path`` and the per-file paths to the lint CLI's
    positional argument.
    """
    for fname, text in sources.items():
        (tmp_path / fname).write_text(text)
    return tmp_path


def _compile_to_descriptor_set(tmp_path: Path, sources: dict[str, str]) -> Path:
    """Compile ``sources`` to a serialized ``.descriptor_set`` file.

    Mirrors ``tests/schema/lint/cli/conftest._compile_to_descriptor_set``
    inline since this test module lives one directory up from the
    CLI conftest (no shared fixture available). Includes transitive
    imports to mirror the protoc default; the fixtures here have no
    cross-file dependencies, so include_imports has no practical
    effect — but matching the conftest's shape avoids divergence-
    risk if the helper grows new semantics.
    """
    _write_sources(tmp_path, sources)
    result = compile_protos_to_result(
        paths=[tmp_path / fname for fname in sources],
        proto_paths=(str(tmp_path),),
    )
    error_diags = [d for d in result.diagnostics if d.level == "error"]
    assert not error_diags, f"fixture compile failed: {error_diags}"
    fds = descriptor_pb2.FileDescriptorSet()
    for fname in result.pool_file_names:
        fd_proto = descriptor_pb2.FileDescriptorProto()
        result.pool.FindFileByName(fname).CopyToProto(fd_proto)
        fds.file.add().CopyFrom(fd_proto)
    out = tmp_path / "package_same.descriptor_set"
    out.write_bytes(fds.SerializeToString())
    return out


# ---------------------------------------------------------------------------
# Idempotent explicit-load — --rule-pack is now a no-op redundant load
# ---------------------------------------------------------------------------


class TestRulePackExplicitLoadIsIdempotent:
    """Explicit ``--rule-pack=...package_same`` is idempotent post-0.3.0.

    Since D6b U7 added ``package_same`` to ``BUILTIN_PACKS``, the
    explicit ``--rule-pack`` flag for a built-in pack becomes a
    redundant explicit load — exercised here as an idempotency
    regression. THREE coupled mechanisms preserve the no-op contract;
    removing any one re-introduces a different failure mode, so a
    future engineer simplifying one without re-checking the others
    can silently break the contract:

    1. **CLI-level dedup at** ``cli.py:841-846`` (the load-bearing
       guard added at D6b U7): ``if user_pack.__name__ not in
       {p.__name__ for p in loaded_packs}: loaded_packs.append(user_pack)``.
       This is what keeps the ``loaded_packs_tuple`` length aligned
       with ``_active_rule_ids_per_pack(...)``'s dict size (the dict
       is keyed by ``pack.__name__`` and would silently de-dup).
       Without this guard, the R25 multi-pack provenance line at
       ``cli.py:987`` fails ``zip(loaded_packs_tuple,
       active_per_pack.values(), strict=True)`` with
       ``ValueError('zip() argument 2 is shorter than argument 1')``
       — the original D6b U7-flip-surfaced bug.
    2. **Engine-level idempotent load** at ``engine.py:241-242``:
       ``if module.__name__ in self._loaded_module_names: return``.
       Prevents the engine from registering the same pack's rules
       twice (which would raise ``DuplicateRuleError``). Independent
       of the CLI guard above — applies to any caller, not just CLI.
    3. **Profile-level frozenset union** at ``model.py:717-719``:
       :meth:`LintProfile.compose` uses ``frozenset().union(*(p.rule_ids
       for p in profiles))``. Backstop that absorbs duplicate
       per-pack profiles even if the upper-layer dedup were
       removed. Defense-in-depth, not the primary mechanism.

    These four tests verify the observable contract (correct
    finding count, correct exit code) holds across
    descriptor-set / proto / both-profiles / message-byte-format
    surfaces.
    """

    def test_descriptor_set_mode_recommended_profile(
        self, tmp_path: Path,
    ) -> None:
        sources = mixed_value(
            "go_package",
            values=("github.com/x/X", "github.com/x/Y", "github.com/x/X"),
            package="smoke.optin",
        )
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package_same",
                "--profile", "recommended",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        # Exit 1 because the rule severity is ERROR (R20 ladder).
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        r7_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "package/same-go-package"
        ]
        assert len(r7_findings) == 3, (
            f"expected 3 findings (one per file), got {len(r7_findings)}"
        )

    def test_descriptor_set_mode_default_profile(
        self, tmp_path: Path,
    ) -> None:
        sources = mixed_value(
            "go_package",
            values=("github.com/x/X", "github.com/x/Y", "github.com/x/X"),
            package="smoke.default_optin",
        )
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package_same",
                "--profile", "default",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        r7_findings = [
            f for f in payload["findings"]
            if f["rule_id"] == "package/same-go-package"
        ]
        assert len(r7_findings) == 3

    def test_proto_mode_produces_same_findings_as_descriptor_set(
        self, tmp_path: Path,
    ) -> None:
        """``--proto`` and descriptor-set mode produce identical R7 findings.

        Per SC 14 (``include_source_info`` independence): R7's input is
        ``FileOptions`` attrs which are first-class FileDescriptor
        fields and do NOT require source-info preservation, so both
        input modes should fire R7 identically.
        """
        sources = mixed_value(
            "go_package",
            values=("github.com/x/X", "github.com/x/Y", "github.com/x/X"),
            package="smoke.modeparity",
        )
        # Build a descriptor set (mode 1).
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        ds_result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package_same",
                "--profile", "recommended",
                "--format", "json",
                str(descriptor_set),
            ],
        )
        assert ds_result.exit_code == 1, ds_result.output
        ds_findings = json.loads(ds_result.stdout)["findings"]

        # Now write .proto files separately and invoke --proto mode (mode 2).
        proto_dir = tmp_path / "proto_mode"
        proto_dir.mkdir()
        for fname, text in sources.items():
            (proto_dir / fname).write_text(text)
        proto_result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package_same",
                "--profile", "recommended",
                "--format", "json",
                "--proto",
                "-I", str(proto_dir),
                *(str(proto_dir / fname) for fname in sources),
            ],
        )
        assert proto_result.exit_code == 1, proto_result.output
        proto_findings = json.loads(proto_result.stdout)["findings"]

        # Compare per-rule + per-file presence + rendered message.
        # The lint_json output renders ``message`` already-formatted
        # and exposes ``location_file`` as a string, so the key
        # captures everything semantically meaningful for parity.
        def key(f: dict[str, object]) -> tuple[object, ...]:
            return (
                f["rule_id"],
                f.get("location_file"),
                f.get("message"),
            )

        ds_r7 = {
            key(f) for f in ds_findings
            if f["rule_id"].startswith("package/same-")
        }
        proto_r7 = {
            key(f) for f in proto_findings
            if f["rule_id"].startswith("package/same-")
        }
        assert ds_r7 == proto_r7, (
            f"mode parity broken:\n"
            f"  descriptor-set: {sorted(ds_r7)}\n"
            f"  --proto:        {sorted(proto_r7)}"
        )

    def test_message_template_matches_buf_byte_format(
        self, tmp_path: Path,
    ) -> None:
        """Rendered message string byte-matches buf v1.69.0's emit.

        The rule's message_template + the helper's values_payload
        composition must produce a line identical to what
        :file:`_buf_smoke/recorded/mixed-value.json` shows. Renderer
        runs over the human format which builds the string from the
        template; we re-render here against the recorded snapshot.
        """
        sources = mixed_value(
            "go_package",
            values=("github.com/x/X", "github.com/x/Y", "github.com/x/X"),
            package="smoke.mixed_value",  # match _buf_smoke/recorded fixture
        )
        descriptor_set = _compile_to_descriptor_set(tmp_path, sources)
        result = CliRunner().invoke(
            lint_main,
            [
                "--no-config",
                "--rule-pack=protokit.schema.lint.rules.package_same",
                "--profile", "recommended",
                str(descriptor_set),
            ],
        )
        assert result.exit_code == 1, result.output
        expected_msg = (
            'Files in package "smoke.mixed_value" have multiple values '
            '"github.com/x/X,github.com/x/Y" '
            'for option "go_package" and all values must be equal.'
        )
        assert expected_msg in result.stdout, (
            f"expected message text not in output:\n{result.stdout}"
        )
