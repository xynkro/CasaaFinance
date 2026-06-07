"""Shared logging setup.

Single canonical home for the logger boilerplate that was copy-pasted across
~three dozen cron-invoked scripts.

Two entry points:

``setup_logging(name)``
    Plain stderr logger (INFO, timestamped). Used by the bulk of scripts that
    only ever log to stderr (captured by the cron / GitHub-Actions runner).

``setup_file_logging(name, logfile, ...)``
    Logger that also writes to ``.state/<logfile>`` via a FileHandler, used by
    the LaunchAgent / scheduled scripts whose operational logs the owner reads
    directly. Reproduces the per-script FileHandler pattern (mkdir the .state
    dir, FileHandler + optional stderr echo) in one place.

Both are idempotent: re-importing a module that calls them does not stack
duplicate handlers (guard on ``logger.handlers``).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Project root (…/FinancePWA). ``.state`` log files hang off this so callers
# can pass a bare filename ("sync.log") or a relative path (".state/sync.log").
_ROOT = Path(__file__).resolve().parent.parent

# Standard timestamped record format used for file logs and most stderr logs.
DEFAULT_FMT = "%(asctime)s %(levelname)s %(message)s"
# Short format the FileHandler scripts use for their stderr echo (the timestamp
# is redundant there because the cron runner already timestamps each line).
SHORT_FMT = "%(levelname)s %(message)s"


def setup_logging(name: str | None = None) -> logging.Logger:
    """Return an INFO-level logger writing to stderr with a timestamped format.

    Idempotent: if the named logger already has handlers, no new handler is
    added (matches the prior per-script ``if not logger.handlers`` guard).
    """
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        h = logging.StreamHandler(sys.stderr)
        h.setFormatter(logging.Formatter(DEFAULT_FMT))
        logger.addHandler(h)
    return logger


def setup_file_logging(
    name: str,
    logfile: str | None,
    *,
    to_stderr: bool = True,
    fmt: str | None = None,
    stream_fmt: str | None = None,
    level: int = logging.INFO,
    file_optional: bool = False,
) -> logging.Logger:
    """Return a logger that writes to ``.state/<logfile>`` and (optionally) stderr.

    Reproduces the FileHandler boilerplate that the LaunchAgent / scheduled
    scripts each defined inline:

      * ``logfile`` is resolved against the project root. A bare name like
        ``"sync.log"`` lands in ``.state/sync.log``; an explicit relative path
        like ``".state/sync.log"`` (e.g. from an env-var override) is honoured
        as-is. The parent directory is created if missing.
      * A ``logging.FileHandler`` is added with ``fmt`` (default ``DEFAULT_FMT``).
      * If ``to_stderr`` (the default), a ``logging.StreamHandler(sys.stderr)``
        is added with ``stream_fmt`` (default ``SHORT_FMT`` — the short format
        the originals used for their stderr echo, since the runner already
        timestamps each line). Pass ``stream_fmt=fmt`` for a uniform format.
      * ``logfile=None`` skips the FileHandler entirely (stderr-only logger) —
        used by callers that never wrote to disk. With no file, ``fmt`` (if
        given) drives the stderr format, so a single ``fmt="%(levelname)s ..."``
        call reads naturally.
      * ``file_optional=True`` wraps the directory creation + FileHandler in a
        ``try/except OSError`` so a read-only filesystem (cloud runner) degrades
        to stderr-only instead of crashing.

    Idempotent: guarded on ``logger.handlers`` like the originals.
    """
    file_fmt = logging.Formatter(fmt if fmt is not None else DEFAULT_FMT)
    if stream_fmt is not None:
        echo_pattern = stream_fmt
    elif logfile is None and fmt is not None:
        # Stderr-only logger: let the natural ``fmt`` arg drive the one handler.
        echo_pattern = fmt
    else:
        echo_pattern = SHORT_FMT
    echo_fmt = logging.Formatter(echo_pattern)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    if logger.handlers:
        return logger

    if logfile is not None:
        log_path = _ROOT / logfile

        def _add_file_handler() -> None:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = logging.FileHandler(log_path)
            fh.setFormatter(file_fmt)
            logger.addHandler(fh)

        if file_optional:
            try:
                _add_file_handler()
            except OSError:
                pass
        else:
            _add_file_handler()

    if to_stderr:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(echo_fmt)
        logger.addHandler(sh)

    return logger
