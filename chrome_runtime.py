"""Compatibility helper for older browser notebooks.

Passing ``None`` as ``version_main`` tells undetected-chromedriver to select
the installed Chrome version itself. This performs no Chrome or registry
probing, so it cannot create additional Chrome windows.
"""

from __future__ import annotations


def detect_chrome_major_version() -> None:
    """Return ``None`` to select undetected-chromedriver's automatic mode."""
    return None
