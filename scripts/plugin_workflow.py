import json
from pathlib import Path
from typing import Any, Dict, List


def build_plugin_payload(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    plugin_ecns: List[Dict[str, Any]] = []
    for ecn in dashboard.get("ecns", []):
        description = ecn.get("description", "") or ""
        issues = []
        if not description.strip():
            issues.append("ECN description is empty.")
        elif len(description.split()) < 8:
            issues.append("ECN description is too short for proper review.")

        if "assembly" not in description.lower() and ecn.get("affectedAssembly"):
            issues.append("Description does not mention the affected assembly.")

        if "change" not in description.lower() and "replace" not in description.lower() and "remove" not in description.lower():
            issues.append("Description does not clearly describe the requested change.")

        audit_required = ecn.get("blockerCount", 0) > 0 or ecn.get("warningCount", 0) > 0
        plugin_ecns.append(
            {
                "ecnId": ecn.get("ecnId"),
                "title": ecn.get("title"),
                "affectedAssembly": ecn.get("affectedAssembly"),
                "description": description,
                "descriptionIssues": issues,
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
        )

    return {"ecns": plugin_ecns}


def write_plugin_dashboard(payload: Dict[str, Any], output_path: Path | str) -> None:
    output_path = Path(output_path)
    html = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>Windchill Plugin Workflow</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; background: #f6f8fb; color: #1f2937; }
    .card { border: 1px solid #d1d5db; padding: 16px; margin-bottom: 16px; border-radius: 10px; background: white; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 12px; margin-top: 12px; }
    .panel { border: 1px solid #e5e7eb; border-radius: 8px; padding: 12px; background: #fafafa; }
    .warning { color: #b45309; font-weight: bold; }
    .required { color: #b91c1c; font-weight: bold; }
    .ok { color: #047857; font-weight: bold; }
    .pill { display: inline-block; padding: 4px 8px; border-radius: 999px; font-size: 12px; font-weight: bold; }
    .pill.review { background: #fef3c7; color: #92400e; }
    .pill.blocker { background: #fee2e2; color: #991b1b; }
    .pill.approve { background: #dcfce7; color: #166534; }
    .actions button { margin-right: 8px; padding: 8px 12px; border: none; border-radius: 6px; cursor: pointer; color: white; font-weight: bold; }
    .actions .approve { background: #047857; }
    .actions .request { background: #b45309; }
    .actions .block { background: #b91c1c; }
  </style>
</head>
<body>
  <h1>Windchill ECN Plugin Review Panel</h1>
  <p>This view mirrors a Windchill-side reviewer experience with description checks, validation results, and BOM coordinator actions.</p>
"""
    for ecn in payload.get("ecns", []):
        summary = ecn.get("validationSummary", {})
        html += f"<div class=\"card\"><h2>{ecn['ecnId']} - {ecn.get('title', '')}</h2>"
        html += f"<p><strong>Affected assembly:</strong> {ecn.get('affectedAssembly', '')}</p>"
        html += f"<p><strong>Decision:</strong> <span class=\"pill {summary.get('decision','review').lower()}\">{summary.get('decision', 'REVIEW').upper()}</span></p>"
        html += "<div class=\"grid\">"
        html += "<div class=\"panel\"><h3>Description</h3><p>" + (ecn.get("description") or "(empty)") + "</p>"
        if ecn.get("descriptionIssues"):
            html += "<p class=\"warning\"><strong>Issues:</strong></p><ul>"
            for issue in ecn["descriptionIssues"]:
                html += f"<li>{issue}</li>"
            html += "</ul>"
        else:
            html += "<p class=\"ok\">No description issues detected.</p>"
        html += "</div>"

        html += "<div class=\"panel\"><h3>Validation findings</h3>"
        html += f"<p>Pass: {summary.get('passCount', 0)} | Warning: {summary.get('warningCount', 0)} | Blocker: {summary.get('blockerCount', 0)}</p>"
        for result in ecn.get("results", []):
            severity = result.get("severity", "")
            html += f"<p><strong>{severity}</strong>: {result.get('ruleId', '')} - {result.get('message', '')}</p>"
        html += "</div>"

        html += "<div class=\"panel\"><h3>BOM coordinator actions</h3>"
        if ecn.get("bomauditRequired"):
            html += "<p class=\"required\"><strong>Audit required before BOM population.</strong></p>"
        else:
            html += "<p class=\"ok\"><strong>No BOM audit required.</strong></p>"
        html += "<div class=\"actions\">"
        html += "<button class=\"approve\">Approve</button>"
        html += "<button class=\"request\">Request changes</button>"
        html += "<button class=\"block\">Block</button>"
        html += "</div><ul>"
        for action in ecn.get("reviewActions", []):
            html += f"<li>{action}</li>"
        html += "</ul></div>"
        html += "</div></div>"
    html += "</body></html>"
    output_path.write_text(html, encoding="utf-8")
