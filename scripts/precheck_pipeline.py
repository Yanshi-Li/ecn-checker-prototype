"""Shared ECN pre-check pipeline used by the Streamlit and Flask interfaces."""

from __future__ import annotations

from scripts.stages.ai_advisory import run_ai_advisory
from scripts.stages.context_engine import log_approved_change, run_context_engine
from scripts.stages.intake import run_intake
from scripts.stages.merge_step import run_merge_step
from scripts.stages.rule_engine import run_rule_engine


def run_precheck(ecn_path: str, bom_path: str | None = None) -> dict:
    """Run every validation stage and return the unified pre-check packet."""
    packet = run_intake(ecn_path, bom_path)
    packet = run_rule_engine(packet)
    packet = run_ai_advisory(packet)
    packet = run_context_engine(packet)
    packet = run_merge_step(packet)
    log_approved_change(packet)
    return packet
