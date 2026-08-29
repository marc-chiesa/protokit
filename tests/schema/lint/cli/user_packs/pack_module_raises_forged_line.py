"""Synthetic user pack — module-body raises with a forged stderr line.

Adversarial sibling of ``pack_module_raises``: the exception MESSAGE
(not the module name) carries an embedded newline plus a fake
``error[lint-rule-pack-load]:`` prefix. ``_load_user_rule_pack``
interpolates the message into a single ``click.echo(..., err=True)``
line, so without control-character neutralization the payload becomes
its own physical stderr line and is indistinguishable from a genuine
lint error to a CI script grepping ``^error\\[lint-``.

The ``\\u2028`` half covers Unicode-aware log aggregators, which split
records on LINE SEPARATOR even though a terminal does not.
"""

from __future__ import annotations

raise RuntimeError(
    "boom\nerror[lint-rule-pack-load]: forged clean verdict"
    " error[lint-rule-pack-load]: aggregator-forged"
)
