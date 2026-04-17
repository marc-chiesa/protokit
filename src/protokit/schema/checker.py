"""Schema compatibility checker engine.

Walks the descriptor tree iteratively (stack-based, no recursion) and
dispatches rules at each traversal point. Field rules see pairs of
``FieldDescriptor``s (either side may be ``None`` for add/remove),
enum rules see pairs of ``EnumDescriptor``s, and message rules see
the message ``Descriptor``s themselves.

Two registration styles for custom rules:

- Emit-style plugins via ``register_field_rule`` /
  ``register_message_rule``: a single callable receives a context and
  calls ``ctx.emit(...)``. This is the primary public API and what
  rule packs use.
- Raw return-style rules via ``register_raw_field_rule`` (and the
  enum / message variants): a callable returns ``list[Finding]``.
  Built-in rules use this internally; advanced users can register
  here too.

Sharing and cycle handling: by default (``dedupe_by_type=False``)
findings on a shared nested type pair are emitted at every path
where the pair appears — "path-complete" reporting, so ignoring
one path doesn't silently hide breaks under a sibling. The
traversal processes each ``(old_full_name, new_full_name)`` pair
once and caches its findings with paths made relative to the
entry; later visits replay the cache with the new path prefix.
Cycle detection uses an in-progress set (DFS-path tracking), so a
self-referential type like ``TreeNode.children`` still terminates
in O(n). Pass ``dedupe_by_type=True`` to restore the original
single-emission-per-type behavior.

Map fields: the synthetic ``map_entry`` message is not descended into
directly. Instead, the checker dispatches field rules (and enum
rules when applicable) on the map-entry ``value`` sub-field at
``field_path.child("value")``, then pushes the value's
``message_type`` onto the stack for recursion if the value is a
message on both sides. This surfaces scalar-type, kind, and
option changes on map values that would otherwise slip through.

Profile filtering and ``CompatibilityPolicy`` live in
``protokit.schema.profiles``.
"""

from __future__ import annotations

import inspect
from dataclasses import replace as _dataclass_replace
from types import ModuleType
from typing import Iterable

from google.protobuf import descriptor as proto_descriptor
from google.protobuf import descriptor_pool

from protokit._descriptors import get_field_map, is_map_field
from protokit.message.model import Diagnostic, FieldPath
from protokit.schema.model import (
    CompatibilityLevel,
    CompatibilityReport,
    Finding,
)
from protokit.schema.plugins import (
    FieldPlugin,
    FieldRuleContext,
    MessagePlugin,
    MessageRuleContext,
    iter_rule_pack,
    make_emit,
)
from protokit.schema.profiles import filter_for_level
from protokit.schema.rules import (
    ENUM_RULES,
    FIELD_RULES,
    MESSAGE_RULES,
    EnumRuleFn,
    FieldRuleFn,
    MessageRuleFn,
    _close_caches,
    _open_caches,
)

FD = proto_descriptor.FieldDescriptor


class SchemaChecker:
    """Configurable compatibility checker.

    Built-in rules are registered by default. Add custom rules via
    ``register_field_rule`` / ``register_message_rule`` (emit-style
    plugins) or ``register_raw_field_rule`` and friends (return-style,
    advanced). Use ``load_rule_pack`` to pull in a module's ``RULES``.

    Attributes:
        level: The active ``CompatibilityLevel``. Mutable — assign
            before calling ``check()`` to switch profiles. The
            attribute is also set into the resulting
            ``CompatibilityReport.level``.
        dedupe_by_type: When False (default), findings on a shared
            nested type are emitted at **every** path where the type
            pair appears (path-complete reporting). When True, each
            type pair is processed once and only the first path's
            findings surface — the original "compatibility is a
            property of the type, not its position" behavior.
    """

    def __init__(
        self,
        *,
        level: CompatibilityLevel = CompatibilityLevel.STRICT,
        include_builtin: bool = True,
        dedupe_by_type: bool = False,
    ) -> None:
        """Construct a checker with the given profile and rule set.

        Args:
            level: Initial profile to filter findings by. Defaults to
                ``CompatibilityLevel.STRICT`` which surfaces every
                finding. Can be reassigned later via the ``level``
                attribute.
            include_builtin: When True (default), the 17 built-in
                rules from ``protokit.schema.rules`` are pre-registered.
                Pass False to start with an empty rule set — useful
                when you want only custom rules to fire.
            dedupe_by_type: When False (default), findings for a
                shared nested type are replayed at every path that
                references it — the path-complete behavior. When
                True, each type pair is processed once and only the
                first-encountered path gets findings, matching the
                original design-doc behavior where compatibility is
                treated as a property of the type definition, not
                its position in the tree.
        """
        self.level = level
        self.dedupe_by_type = dedupe_by_type
        # Return-style rules: built-ins seeded here; raw register methods
        # extend the lists in place.
        self._field_rules: list[tuple[str, FieldRuleFn]] = (
            list(FIELD_RULES) if include_builtin else []
        )
        self._enum_rules: list[tuple[str, EnumRuleFn]] = (
            list(ENUM_RULES) if include_builtin else []
        )
        self._message_rules: list[tuple[str, MessageRuleFn]] = (
            list(MESSAGE_RULES) if include_builtin else []
        )
        # Emit-style plugins: registered via the public API.
        self._field_plugins: list[tuple[str, FieldPlugin]] = []
        self._message_plugins: list[tuple[str, MessagePlugin]] = []

        self._ignore_paths: list[FieldPath] = []

    # ------------------------------------------------------------------
    # Public emit-style plugin registration
    # ------------------------------------------------------------------

    def register_field_rule(self, rule_id: str, plugin_fn: FieldPlugin) -> None:
        """Register an emit-style field-level plugin.

        The plugin receives a ``FieldRuleContext`` and calls
        ``ctx.emit(...)`` to record findings. Plugin exceptions and
        async-plugin misuse are captured into
        ``CompatibilityReport.warnings`` so comparison continues and
        the CLI can fail loudly.

        Args:
            rule_id: Identifier stored on every emitted ``Finding``.
                Should be unique within the checker for clean
                attribution; duplicates are allowed but produce
                ambiguous reports.
            plugin_fn: Callable matching ``FieldPlugin``:
                ``(FieldRuleContext) -> None``. Must be synchronous —
                ``async def`` plugins are rejected at registration
                time because the engine has no event loop to await
                them.

        Raises:
            TypeError: If ``plugin_fn`` is an async function.
        """
        self._reject_async(rule_id, plugin_fn)
        self._field_plugins.append((rule_id, plugin_fn))

    def register_message_rule(self, rule_id: str, plugin_fn: MessagePlugin) -> None:
        """Register an emit-style message-level plugin.

        Fires once per message visited during traversal, before
        descent into the message's fields. Same exception-safety
        guarantee as ``register_field_rule``.

        Args:
            rule_id: Identifier stored on every emitted ``Finding``.
            plugin_fn: Callable matching ``MessagePlugin``:
                ``(MessageRuleContext) -> None``. Must be synchronous.

        Raises:
            TypeError: If ``plugin_fn`` is an async function.
        """
        self._reject_async(rule_id, plugin_fn)
        self._message_plugins.append((rule_id, plugin_fn))

    @staticmethod
    def _reject_async(rule_id: str, plugin_fn: object) -> None:
        """Fail fast when someone tries to register an ``async def`` plugin.

        The engine is synchronous — an async plugin would return a
        coroutine from the call, the engine would never await it,
        and any ``ctx.emit(...)`` calls inside it would never run.
        We catch the common case here; dynamically-wrapped async
        callables are still caught at dispatch time by the
        coroutine check in ``_dispatch_*_plugin``.
        """
        if inspect.iscoroutinefunction(plugin_fn):
            raise TypeError(
                f"schema plugin '{rule_id}' is an async function; "
                "the checker is synchronous — wrap the async logic "
                "in a synchronous shim or run it outside the plugin."
            )

    def load_rule_pack(self, module: ModuleType) -> None:
        """Load every entry from ``module.RULES`` as a field plugin.

        Rule packs are plain Python modules with a ``RULES`` attribute
        holding a sequence of ``(rule_id, plugin_fn)`` pairs. Each pair
        is registered via :meth:`register_field_rule`.

        Args:
            module: An imported module exposing a ``RULES`` attribute.
                Typically obtained via ``importlib.import_module(...)``.

        Raises:
            AttributeError: If ``module`` has no ``RULES`` attribute.
            TypeError: If any ``RULES`` entry is not a
                ``(str, callable)`` pair. Propagated from
                :func:`protokit.schema.plugins.iter_rule_pack`.
        """
        for rule_id, plugin_fn in iter_rule_pack(module):
            self.register_field_rule(rule_id, plugin_fn)

    # ------------------------------------------------------------------
    # Raw return-style rule registration (advanced)
    # ------------------------------------------------------------------

    def register_raw_field_rule(self, rule_id: str, rule_fn: FieldRuleFn) -> None:
        """Register a return-style field rule (advanced API).

        Use this when you need the same call shape as the built-in
        rules — e.g., for performance-critical paths, or when a
        single rule needs to emit findings at multiple child paths
        (which the emit-style API doesn't support).

        Args:
            rule_id: Identifier for diagnostic purposes. Unlike
                emit-style rules, the rule_id is *not* stitched into
                the returned findings — the rule function is
                responsible for setting ``rule_id`` on each ``Finding``
                it returns.
            rule_fn: Callable matching ``FieldRuleFn``:
                ``(FieldDescriptor | None, FieldDescriptor | None,
                FieldPath) -> Iterable[Finding]``.
        """
        self._field_rules.append((rule_id, rule_fn))

    def register_raw_enum_rule(self, rule_id: str, rule_fn: EnumRuleFn) -> None:
        """Register a return-style enum-level rule (advanced API).

        Args:
            rule_id: Identifier for diagnostic purposes; not auto-stitched.
            rule_fn: Callable matching ``EnumRuleFn``:
                ``(EnumDescriptor | None, EnumDescriptor | None,
                FieldPath) -> Iterable[Finding]``.
        """
        self._enum_rules.append((rule_id, rule_fn))

    def register_raw_message_rule(self, rule_id: str, rule_fn: MessageRuleFn) -> None:
        """Register a return-style message-level rule (advanced API).

        Args:
            rule_id: Identifier for diagnostic purposes; not auto-stitched.
            rule_fn: Callable matching ``MessageRuleFn``:
                ``(Descriptor | None, Descriptor | None,
                FieldPath) -> Iterable[Finding]``.
        """
        self._message_rules.append((rule_id, rule_fn))

    # ------------------------------------------------------------------
    # Ignore paths
    # ------------------------------------------------------------------

    def ignore(self, path: str) -> None:
        """Suppress findings whose path begins with the given dotted prefix.

        Uses segment-name prefix matching. ``"debug"`` suppresses
        ``debug`` and every descendant path such as ``debug.inner``.
        ``"parent.debug"`` suppresses only under that specific parent.
        Filtering is applied after profile filtering, so a suppressed
        finding is also absent from the bucket properties.

        Args:
            path: Dotted path string. Must parse as a ``FieldPath``;
                see :meth:`protokit.message.model.FieldPath.parse` for
                the grammar. Schema paths never include bracket or
                map-key syntax.

        Raises:
            ValueError: If ``path`` cannot be parsed as a ``FieldPath``.
        """
        self._ignore_paths.append(FieldPath.parse(path))

    # ------------------------------------------------------------------
    # Checking
    # ------------------------------------------------------------------

    def check(
        self,
        old_pool: descriptor_pool.DescriptorPool,
        old_type: str,
        new_pool: descriptor_pool.DescriptorPool,
        new_type: str,
    ) -> CompatibilityReport:
        """Check compatibility between two message types in two pools.

        Resolves ``old_type`` in ``old_pool`` and ``new_type`` in
        ``new_pool``, then walks the descriptor tree dispatching every
        registered rule (built-in, raw, and emit-style plugins). The
        raw findings are filtered by the checker's ``level`` and
        ``ignore_paths`` before being assembled into the report.

        Args:
            old_pool: Descriptor pool containing the old schema.
            old_type: Fully-qualified message type name in
                ``old_pool`` (e.g. ``"acme.User"``).
            new_pool: Descriptor pool containing the new schema. May
                be the same object as ``old_pool`` for same-pool
                checks.
            new_type: Fully-qualified message type name in
                ``new_pool``. Use a different name from ``old_type``
                for cross-type comparisons (e.g., ``"acme.UserV1"``
                vs ``"acme.UserV2"``).

        Returns:
            A ``CompatibilityReport`` whose ``findings`` are already
            filtered by ``self.level`` and ``ignore_paths``. The
            report's ``level`` is set to ``self.level``.

        Raises:
            ValueError: If either type name cannot be resolved in its
                respective pool.
        """
        try:
            old_desc = old_pool.FindMessageTypeByName(old_type)
        except KeyError as exc:
            raise ValueError(
                f"old_type '{old_type}' not found in old_pool"
            ) from exc
        try:
            new_desc = new_pool.FindMessageTypeByName(new_type)
        except KeyError as exc:
            raise ValueError(
                f"new_type '{new_type}' not found in new_pool"
            ) from exc

        warnings_sink: list[Diagnostic] = []
        cache_token = _open_caches()
        try:
            raw = self._traverse(
                old_desc, new_desc, old_pool, new_pool, warnings_sink,
            )
        finally:
            _close_caches(cache_token)

        filtered = filter_for_level(raw, self.level)
        filtered = self._apply_ignore(filtered)
        return CompatibilityReport(
            level=self.level,
            findings=tuple(filtered),
            diagnostics=tuple(warnings_sink),
        )

    # ------------------------------------------------------------------
    # Internal traversal
    # ------------------------------------------------------------------

    def _traverse(
        self,
        root_old: proto_descriptor.Descriptor,
        root_new: proto_descriptor.Descriptor,
        old_pool: descriptor_pool.DescriptorPool,
        new_pool: descriptor_pool.DescriptorPool,
        warnings_sink: list[Diagnostic],
    ) -> list[Finding]:
        """Walk the descriptor tree and collect findings.

        Cycle detection uses an ``in_progress`` set (type pairs
        currently on the DFS path) — re-entering an in-progress pair
        is a cycle and gets skipped.

        Sharing is handled differently depending on
        ``self.dedupe_by_type``:

        - False (default, path-complete): process each type pair
          once, cache the resulting findings keyed by type pair with
          paths stored relative to the entry point, and replay the
          cached findings with the new prefix whenever the same
          pair appears under a different path.
        - True: use a flat visited set and skip every repeat visit
          after the first, matching the original design-doc
          behavior.

        The stack carries two kinds of entries in path-complete mode:
        ``("visit", old_m, new_m, path)`` to process a pair, and
        ``("post", key, entry_path, start_idx)`` as a sentinel that
        fires when the pair's subtree is fully processed so we can
        snapshot and cache the emitted findings.
        """
        findings: list[Finding] = []
        stack: list = [("visit", root_old, root_new, FieldPath(segments=()))]
        in_progress: set[tuple[str, str]] = set()
        dedupe_visited: set[tuple[str, str]] = set()
        # Per-pair cache: each entry is ``(rel_path, finding)`` where
        # ``rel_path`` is the path made relative to the entry's visit
        # point, or ``None`` if the finding's path lies outside the
        # entry subtree (e.g. a raw rule that emitted at an unrelated
        # path). ``None`` signals "preserve the original path on
        # replay" so we don't concatenate a new prefix onto a
        # finding that wasn't entry-rooted to begin with.
        cache: dict[
            tuple[str, str], list[tuple[FieldPath | None, Finding]]
        ] = {}

        while stack:
            entry = stack.pop()
            tag = entry[0]

            if tag == "post":
                _, key, entry_path, start_idx = entry
                in_progress.discard(key)
                # Snapshot everything emitted since we pushed this
                # sentinel and store each finding with a path
                # relative to this visit's entry so it can be
                # replayed at other paths.
                subtree = findings[start_idx:]
                cache[key] = [
                    (self._strip_path_prefix(f.path, entry_path), f)
                    for f in subtree
                ]
                continue

            _, old_m, new_m, path = entry
            key = (old_m.full_name, new_m.full_name)

            if self.dedupe_by_type:
                # One emission per type pair; also terminates cycles
                # because any repeat pop hits the visited set.
                if key in dedupe_visited:
                    continue
                dedupe_visited.add(key)
            else:
                if key in in_progress:
                    # Cycle — already traversing this type pair
                    # deeper up the stack. Don't recurse.
                    continue
                if key in cache:
                    # Replay the type pair's findings at this path.
                    for rel, finding in cache[key]:
                        if rel is None:
                            # Finding wasn't entry-rooted; preserve
                            # its original path instead of prefixing.
                            findings.append(finding)
                        else:
                            new_path = self._join_paths(path, rel)
                            findings.append(
                                _dataclass_replace(finding, path=new_path)
                            )
                    continue
                in_progress.add(key)
                # Sentinel fires after this pair's subtree completes.
                stack.append(("post", key, path, len(findings)))

            for _, rule_fn in self._message_rules:
                findings.extend(rule_fn(old_m, new_m, path))

            for rule_id, plugin_fn in self._message_plugins:
                self._dispatch_message_plugin(
                    rule_id, plugin_fn, old_m, new_m, path,
                    old_pool, new_pool, findings, warnings_sink,
                )

            self._compare_fields(
                old_m, new_m, path, old_pool, new_pool,
                findings, warnings_sink, stack,
            )

        return findings

    @staticmethod
    def _strip_path_prefix(
        absolute: FieldPath, prefix: FieldPath,
    ) -> FieldPath | None:
        """Return ``absolute`` made relative to ``prefix``, or ``None``.

        When ``absolute`` starts with ``prefix`` (the normal case —
        a finding emitted under the current visit's entry path),
        returns the trailing segments as a new ``FieldPath``. When
        ``absolute`` does not start with ``prefix`` (e.g. a raw rule
        emitted at an unrelated path), returns ``None`` — the caller
        treats this as "preserve the original path on replay" rather
        than concatenating a new prefix onto a non-entry-rooted
        path.
        """
        pref_segs = prefix.segments
        abs_segs = absolute.segments
        if len(abs_segs) < len(pref_segs):
            return None
        for i, seg in enumerate(pref_segs):
            if abs_segs[i] != seg:
                return None
        return FieldPath(segments=abs_segs[len(pref_segs):])

    @staticmethod
    def _join_paths(prefix: FieldPath, suffix: FieldPath) -> FieldPath:
        """Concatenate two ``FieldPath`` objects."""
        return FieldPath(segments=prefix.segments + suffix.segments)

    def _compare_fields(
        self,
        old_m: proto_descriptor.Descriptor,
        new_m: proto_descriptor.Descriptor,
        path: FieldPath,
        old_pool: descriptor_pool.DescriptorPool,
        new_pool: descriptor_pool.DescriptorPool,
        findings: list[Finding],
        warnings_sink: list[Diagnostic],
        stack: list,
    ) -> None:
        old_fields = get_field_map(old_m)
        new_fields = get_field_map(new_m)
        names = sorted(set(old_fields) | set(new_fields))
        for name in names:
            old_fd = old_fields.get(name)
            new_fd = new_fields.get(name)
            field_path = path.child(name)

            for _, rule_fn in self._field_rules:
                findings.extend(rule_fn(old_fd, new_fd, field_path))

            for rule_id, plugin_fn in self._field_plugins:
                self._dispatch_field_plugin(
                    rule_id, plugin_fn, old_fd, new_fd, field_path,
                    old_pool, new_pool, findings, warnings_sink,
                )

            if old_fd is None or new_fd is None:
                continue

            if old_fd.type == FD.TYPE_ENUM and new_fd.type == FD.TYPE_ENUM:
                for _, rule_fn in self._enum_rules:
                    findings.extend(rule_fn(
                        old_fd.enum_type, new_fd.enum_type, field_path,
                    ))
                continue

            if old_fd.type != FD.TYPE_MESSAGE or new_fd.type != FD.TYPE_MESSAGE:
                continue

            old_is_map = is_map_field(old_fd)
            new_is_map = is_map_field(new_fd)
            if old_is_map != new_is_map:
                # map_to_repeated / repeated_to_singular already fired;
                # no shared subtree to recurse into.
                continue

            if old_is_map and new_is_map:
                self._compare_map_value(
                    old_fd, new_fd, field_path,
                    old_pool, new_pool, findings, warnings_sink, stack,
                )
                continue

            stack.append(
                ("visit", old_fd.message_type, new_fd.message_type, field_path)
            )

    def _compare_map_value(
        self,
        old_fd: proto_descriptor.FieldDescriptor,
        new_fd: proto_descriptor.FieldDescriptor,
        path: FieldPath,
        old_pool: descriptor_pool.DescriptorPool,
        new_pool: descriptor_pool.DescriptorPool,
        findings: list[Finding],
        warnings_sink: list[Diagnostic],
        stack: list,
    ) -> None:
        """Dispatch field rules + push recursion for a map's value sub-field.

        The synthetic ``MapEntry`` message has ``key`` and ``value``
        fields. ``key`` is always a scalar and not user-visible, but
        ``value`` carries the user's declared map value type — so we
        treat it like any other field for rule dispatch. If the
        value is itself a message, we also push its message_type
        onto the stack so the engine recurses into it.

        Path: findings on the value sub-field use
        ``path.child("value")`` — the map field itself stays at
        ``path`` and any value-type concern appears nested under
        it.
        """
        old_value = old_fd.message_type.fields_by_name.get("value")
        new_value = new_fd.message_type.fields_by_name.get("value")
        if old_value is None or new_value is None:
            return
        value_path = path.child("value")

        # Run all registered field rules + plugins on the value pair.
        # Rules that guard on is_map_field won't fire here (the value
        # isn't a map); all the type / cardinality / option rules do.
        for _, rule_fn in self._field_rules:
            findings.extend(rule_fn(old_value, new_value, value_path))
        for rule_id, plugin_fn in self._field_plugins:
            self._dispatch_field_plugin(
                rule_id, plugin_fn, old_value, new_value, value_path,
                old_pool, new_pool, findings, warnings_sink,
            )

        # Enum-rule dispatch for TYPE_ENUM values, mirroring the
        # non-map enum path in _compare_fields.
        if old_value.type == FD.TYPE_ENUM and new_value.type == FD.TYPE_ENUM:
            for _, rule_fn in self._enum_rules:
                findings.extend(rule_fn(
                    old_value.enum_type, new_value.enum_type, value_path,
                ))

        # If the value is a message on both sides, recurse into it.
        if (old_value.type == FD.TYPE_MESSAGE
                and new_value.type == FD.TYPE_MESSAGE):
            stack.append((
                "visit",
                old_value.message_type, new_value.message_type, value_path,
            ))

    # ------------------------------------------------------------------
    # Plugin dispatch (with exception safety)
    # ------------------------------------------------------------------

    def _dispatch_field_plugin(
        self,
        rule_id: str,
        plugin_fn: FieldPlugin,
        old_fd: proto_descriptor.FieldDescriptor | None,
        new_fd: proto_descriptor.FieldDescriptor | None,
        path: FieldPath,
        old_pool: descriptor_pool.DescriptorPool,
        new_pool: descriptor_pool.DescriptorPool,
        findings: list[Finding],
        warnings_sink: list[Diagnostic],
    ) -> None:
        sink: list[Finding] = []
        emit = make_emit(rule_id, sink, old_descriptor=old_fd, new_descriptor=new_fd)
        ctx = FieldRuleContext(
            path=path,
            old_field=old_fd,
            new_field=new_fd,
            old_pool=old_pool,
            new_pool=new_pool,
            _emit_fn=emit,
        )
        try:
            result = plugin_fn(ctx)
        except Exception as exc:
            self._record_plugin_failure(
                rule_id, exc, path, warnings_sink,
            )
            return
        if inspect.isawaitable(result):
            self._cleanup_awaitable(result)
            self._record_plugin_failure(
                rule_id,
                TypeError(
                    "plugin returned an awaitable; async plugins are "
                    "not supported"
                ),
                path,
                warnings_sink,
            )
            return
        findings.extend(sink)

    def _dispatch_message_plugin(
        self,
        rule_id: str,
        plugin_fn: MessagePlugin,
        old_m: proto_descriptor.Descriptor | None,
        new_m: proto_descriptor.Descriptor | None,
        path: FieldPath,
        old_pool: descriptor_pool.DescriptorPool,
        new_pool: descriptor_pool.DescriptorPool,
        findings: list[Finding],
        warnings_sink: list[Diagnostic],
    ) -> None:
        sink: list[Finding] = []
        emit = make_emit(rule_id, sink, old_descriptor=old_m, new_descriptor=new_m)
        ctx = MessageRuleContext(
            path=path,
            old_descriptor=old_m,
            new_descriptor=new_m,
            old_pool=old_pool,
            new_pool=new_pool,
            _emit_fn=emit,
        )
        try:
            result = plugin_fn(ctx)
        except Exception as exc:
            self._record_plugin_failure(
                rule_id, exc, path, warnings_sink,
            )
            return
        if inspect.isawaitable(result):
            self._cleanup_awaitable(result)
            self._record_plugin_failure(
                rule_id,
                TypeError(
                    "plugin returned an awaitable; async plugins are "
                    "not supported"
                ),
                path,
                warnings_sink,
            )
            return
        findings.extend(sink)

    @staticmethod
    def _cleanup_awaitable(result: object) -> None:
        """Best-effort cleanup of an awaitable plugin return.

        Different awaitables expose different cleanup methods:
        native coroutines and legacy generator-based ones use
        ``close()``, ``asyncio.Future`` uses ``cancel()``, and
        custom ``__await__`` objects may have neither. Try each
        method in turn, swallowing any exception so a misbehaving
        awaitable can't take the whole check down during teardown.
        Returns after the first method completes *successfully*; if
        the first method raises, we still try the next so a
        coroutine that explodes on ``close()`` still gets a chance
        to ``cancel()``.
        """
        for method in ("close", "cancel"):
            cleanup = getattr(result, method, None)
            if not callable(cleanup):
                continue
            try:
                cleanup()
            except Exception:
                continue
            return

    @staticmethod
    def _record_plugin_failure(
        rule_id: str,
        exc: Exception,
        path: FieldPath,
        warnings_sink: list[Diagnostic],
    ) -> None:
        """Record a plugin exception into ``CompatibilityReport.diagnostics``.

        A plugin crash is a tool-level failure, not a comparison
        caveat: the ``Diagnostic`` goes in at ``level="error"`` so
        consumers can distinguish it from benign warnings. CLI
        callers fail-closed on any error diagnostic (exit 2);
        library callers can read ``report.errors`` directly or
        iterate ``report.diagnostics`` and branch on ``d.level``.
        """
        message = (
            f"schema plugin '{rule_id}' raised "
            f"{type(exc).__name__}: {exc}"
        )
        warnings_sink.append(Diagnostic(
            path=str(path) if path else None,
            message=message,
            level="error",
        ))

    # ------------------------------------------------------------------
    # Post-processing
    # ------------------------------------------------------------------

    def _apply_ignore(self, findings: Iterable[Finding]) -> list[Finding]:
        if not self._ignore_paths:
            return list(findings)
        ignored = self._ignore_paths
        return [
            f for f in findings
            if not any(ig.is_prefix_of(f.path) for ig in ignored)
        ]


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def check_compatibility(
    old_pool: descriptor_pool.DescriptorPool,
    old_type: str,
    new_pool: descriptor_pool.DescriptorPool,
    new_type: str,
    *,
    level: CompatibilityLevel = CompatibilityLevel.STRICT,
) -> CompatibilityReport:
    """One-shot compatibility check with the built-in rule set.

    Convenience wrapper around ``SchemaChecker(level=level).check(...)``.
    Use the class directly when you need to register custom rules,
    configure ignore paths, or load rule packs.

    Args:
        old_pool: Descriptor pool containing the old schema.
        old_type: Fully-qualified message type name in ``old_pool``.
        new_pool: Descriptor pool containing the new schema.
        new_type: Fully-qualified message type name in ``new_pool``.
            May differ from ``old_type`` for cross-type comparisons.
        level: Compatibility profile to apply. Defaults to
            ``CompatibilityLevel.STRICT``.

    Returns:
        A ``CompatibilityReport`` with findings filtered by ``level``.

    Raises:
        ValueError: If either type name cannot be resolved in its
            pool. Propagated from ``SchemaChecker.check``.
    """
    return SchemaChecker(level=level).check(old_pool, old_type, new_pool, new_type)
