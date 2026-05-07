"""Synthetic user pack — module body calls ``sys.exit(0)``.

Tests the ``except SystemExit`` guard in ``_load_user_rule_pack``.
Without the guard, a user pack calling ``sys.exit(0)`` at module
load time would propagate past the broad ``except Exception`` and
produce a false-green CI exit. With the guard, this routes to
``error[lint-rule-pack-load]:`` with ``kind=import`` token and
``sys.exit({code!r}) at module-body load time`` in the message.
"""

from __future__ import annotations

import sys

# Intentional SystemExit at module body load time.
sys.exit(0)
