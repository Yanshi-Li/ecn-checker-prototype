import html as html_lib
import importlib.util
from pathlib import Path
from typing import Any, Dict, List

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ecn_checker import check_description_issues


def build_plugin_payload(dashboard: Dict[str, Any]) -> Dict[str, Any]:
    plugin_ecns: List[Dict[str, Any]] = []
    for ecn in dashboard.get("ecns", []):
        description = ecn.get("description", "") or ""
        issues = check_description_issues(ecn)

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
<html lang="en">
<head>
  <meta charset="utf-8" />
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
    .actions button { margin-right: 8px; padding: 8px 12px; border: none; border-radius: 6px; color: white; font-weight: bold; cursor: pointer; }
    .actions .approve { background: #047857; }
    .actions .request { background: #b45309; }
    .actions .block { background: #b91c1c; }
  </style>
</head>
<body>
  <h1>Windchill Plugin Workflow Dashboard</h1>
"""
    for ecn in payload.get("ecns", []):
        summary = ecn.get("validationSummary", {})
        html += f"<div class=\"card\"><h2>{html_lib.escape(str(ecn.get('ecnId')))}: {html_lib.escape(str(ecn.get('title')))}</h2>"
        html += f"<p><strong>Assembly:</strong> {html_lib.escape(str(ecn.get('affectedAssembly')))}</p><div class=\"grid\">"
        
        html += f"<div class=\"panel\"><h3>Description analysis</h3><p>{html_lib.escape(ecn.get('description') or '(empty)')}</p>"
        if ecn.get("descriptionIssues"):
            html += "<p class=\"warning\">Issues:</p><ul>"
            for issue in ecn["descriptionIssues"]:
                html += f"<li>{html_lib.escape(issue)}</li>"
            html += "</ul>"
        else:
            html += "<p class=\"ok\">No description issues detected.</p>"
        html += "</div>"

        html += "<div class=\"panel\"><h3>Validation findings</h3>"
        html += f"<p>Pass: {summary.get('passCount', 0)} | Warning: {summary.get('warningCount', 0)} | Blocker: {summary.get('blockerCount', 0)}</p>"
        for result in ecn.get("results", []):
            severity = html_lib.escape(result.get("severity", ""))
            html += f"<p><strong>{severity}</strong>: {html_lib.escape(result.get('ruleId', ''))} - {html_lib.escape(result.get('message', ''))}</p>"
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
            html += f"<li>{html_lib.escape(action)}</li>"
        html += "</ul></div></div></div>"

    html += "</body></html>"
    output_path.write_text(html, encoding="utf-8")