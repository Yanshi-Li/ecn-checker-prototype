"""Backward-compatible wrapper for staged dashboard module."""

from stages.dashboard import *  # noqa: F401,F403
from stages import dashboard as _impl
