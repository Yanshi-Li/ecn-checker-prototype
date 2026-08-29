"""Compatibility wrapper for the staged email-notification module."""

try:
    from .stages.email_notification import *  # noqa: F401,F403
except ImportError:
    from stages.email_notification import *  # noqa: F401,F403



