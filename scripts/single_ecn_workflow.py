import html as html_lib
from pathlib import Path
from typing import Any, Dict, List

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ecn_checker import check_description_issues


def build_single_ecn_view(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    ecn = dashboard.get("ecns", [{}])[0]
    description = ecn.get("description", "") or ""
    description_issues = check_description_issues(ecn)

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
<html lang="en">
<head>
  <meta charset="utf-8" />
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
  <h1>Single ECN Review Workflow</h1>
"""
    summary = payload.get("validationSummary", {})
    html += f"<div class=\"container\"><div class=\"card\"><h2>{html_lib.escape(str(payload.get('ecnId')))}: {html_lib.escape(str(payload.get('title')))}</h2>"
    html += f"<p><strong>Assembly:</strong> {html_lib.escape(str(payload.get('affectedAssembly')))}</p></div>"
    html += "<div class=\"card\"><h3>Description</h3><p>" + html_lib.escape(payload.get("description") or "(empty)") + "</p>"
    
    if payload.get("descriptionIssues"):
        html += "<p class=\"warning\">Issues:</p><ul>"
        for issue in payload["descriptionIssues"]:
            html += f"<li>{html_lib.escape(issue)}</li>"
        html += "</ul>"
    else:
        html += "<p class=\"warning\">No description issues detected.</p>"
        
    html += "</div>"
    html += f"<div class=\"card\"><h3>Validation</h3><p>Pass: {summary.get('passCount', 0)} | Warning: {summary.get('warningCount', 0)} | Blocker: {summary.get('blockerCount', 0)}</p>"
    for result in payload.get("results", []):
        html += f"<p><strong>{html_lib.escape(result.get('severity', ''))}</strong>: {html_lib.escape(result.get('ruleId', ''))} - {html_lib.escape(result.get('message', ''))}</p>"
    html += "</div>"
    html += "<div class=\"card\"><h3>BOM coordinator audit</h3>"
    if payload.get("bomauditRequired"):
        html += "<p class=\"required\">Audit required before BOM population.</p>"
    else:
        html += "<p>No audit required.</p>"
    html += "<div class=\"actions\"><button class=\"approve\">Approve</button><button class=\"request\">Request changes</button><button class=\"block\">Block</button></div><ul>"
    for action in payload.get("reviewActions", []):
        html += f"<li>{html_lib.escape(action)}</li>"
    html += "</ul></div></div></body></html>"

    output_path.write_text(html, encoding="utf-8")