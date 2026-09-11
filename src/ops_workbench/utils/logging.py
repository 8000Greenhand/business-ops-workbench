"""Logging setup for Business Ops Workbench."""

import logging

DEFAULT_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Configure application logging with a consistent default format."""
    logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger for an application module."""
    return logging.getLogger(name)
