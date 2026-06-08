"""Shared logging configuration for the CLI entry points."""

from __future__ import annotations

import logging
import os
import sys


def setup_logging(logger_name: str) -> logging.Logger:
    """Configure root logging from the LOG_LEVEL env var and return a named
    logger for the caller."""
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    return logging.getLogger(logger_name)
