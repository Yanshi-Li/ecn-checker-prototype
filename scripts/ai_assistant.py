import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Union


Provider = Optional[str]


def _build_summary(ecn: Dict[str, Any]) -> str:
    blockers = ecn.get("blockerCount", 0)
    warnings = ecn.get("warningCount", 0)
    if blockers > 0:
        return f"{ecn['ecnId']} has {blockers} blocker(s) and {warnings} warning(s); reviewer attention is required before BOM population."
    if warnings > 0:
        return f"{ecn['ecnId']} has {warnings} warning(s); the BOM coordinator should review the proposed change carefully."
    return f"{ecn['ecnId']} passed the automated checks and is ready for routine review."


def _risk_level(ecn: Dict[str, Any]) -> str:
    if ecn.get("blockerCount", 0) > 0:
        return "high"
    if ecn.get("warningCount", 0) > 0:
        return "medium"
    return "low"


def _reviewer_actions(ecn: Dict[str, Any]) -> List[str]:
    actions = []
    if ecn.get("blockerCount", 0) > 0:
        actions.append("Resolve all blockers before approval.")
    if ecn.get("warningCount", 0) > 0:
        actions.append("Confirm warnings with the BOM coordinator.")
    actions.append("Require human review before populating BOM data.")
    return actions


def _build_prompt(ecn: Dict[str, Any]) -> str:
    results = ecn.get("results", [])
    summary_lines = [
        f"ECN ID: {ecn.get('ecnId', 'unknown')}",
        f"Title: {ecn.get('title', '')}",
        f"Status: {ecn.get('status', '')}",
        f"Affected assembly: {ecn.get('affectedAssembly', '')}",
        f"Quality approval: {ecn.get('qualityApproval', False)}",
        f"Pass count: {ecn.get('passCount', 0)}",
        f"Warning count: {ecn.get('warningCount', 0)}",
        f"Blocker count: {ecn.get('blockerCount', 0)}",
    ]
    if results:
        summary_lines.append("Rules:")
        for result in results:
            summary_lines.append(
                f"- {result.get('severity', '')}: {result.get('ruleId', '')} - {result.get('message', '')}"
            )
    prompt = (
        "You are helping a BOM coordinator review an ECN. "
        "Return valid JSON with keys: summary, riskLevel, reviewerActions. "
        "riskLevel must be one of: low, medium, high. "
        "reviewerActions must be a list of short imperative strings.\n\n"
        + "\n".join(summary_lines)
    )
    return prompt


def _call_llm(prompt: str) -> Optional[Dict[str, Any]]:
    provider = os.getenv("ECN_LLM_PROVIDER", "openai").lower()

    if provider == "ollama":
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
        payload = {"model": model, "prompt": prompt, "stream": False}
        req = urllib.request.Request(
            f"{base_url}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
                text = body.get("response", "").strip()
                return _parse_json_response(text)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
            return None

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return None
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1/chat/completions")
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": "You help review engineering change notices."}, {"role": "user", "content": prompt}],
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            base_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                body = json.loads(response.read().decode("utf-8"))
                content = body.get("choices", [{}])[0].get("message", {}).get("content", "")
                return _parse_json_response(content)
        except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError, IndexError):
            return None

    return None


def _parse_json_response(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        payload = json.loads(stripped)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        return None
    return None


def _assistant_payload(ecn: Dict[str, Any]) -> Dict[str, Any]:
    llm_payload = _call_llm(_build_prompt(ecn))
    if llm_payload:
        summary = llm_payload.get("summary") or _build_summary(ecn)
        risk_level = llm_payload.get("riskLevel") or _risk_level(ecn)
        reviewer_actions = llm_payload.get("reviewerActions") or _reviewer_actions(ecn)
        return {
            "ecnId": ecn.get("ecnId"),
            "summary": str(summary),
            "riskLevel": str(risk_level).lower(),
            "reviewerActions": [str(action) for action in reviewer_actions],
        }

    return {
        "ecnId": ecn.get("ecnId"),
        "summary": _build_summary(ecn),
        "riskLevel": _risk_level(ecn),
        "reviewerActions": _reviewer_actions(ecn),
    }


def generate_assistant_output(dashboard: Dict[str, Any], output_path: Union[Path, str], html_path: Union[Path, str]) -> Dict[str, Any]:
    ecns = []
    for ecn in dashboard.get("ecns", []):
        ecns.append(_assistant_payload(ecn))

    payload = {"ecns": ecns}
    output_path = Path(output_path)
    html_path = Path(html_path)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    html = """<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <title>Hybrid ECN Assistant</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 24px; }
    .card { border: 1px solid #ddd; padding: 16px; margin-bottom: 16px; border-radius: 8px; }
    .high { color: #b91c1c; font-weight: bold; }
    .medium { color: #b45309; font-weight: bold; }
    .low { color: #047857; font-weight: bold; }
  </style>
</head>
<body>
  <h1>Hybrid ECN Assistant</h1>
  <p>This page shows AI-assisted reviewer guidance generated from the checker results.</p>
"""
    for ecn in ecns:
        html += f"<div class=\"card\"><h2>{ecn['ecnId']}</h2><p><strong>Summary:</strong> {ecn['summary']}</p><p><strong>Risk:</strong> <span class=\"{ecn['riskLevel']}\">{ecn['riskLevel'].upper()}</span></p><ul>"
        for action in ecn["reviewerActions"]:
            html += f"<li>{action}</li>"
        html += "</ul></div>"
    html += "</body></html>"
    html_path.write_text(html, encoding="utf-8")
    return payload
