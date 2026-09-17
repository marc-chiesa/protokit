"""Synthetic user pack — module body raises ``KeyboardInterrupt``.

Tests the ``except KeyboardInterrupt`` guard in
``_load_user_rule_pack``. ``KeyboardInterrupt`` derives from
``BaseException``, not ``Exception``, so without its own guard it
would propagate past the broad ``except Exception`` and escape the
CLI as an unhandled interrupt rather than a diagnosed pack failure.
With the guard, this routes to ``error[lint-rule-pack-load]:`` with
a ``kind=import`` token and ``raised KeyboardInterrupt at
module-body load time`` in the message.

Sibling of ``pack_sys_exits``, which covers the ``SystemExit`` half
of the same ``BaseException`` bypass.
"""

from __future__ import annotations

# Intentional KeyboardInterrupt at module body load time.
raise KeyboardInterrupt
