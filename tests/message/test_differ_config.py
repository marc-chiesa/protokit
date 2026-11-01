"""The configuration snapshot ``compare()`` takes, and the trial differencer built from it.

Set pairing's trial differencer is built from a :class:`DifferConfig`, so a
setting the snapshot or the builder forgets would silently not apply inside
pairing. The round trip below fails as soon as either side misses a field.
"""

from __future__ import annotations

import dataclasses

from protokit.message import FloatComparison, MessageDifferencer, MessageFieldComparison
from protokit.message._differ_config import DifferConfig
from protokit.message.differ import _config_of, _engine


def _configured() -> MessageDifferencer:
    """A differencer with every setting away from its default."""
    d = MessageDifferencer()
    d.ignore_fields("noise", "a.b", lambda fd, path: False)
    d.treat_as_map("rows", key="id")
    d.treat_as_map("box.cells", key="k")
    d.treat_as_set("tags")
    d.set_partial()
    d.set_message_field_comparison(MessageFieldComparison.EQUAL)
    d.set_float_comparison(FloatComparison.APPROXIMATE)
    d.set_float_comparison(FloatComparison.APPROXIMATE, selector="ratio")
    d.max_depth = 3
    d.strict_schema = True
    d.register_validate_hook(lambda ctx: None)
    d.register_compare_hook(lambda ctx: None)
    d.register_report_hook(lambda ctx: None)
    d.register_message_validate_hook(lambda ctx: None)
    return d


def test_every_setting_survives_the_round_trip() -> None:
    config = _config_of(_configured())
    default = _config_of(MessageDifferencer())

    unchanged = [
        f.name for f in dataclasses.fields(DifferConfig)
        if getattr(config, f.name) == getattr(default, f.name)
    ]
    assert unchanged == [], "the fixture must move every setting off its default"
    assert _config_of(_engine(config)) == config


def test_the_trial_configuration_is_its_own_trial_configuration() -> None:
    trial = _config_of(_configured()).for_trial()

    assert trial.for_trial() == trial
    assert (trial.max_depth, trial.partial, trial.float_overlays, trial.validate_hooks) == (
        None, False, (), (),
    )
    assert trial.float_config.mode is FloatComparison.EXACT
