"""Shared logging setup.

Single canonical home for the StreamHandler logger boilerplate that was
copy-pasted across ~two dozen cron-invoked scripts. Each caller passes its
own logger name; the level (INFO), formatter, and stderr stream are uniform.

Scripts that need a FileHandler (e.g. the LaunchAgent-driven ones writing to
``.state/*.log``) deliberately keep their own setup and do NOT use this.
"""

from __future__ import annotations

import logging
import sys


def setup_logging(name: str | None = None) -> logging.Logger:
    """Return an INFO-level logger writing to stderr with a timestamped format.

    Idempotent: if the named logger already has handlers, no new handler is
    added (matches the prior per-script ``if not logger.handlers`` guard).
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(h)
    return logger
