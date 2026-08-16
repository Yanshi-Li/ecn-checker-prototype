"""Backward-compatible wrapper for staged AI advisory module."""

from stages.ai_advisory import *  # noqa: F401,F403
from stages import ai_advisory as _impl

_build_prompt = _impl._build_prompt
_resolve_llm_config = _impl._resolve_llm_config
_rule_based_advisory = _impl._rule_based_advisory
