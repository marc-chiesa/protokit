"""Synthetic user rule-packs for testing ``protokit lint --rule-pack``.

Each ``pack_*.py`` here is a fixture that exercises one branch of
the U3 ``--rule-pack`` loading + composition + error-routing path.
Files use a ``pack_`` prefix (not ``test_``) so pytest's default
collection skips them; tests reference these packs by their
fully-qualified Python module path (e.g.,
``tests.schema.lint.cli.user_packs.pack_user_a``) when invoking
``--rule-pack``.
"""

from __future__ import annotations
