"""Tests for protokit.schema.profiles."""

from __future__ import annotations

from google.protobuf import descriptor_pool

from protokit.message.model import FieldPath
from protokit.schema import (
    CompatibilityLevel,
    CompatibilityPolicy,
    Direction,
    Finding,
    Severity,
    filter_for_level,
)
from tests.schema.helpers import T, build_message


ROOT = FieldPath(segments=())


def _f(rule_id: str, sev: Severity, direction: Direction) -> Finding:
    return Finding(path=ROOT, rule_id=rule_id, severity=sev,
                   direction=direction, message="")


# ---------------------------------------------------------------------------
# filter_for_level
# ---------------------------------------------------------------------------


class TestFilterForLevel:
    def test_wire_keeps_only_wire(self) -> None:
        findings = [
            _f("w", Severity.WIRE, Direction.BOTH),
            _f("s", Severity.SEMANTIC, Direction.BACKWARD),
            _f("p", Severity.POLICY, Direction.BOTH),
        ]
        out = filter_for_level(findings, CompatibilityLevel.WIRE)
        assert {f.rule_id for f in out} == {"w"}

    def test_consumer_safe_excludes_forward_and_policy(self) -> None:
        findings = [
            _f("rm", Severity.SEMANTIC, Direction.BACKWARD),
            _f("add", Severity.SEMANTIC, Direction.FORWARD),
            _f("opt", Severity.POLICY, Direction.BOTH),
            _f("wire", Severity.WIRE, Direction.BOTH),
        ]
        out = filter_for_level(findings, CompatibilityLevel.CONSUMER_SAFE)
        assert {f.rule_id for f in out} == {"rm", "wire"}

    def test_producer_safe_excludes_backward_and_policy(self) -> None:
        findings = [
            _f("rm", Severity.SEMANTIC, Direction.BACKWARD),
            _f("add", Severity.SEMANTIC, Direction.FORWARD),
            _f("wire", Severity.WIRE, Direction.BOTH),
        ]
        out = filter_for_level(findings, CompatibilityLevel.PRODUCER_SAFE)
        assert {f.rule_id for f in out} == {"add", "wire"}

    def test_strict_keeps_everything(self) -> None:
        findings = [
            _f("a", Severity.WIRE, Direction.BOTH),
            _f("b", Severity.SEMANTIC, Direction.BACKWARD),
            _f("c", Severity.SEMANTIC, Direction.FORWARD),
            _f("d", Severity.POLICY, Direction.BOTH),
        ]
        out = filter_for_level(findings, CompatibilityLevel.STRICT)
        assert len(out) == 4


# ---------------------------------------------------------------------------
# CompatibilityPolicy
# ---------------------------------------------------------------------------


def _make_pair(
    *, old_field_name: str | None = None, new_field_name: str | None = None,
) -> tuple[descriptor_pool.DescriptorPool, descriptor_pool.DescriptorPool]:
    old = descriptor_pool.DescriptorPool()
    new = descriptor_pool.DescriptorPool()
    if old_field_name:
        build_message(old, "t.M", fields=[
            {"name": old_field_name, "number": 1, "type": T.TYPE_STRING},
        ])
    else:
        build_message(old, "t.M", fields=[])
    if new_field_name:
        build_message(new, "t.M", fields=[
            {"name": new_field_name, "number": 1, "type": T.TYPE_STRING},
        ])
    else:
        build_message(new, "t.M", fields=[])
    return old, new


class TestCompatibilityPolicyDefaults:
    def test_defaults(self) -> None:
        policy = CompatibilityPolicy()
        # Default matches the CLI: protect old consumers out of the box.
        assert policy.base is CompatibilityLevel.CONSUMER_SAFE
        assert tuple(policy.custom_rules) == ()
        assert tuple(policy.ignore_paths) == ()

    def test_list_inputs_are_frozen_to_tuples(self) -> None:
        """Pass mutable lists at construction; policy must snapshot them."""
        rules = [("rule1", lambda ctx: None)]
        ignores = ["debug"]
        policy = CompatibilityPolicy(
            custom_rules=rules,
            ignore_paths=ignores,
        )
        assert isinstance(policy.custom_rules, tuple)
        assert isinstance(policy.ignore_paths, tuple)
        # Mutating the caller's list must not affect the policy.
        rules.append(("sneaky", lambda ctx: None))
        ignores.append("x")
        assert len(policy.custom_rules) == 1
        assert len(policy.ignore_paths) == 1


class TestCompatibilityPolicyCheck:
    def test_runs_check_with_base_level(self) -> None:
        old, new = _make_pair(old_field_name="x", new_field_name=None)
        policy = CompatibilityPolicy(base=CompatibilityLevel.CONSUMER_SAFE)
        report = policy.check(old, "t.M", new, "t.M")
        assert any(f.rule_id == "field_removed" for f in report.findings)
        assert report.level is CompatibilityLevel.CONSUMER_SAFE

    def test_producer_safe_filters_field_removed(self) -> None:
        old, new = _make_pair(old_field_name="x", new_field_name=None)
        policy = CompatibilityPolicy(base=CompatibilityLevel.PRODUCER_SAFE)
        report = policy.check(old, "t.M", new, "t.M")
        # field_removed is BACKWARD — filtered out by PRODUCER_SAFE.
        assert all(f.rule_id != "field_removed" for f in report.findings)

    def test_ignore_paths_suppresses(self) -> None:
        old, new = _make_pair(old_field_name="debug", new_field_name=None)
        policy = CompatibilityPolicy(
            base=CompatibilityLevel.STRICT,
            ignore_paths=("debug",),
        )
        report = policy.check(old, "t.M", new, "t.M")
        assert report.is_compatible

    def test_custom_field_plugin_invoked(self) -> None:
        old, new = _make_pair(old_field_name="x", new_field_name="x")
        emitted: list[str] = []

        def visit(ctx) -> None:
            emitted.append(str(ctx.path))

        policy = CompatibilityPolicy(
            base=CompatibilityLevel.STRICT,
            custom_rules=(("visit", visit),),
        )
        policy.check(old, "t.M", new, "t.M")
        assert "x" in emitted

    def test_custom_field_plugin_emits_through_filter(self) -> None:
        old, new = _make_pair(old_field_name="x", new_field_name="x")

        def reject(ctx) -> None:
            if ctx.old_field is not None and ctx.old_field.name == "x":
                ctx.emit(severity=Severity.WIRE, message="x is forbidden")

        policy = CompatibilityPolicy(
            base=CompatibilityLevel.WIRE,
            custom_rules=(("reject_x", reject),),
        )
        report = policy.check(old, "t.M", new, "t.M")
        assert any(f.rule_id == "reject_x" for f in report.findings)

    def test_policy_is_frozen(self) -> None:
        import pytest
        policy = CompatibilityPolicy()
        with pytest.raises(Exception):
            policy.base = CompatibilityLevel.WIRE  # type: ignore[misc]

    def test_check_raises_on_missing_type(self) -> None:
        """Policy.check propagates ValueError for missing types."""
        import pytest
        old = descriptor_pool.DescriptorPool()
        new = descriptor_pool.DescriptorPool()
        build_message(old, "t.M", fields=[])
        build_message(new, "t.M", fields=[])
        policy = CompatibilityPolicy()
        with pytest.raises(ValueError, match="old_type"):
            policy.check(old, "t.Missing", new, "t.M")
        with pytest.raises(ValueError, match="new_type"):
            policy.check(old, "t.M", new, "t.Missing")
