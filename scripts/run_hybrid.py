"""
Main Orchestrator - ECN Hybrid Checker Pipeline
Flow: Intake -> Rule Engine -> AI Advisory -> Context Engine -> Merge Step -> Dashboard -> Email Notification
"""

import os
import sys
import logging
import argparse
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPTS = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.stages import (
    ai_advisory as ai_advisory_mod,
    context_engine as context_engine_mod,
    dashboard as dashboard_mod,
    email_notification as email_notification_mod,
    intake as intake_mod,
    merge_step as merge_step_mod,
    rule_engine as rule_engine_mod,
)

# Path setup
run_intake = intake_mod.run_intake
run_rule_engine = rule_engine_mod.run_rule_engine
run_ai_advisory = ai_advisory_mod.run_ai_advisory
run_context_engine = context_engine_mod.run_context_engine
log_approved_change = context_engine_mod.log_approved_change
run_merge_step = merge_step_mod.run_merge_step
run_dashboard = dashboard_mod.run_dashboard
send_fail_email = email_notification_mod.send_fail_email
send_pass_email = email_notification_mod.send_pass_email


# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# AI summary writer
def write_ai_summary(packet: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    header = packet["header"]
    ai_flags = packet["validation"].get("ai_flags", {})

    rule_violations = packet["validation"].get("rule_violations", [])
    context_flags = packet["validation"].get("context_flags", [])

    # Guard: wrap bare list into expected dict shape.
    if isinstance(ai_flags, list):
        ai_flags = {
            "overall_risk": "UNKNOWN",
            "description_quality": "UNKNOWN",
            "flags": ai_flags,
            "recommendation": "ai_flags was stored as a raw list — check ai_advisory.py.",
            "ai_available": False,
        }

    lines = [
        f"# ECN AI Summary — {header.get('change_notice_number', 'N/A')}",
        f"**Title:** {header.get('title', '')}  ",
        f"**Author:** {header.get('author', '')}  ",
        f"**Date:** {header.get('date', '')}  ",
        "",
        "---",
        "",
        "## AI Advisory",
        f"- **Overall Risk:** {ai_flags.get('overall_risk', 'N/A')}",
        f"- **Description Quality:** {ai_flags.get('description_quality', 'N/A')}",
        f"- **AI Available:** {ai_flags.get('ai_available', False)}",
        f"- **Response Status:** {ai_flags.get('response_status', 'UNKNOWN')}",
        f"- **Recommendation:** {ai_flags.get('recommendation', '')}",
        "",
        "### AI Flags",
    ]

    for flag in ai_flags.get("flags", []):
        lines.append(f"- **{flag.get('type')}**: {flag.get('detail')}")

    lines += ["", "---", "", "## Rule Engine Violations"]
    for v in rule_violations:
        lines.append(
            f"- [{v.get('severity')}] **{v.get('rule_id')}** — {v.get('message')}"
        )

    lines += ["", "---", "", "## Context Engine Flags"]
    for ctx_flag in context_flags:
        lines.append(
            f"- [{ctx_flag.get('severity')}] **{ctx_flag.get('rule_id', '—')}** "
            f"{ctx_flag.get('flag_type')} ({ctx_flag.get('part_number')}) — "
            f"{ctx_flag.get('message')}"
        )

    summary_path = out_dir / "ai_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info("AI summary written to %s", summary_path)


# CLI
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ECN Hybrid Checker - Full Pipeline"
    )
    parser.add_argument(
        "--ecn",
        required=True,
        help="Path to the required ECN file (CSV, Excel, PDF, HTML, or EML)",
    )
    parser.add_argument(
        "--bom",
        action="append",
        default=[],
        help="Path to one BOM file; repeat up to four times. BOM is optional.",
    )
    parser.add_argument(
        "--engineer-email",
        default="engineer@company.com",
        help="Engineer email for notifications",
    )
    parser.add_argument(
        "--ce-email",
        default="chief.engineer@company.com",
        help="Chief Engineer email for PASS gate notifications",
    )
    return parser.parse_args()



# Pipeline
def run_pipeline(args: argparse.Namespace, output_suffix: str = "") -> dict:
    logger.info("=" * 60)
    logger.info("ECN CHECKER PIPELINE STARTING")
    logger.info("=" * 60)

        
    # Stage 1: Intake


    logger.info("-- Stage 1: Intake & Extraction --")

    # The CLI passes ``None`` for an ECN-only run. Normalize both that
    # The CLI passes ``None`` for an ECN-only run. Normalize both that
    # representation and the single-string test/caller form before inspecting

    # representation and the single-string test/caller form before inspecting


    # the collection.
    bom_paths = args.bom or []
    if isinstance(bom_paths, str):
        bom_paths = [bom_paths]

    if len(bom_paths) > 1:
        raise ValueError(
            "One ECN is compared with one BOM per run. "
            "Run each BOM separately rather than comparing BOM files with each other."
        )
    packet = run_intake(args.ecn, bom_paths[0] if bom_paths else None)

    # Stage 2: Rule Engine


    logger.info("-- Stage 2: Rule Engine --")
    packet = run_rule_engine(packet)


    errors = [
        v for v in packet["validation"]["rule_violations"]
        if v.get("gate_effect") == "FAIL"
    ]
    if errors:
        logger.warning(
            "%d rule error(s) found. AI Advisory will still run.", len(errors)
        )

    # Stage 3: AI Advisory
    logger.info("-- Stage 3: AI Advisory --")
    packet = run_ai_advisory(packet)

    # Stage 4: Context Engine
    logger.info("-- Stage 4: Context Engine (RAG) --")
    packet = run_context_engine(packet)
    # Safety net: ensure ai_flags is always a valid dict before dashboard
    ai_flags = packet["validation"].get("ai_flags", {})
    if not isinstance(ai_flags, dict) or not ai_flags:
        logger.warning("ai_flags missing or wrong type - injecting empty advisory dict.")
        packet["validation"]["ai_flags"] = {
            "overall_risk":        "UNKNOWN",
            "description_quality": "UNKNOWN",
            "flags":               [],
            "recommendation":      "AI Advisory result was lost - check pipeline logs.",
            "ai_available":        False,
        }
        logger.info("ai_flags at dashboard: %s", packet["validation"].get("ai_flags"))

        
    # Merge Step: Aggregation & Gate Decision

    logger.info("-- Merge Step: Aggregation & Gate Decision --")
    packet = run_merge_step(packet)
    log_approved_change(packet)
    logger.info("GATE DECISION: %s", packet["gate"]["decision"])

        
    # Stage 5: Dashboard


    logger.info("-- Stage 5: Dashboard --")
    

    output_dir = ROOT / "out"
    dashboard_path = run_dashboard(
        packet,
        out_path=output_dir / f"dashboard{output_suffix}.html",
    )

    write_ai_summary(packet, output_dir)
    if output_suffix:
        summary_path = output_dir / "ai_summary.md"
        suffixed_summary_path = output_dir / f"ai_summary{output_suffix}.md"
        summary_path.replace(suffixed_summary_path)

    # Stage 6: Email Notification, driven solely by the calculated gate.
    decision = packet["gate"]["decision"]
    logger.info("-- Stage 6: Email Notification (%s) --", decision)
    if decision == "FAIL":
        notification_result = send_fail_email(packet, args.engineer_email)
    else:
        notification_result = send_pass_email(
            packet, args.engineer_email, args.ce_email
        )
    packet["notification"] = notification_result
    logger.info(
        "Notification %s - recipients: %s; subject: %s",
        "sent" if notification_result["sent"] else "dry-run" if notification_result["dry_run"] else "not sent",
        ", ".join(notification_result["recipients"]),
        notification_result["subject"],
    )

    logger.info("=" * 60)
        
    logger.info("PIPELINE COMPLETE")

    logger.info("  Dashboard : %s", dashboard_path)
    logger.info(
        "  Summary   : %s",
        ROOT / "out" / f"ai_summary{output_suffix}.md",
    )
    logger.info("=" * 60)

        
    return packet



# Entry point
if __name__ == "__main__":
    args = parse_args()
    bom_paths = args.bom or [None]
    if len(bom_paths) > 4:
        raise SystemExit("Provide zero to four BOM files.")

    for index, bom_path in enumerate(bom_paths, start=1):
        args.bom = bom_path
        suffix = "" if len(bom_paths) == 1 else f"_{index}"
        logger.info(
            "Comparing ECN %s with BOM %s (%d of %d)",
            args.ecn,
            bom_path or "<none>",
            index,
            len(bom_paths),
        )
        run_pipeline(args, output_suffix=suffix)
