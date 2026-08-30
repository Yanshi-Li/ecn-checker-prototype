"""Aggregate pipeline findings and calculate the v1.2 ECN gate decision.

The gate closes when Node 2 produces an ERROR-severity blocker, or Node 4
produces a configured part issue or conflict alert. Warnings and Node 3 AI
notes are advisory only. A packet passes only when all three gate-closing
categories are empty.
"""

import logging

logger = logging.getLogger(__name__)

PART_ISSUE_FLAG_TYPES = {
    "DISCONTINUED_PART",
    "MISSING_SUPPLIER",
    "UOM_MISMATCH",
}
CONFLICT_ALERT_FLAG_TYPES = {"HISTORICAL_CONFLICT"}
WARNING_ONLY_FLAG_TYPES = {
    "UNKNOWN_PART",
    "QUANTITY_ANOMALY",
    "DESCRIPTION_MISMATCH",
}


def run_merge_step(packet: dict) -> dict:
    """Aggregate validation output and attach the automatic gate decision."""
    validation = packet["validation"]
    rule_violations = validation.get("rule_violations", [])
    context_flags = validation.get("context_flags", [])
    ai_flags = validation.get("ai_flags", {})
    if not isinstance(ai_flags, dict):
        ai_flags = {}

    blockers = [
        violation
        for violation in rule_violations
        if violation.get("severity") == "ERROR"
    ]
    rule_warnings = [
        violation
        for violation in rule_violations
        if violation.get("severity") != "ERROR"
    ]

    part_issues = []
    conflict_alerts = []
    context_warnings = []
    for flag in context_flags:
        flag_type = flag.get("flag_type")
        if flag_type in PART_ISSUE_FLAG_TYPES:
            part_issues.append(flag)
        elif flag_type in CONFLICT_ALERT_FLAG_TYPES:
            conflict_alerts.append(flag)
        elif flag_type in WARNING_ONLY_FLAG_TYPES:
            context_warnings.append(flag)
        else:
            raise ValueError(
                f"Unclassified context flag_type: {flag_type!r}. "
                "Register it in a merge-step classification set."
            )




    decision = "PASS" if not (blockers or part_issues or conflict_alerts) else "FAIL"
    overall_risk = ai_flags.get("overall_risk")
    packet["gate"] = {
        "decision": decision,
        "blockers": blockers,
        "part_issues": part_issues,
        "conflict_alerts": conflict_alerts,
        "warnings": rule_warnings + context_warnings,
        "ai_notes": {
            "mismatch_flag": overall_risk not in {"LOW", "UNKNOWN", None},
            "flags": ai_flags.get("flags", []),
            "recommendation": ai_flags.get("recommendation", ""),
            "confidence": ai_flags.get("confidence"),
            "ai_available": ai_flags.get("ai_available", False),
        },
    }

    logger.info(
        "Merge Step complete — %s (blockers:%d part_issues:%d "
        "conflict_alerts:%d warnings:%d)",
        decision,
        len(blockers),
        len(part_issues),
        len(conflict_alerts),
        len(packet["gate"]["warnings"]),
    )
    return packet
