"""
Main Orchestrator — ECN Hybrid Checker Pipeline
Flow: Intake → Rule Engine → AI Advisory → Context Engine → Merge Step → Dashboard → Approval
"""

import os
import sys
import logging
import argparse
import importlib.util
from pathlib import Path

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent
SCRIPTS = Path(__file__).parent


def _load(name: str):
    """Load a module by explicit file path to avoid PyPI package shadowing."""
    path = SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    print(f"  [loader] {name} -> {path}")
    return mod


intake_mod            = _load("intake")
rule_engine_mod       = _load("rule_engine")
ai_advisory_mod       = _load("ai_advisory")
context_engine_mod    = _load("context_engine")
merge_step_mod        = _load("merge_step")
dashboard_mod         = _load("dashboard")
approval_workflow_mod = _load("approval_workflow")

run_intake         = intake_mod.run_intake
run_rule_engine    = rule_engine_mod.run_rule_engine
run_ai_advisory    = ai_advisory_mod.run_ai_advisory
run_context_engine = context_engine_mod.run_context_engine
run_merge_step     = merge_step_mod.run_merge_step
run_dashboard      = dashboard_mod.run_dashboard
approve_ecn        = approval_workflow_mod.approve_ecn
reject_ecn         = approval_workflow_mod.reject_ecn


# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── AI summary writer ─────────────────────────────────────────────────────────
def write_ai_summary(packet: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    header = packet["header"]
    ai_flags = packet["validation"].get("ai_flags", {})
    rule_violations = packet["validation"].get("rule_violations", [])
    context_flags = packet["validation"].get("context_flags", [])
        # Guard: wrap bare list into expected dict shape
    if isinstance(ai_flags, list):
        ai_flags = {
            "overall_risk": "UNKNOWN",
            "description_quality": "UNKNOWN",
            "flags": ai_flags,
            "recommendation": "ai_flags was stored as a raw list — check ai_advisory.py.",
            "ai_available": False,
        }
    lines = [
        f"# ECN AI Summary — {header.get('ecn_id', 'N/A')}",
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
    for f in context_flags:
        lines.append(
            f"- [{f.get('severity')}] **{f.get('flag_type')}** "
            f"({f.get('part_number')}) — {f.get('message')}"
        )

    summary_path = out_dir / "ai_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info("AI summary written to %s", summary_path)


# ── CLI ───────────────────────────────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ECN Hybrid Checker — Full Pipeline"
    )
    parser.add_argument(
        "--ecn", default=str(ROOT / "data" / "ecn_intake.csv"),
        help="Path to ECN file (CSV, Excel, or PDF)"
    )
    parser.add_argument(
        "--bom", default=str(ROOT / "data" / "bom.csv"),
        help="Path to BOM file (CSV or Excel)"
    )
    parser.add_argument(
        "--engineer-email", default="engineer@company.com",
        help="Engineer email for notifications"
    )
    parser.add_argument(
        "--coordinator-email", default="bom.coordinator@company.com",
        help="BOM Coordinator email for notifications"
    )
    parser.add_argument(
        "--auto-decision", choices=["approve", "reject", "none"],
        default="none",
        help="Auto-approve or auto-reject for testing (default: none)"
    )
    parser.add_argument(
        "--reject-reason", default="Issues found during automated review.",
        help="Rejection reason (used with --auto-decision reject)"
    )
    return parser.parse_args()


# ── Pipeline ──────────────────────────────────────────────────────────────────
def run_pipeline(args: argparse.Namespace) -> dict:
    logger.info("=" * 60)
    logger.info("ECN CHECKER PIPELINE STARTING")
    logger.info("=" * 60)

    # Stage 1: Intake
    logger.info("── Stage 1: Intake & Extraction ──")
    packet = run_intake(args.ecn, args.bom)

    # Stage 2: Rule Engine
    logger.info("── Stage 2: Rule Engine ──")
    packet = run_rule_engine(packet)

    # Early exit if critical errors and no AI needed
    errors = [
        v for v in packet["validation"]["rule_violations"]
        if v["severity"] == "ERROR"
    ]
    if errors:
        logger.warning(
            "%d rule error(s) found. AI Advisory will still run.", len(errors)
        )

    # Stage 3: AI Advisory
    logger.info("── Stage 3: AI Advisory ──")
    packet = run_ai_advisory(packet)

    # Stage 4: Context Engine
    logger.info("── Stage 4: Context Engine (RAG) ──")
    packet = run_context_engine(packet)
    #  Safety net — ensure ai_flags is always a valid dict before dashboard
    ai_flags = packet["validation"].get("ai_flags", {})
    if not isinstance(ai_flags, dict) or not ai_flags:
        logger.warning("ai_flags missing or wrong type — injecting empty advisory dict.")
        packet["validation"]["ai_flags"] = {
            "overall_risk":        "UNKNOWN",
            "description_quality": "UNKNOWN",
            "flags":               [],
            "recommendation":      "AI Advisory result was lost — check pipeline logs.",
            "ai_available":        False,
        }
        logger.info("ai_flags at dashboard: %s", packet["validation"].get("ai_flags"))

    # Merge Step: Aggregation & Gate Decision
    logger.info("── Merge Step: Aggregation & Gate Decision ──")
    packet = run_merge_step(packet)
    logger.info("GATE DECISION: %s", packet["gate"]["decision"])

    # Stage 5: Dashboard
    logger.info("── Stage 5: Dashboard ──")
    if hasattr(dashboard_mod, "_impl") and hasattr(dashboard_mod, "OUT_DIR"):
        dashboard_mod._impl.OUT_DIR = dashboard_mod.OUT_DIR
    dashboard_path = run_dashboard(packet)
    write_ai_summary(packet, ROOT / "out")

    logger.info("=" * 60)
    logger.info("PIPELINE COMPLETE")
    logger.info("  Dashboard : %s", dashboard_path)
    logger.info("  Summary   : %s", ROOT / "out" / "ai_summary.md")
    logger.info("=" * 60)

    # Stage 6: Approval Workflow (optional / automated for testing)
    if args.auto_decision == "approve":
        logger.info("── Stage 6: Auto-Approve ──")
        approve_ecn(packet, args.coordinator_email, args.engineer_email)
    elif args.auto_decision == "reject":
        logger.info("── Stage 6: Auto-Reject ──")
        reject_ecn(
            packet, args.coordinator_email,
            args.engineer_email, args.reject_reason
        )
    else:
        logger.info(
            "── Stage 6: Awaiting BOM Coordinator decision ──\n"
            "   Use approve_ecn() / reject_ecn() from approval_workflow.py"
        )

    return packet


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    args = parse_args()
    run_pipeline(args)
    