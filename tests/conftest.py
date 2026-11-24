"""Shared pytest configuration.

Registers a ``deep`` hypothesis profile for the property-based tests (#39,
``test_schedule_properties.py``). CI runs hypothesis's defaults — a hundred
examples per property, which is enough to keep a regression from landing
unnoticed and cheap enough not to dominate the pipeline. Run

    pytest --hypothesis-profile=deep

before trusting a change to schedule generation: a thousand examples per
property is roughly a minute and reaches the shapes the default pass does not,
which is how the 30/360 zero-length stub and the ACT/360 oversized stub in
``test_schedule_properties.py`` were found.
"""

from hypothesis import settings

settings.register_profile("deep", max_examples=1000, deadline=None)
