import json
from pathlib import Path
from typing import Any, Dict, List


def build_single_ecn_view(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    ecn = dashboard.get("ecns", [{}])[0]
    description = ecn.get("description", "") or ""
    description_issues = []
    if not description.strip():
        description_issues.append("ECN description is empty.")
    elif len(description.split()) < 8:
        description_issues.append("ECN description is too short for proper review.")
    if "assembly" not in description.lower() and ecn.get("affectedAssembly"):
        description_issues.append("Description does not mention the affected assembly.")

    audit_required = ecn.get("blockerCount", 0) > 0 or ecn.get("warningCount", 0) > 0
    return {
        "ecnId": ecn.get("ecnId"),
        "title": ecn.get("title"),
        "affectedAssembly": ecn.get("affectedAssembly"),
        "description": description,
        "descriptionIssues": description_issues,
        "bomauditRequired": audit_required,
        "reviewActions": [
            "Review description completeness",
            "Validate affected assembly context",
            "Confirm BOM impact before population",
        ],
        "validationSummary": {
            "passCount": ecn.get("passCount", 0),
            "warningCount": ecn.get("warningCount", 0),
            "blockerCount": ecn.get("blockerCount", 0),
            "decision": ecn.get("decision", "REVIEW"),
        },
        "results": ecn.get("results", []),
    }


def write_single_ecn_dashboard(payload: Dict[str, Any], output_path: Path | str) -> None:
    output_path = Path(output_path)
    html = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>Single ECN Workflow</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f5f7fb; color: #1f2937; }
    .container { display: grid; gap: 16px; }
    .card { background: white; border: 1px solid #d1d5db; padding: 16px; border-radius: 10px; }
    .row { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }
    .pill { display: inline-block; padding: 4px 8px; border-radius: 999px; font-weight: bold; font-size: 12px; }
    .pill.review { background: #fef3c7; color: #92400e; }
    .pill.blocker { background: #fee2e2; color: #991b1b; }
    .pill.approve { background: #dcfce7; color: #166534; }
    .actions button { margin-right: 8px; padding: 8px 12px; border: none; border-radius: 6px; color: white; font-weight: bold; cursor: pointer; }
    .actions .approve { background: #047857; }
    .actions .request { background: #b45309; }
    .actions .block { background: #b91c1c; }
    .warning { color: #b45309; font-weight: bold; }
    .required { color: #b91c1c; font-weight: bold; }
  </style>
</head>
<body>
  <h1>Single-ECN Creator and BOM Coordinator Workflow</h1>
  <p>This view is centered on one ECN at a time so it fits the creator-to-reviewer flow.</p>
  <div class=\"container\">
"""
    html += f"<div class=\"card\"><h2>{payload['ecnId']} - {payload.get('title', '')}</h2><p><strong>Affected assembly:</strong> {payload.get('affectedAssembly', '')}</p>"
    summary = payload.get("validationSummary", {})
    decision = str(summary.get("decision", "REVIEW")).upper()
    html += f"<p><strong>Decision:</strong> <span class=\"pill {decision.lower() if decision.lower() in {'review','blocker','approve'} else 'review'}\">{decision}</span></p></div>"
    html += "<div class=\"row\">"
    html += "<div class=\"card\"><h3>Creator view</h3><p><strong>Description:</strong> " + (payload.get("description") or "(empty)") + "</p>"
    if payload.get("descriptionIssues"):
        html += "<p class=\"warning\">Issues:</p><ul>"
        for issue in payload["descriptionIssues"]:
            html += f"<li>{issue}</li>"
        html += "</ul>"
    else:
        html += "<p class=\"warning\">No description issues detected.</p>"
    html += "</div>"
    html += "<div class=\"card\"><h3>Validation</h3><p>Pass: " + str(summary.get("passCount", 0)) + " | Warning: " + str(summary.get("warningCount", 0)) + " | Blocker: " + str(summary.get("blockerCount", 0)) + "</p>"
    for result in payload.get("results", []):
        html += f"<p><strong>{result.get('severity', '')}</strong>: {result.get('ruleId', '')} - {result.get('message', '')}</p>"
    html += "</div>"
    html += "<div class=\"card\"><h3>BOM coordinator audit</h3>"
    if payload.get("bomauditRequired"):
        html += "<p class=\"required\">Audit required before BOM population.</p>"
    else:
        html += "<p>No audit required.</p>"
    html += "<div class=\"actions\"><button class=\"approve\">Approve</button><button class=\"request\">Request changes</button><button class=\"block\">Block</button></div><ul>"
    for action in payload.get("reviewActions", []):
        html += f"<li>{action}</li>"
    html += "</ul></div>"
    html += "</div></div></body></html>"
    output_path.write_text(html, encoding="utf-8")
