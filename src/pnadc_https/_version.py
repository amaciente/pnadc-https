"""Single source of truth for the package version.

Kept in its own module so that :mod:`pnadc_https.config` can read it without
importing :mod:`pnadc`, which imports ``config`` in turn.  ``pyproject.toml``
reads the same attribute, so the version is declared exactly once.
"""

from __future__ import annotations

__version__ = "0.4.0"
