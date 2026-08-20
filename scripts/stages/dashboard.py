"""
Stage 5: Shared Dashboard
- Engineer View: real-time error display with fix guidance
- BOM Coordinator View: full audit package with all flags
Outputs a self-contained HTML file to out/dashboard.html
"""

import json
import logging
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)
OUT_DIR = Path(__file__).parent.parent.parent / "out"


# ── Severity helpers ──────────────────────────────────────────────────────────
def _badge(severity: str) -> str:
    colors = {
        "ERROR":   ("🔴", "#ffe0e0", "#c0392b"),
        "WARNING": ("🟡", "#fff8e0", "#d4a017"),
        "INFO":    ("🔵", "#e0f0ff", "#2980b9"),
    }
    icon, bg, border = colors.get(severity.upper(), ("⚪", "#f5f5f5", "#aaa"))
    return (
        f'<span style="background:{bg};border:1px solid {border};'
        f'padding:2px 8px;border-radius:4px;font-size:0.85em;">'
        f'{icon} {severity}</span>'
    )


def _render_violations(violations: list[dict]) -> str:
    if not violations:
        return '<p style="color:green;">✅ No violations found.</p>'
    rows = ""
    for v in violations:
        rule = v.get("rule_id", "—")
        msg = v.get("message", "")
        sev = v.get("severity", "INFO")
        field = v.get("field", "")
        rows += f"""
        <tr>
          <td><code>{rule}</code></td>
          <td>{_badge(sev)}</td>
          <td><code>{field}</code></td>
          <td>{msg}</td>
        </tr>"""
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:0.9em;">
      <thead>
        <tr style="background:#f0f0f0;">
          <th style="padding:6px;text-align:left;">Rule</th>
          <th style="padding:6px;text-align:left;">Severity</th>
          <th style="padding:6px;text-align:left;">Field</th>
          <th style="padding:6px;text-align:left;">Message</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def _render_context_flags(flags: list[dict]) -> str:
    if not flags:
        return '<p style="color:green;">✅ No context issues found.</p>'
    rows = ""
    for f in flags:
        rows += f"""
        <tr>
          <td><code>{f.get('part_number','')}</code></td>
          <td>{_badge(f.get('severity','INFO'))}</td>
          <td>{f.get('flag_type','')}</td>
          <td>{f.get('message','')}</td>
        </tr>"""
    return f"""
    <table style="width:100%;border-collapse:collapse;font-size:0.9em;">
      <thead>
        <tr style="background:#f0f0f0;">
          <th style="padding:6px;text-align:left;">Part</th>
          <th style="padding:6px;text-align:left;">Severity</th>
          <th style="padding:6px;text-align:left;">Type</th>
          <th style="padding:6px;text-align:left;">Message</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>"""


def _render_ai_flags(ai_flags: dict) -> str:
    if not ai_flags:
        return '<p>AI Advisory did not run.</p>'

    risk_colors = {"LOW": "green", "MEDIUM": "orange", "HIGH": "red"}
    risk = ai_flags.get("overall_risk", "UNKNOWN")
    quality = ai_flags.get("description_quality", "UNKNOWN")
    recommendation = ai_flags.get("recommendation", "")
    available = ai_flags.get("ai_available", False)
    ai_label = "🤖 AI Advisory" if available else "⚙️ Rule-Based Advisory (AI Unavailable)"

    flag_rows = ""
    for flag in ai_flags.get("flags", []):
        flag_rows += f"""
        <tr>
          <td>{flag.get('type','')}</td>
          <td>{flag.get('detail','')}</td>
          <td>{flag.get('line_number') or '—'}</td>
        </tr>"""

    flag_table = f"""
    <table style="width:100%;border-collapse:collapse;font-size:0.9em;">
      <thead>
        <tr style="background:#f0f0f0;">
          <th style="padding:6px;text-align:left;">Flag Type</th>
          <th style="padding:6px;text-align:left;">Detail</th>
          <th style="padding:6px;text-align:left;">Line</th>
        </tr>
      </thead>
      <tbody>{flag_rows if flag_rows else '<tr><td colspan="3">No flags.</td></tr>'}</tbody>
    </table>""" if ai_flags.get("flags") else '<p style="color:green;">✅ No AI flags.</p>'

    return f"""
    <p><strong>{ai_label}</strong></p>
    <p>Overall Risk: <strong style="color:{risk_colors.get(risk,'black')};">{risk}</strong>
       &nbsp;|&nbsp; Description Quality: <strong>{quality}</strong></p>
    <p><em>{recommendation}</em></p>
    {flag_table}"""


# ── Summary bar ───────────────────────────────────────────────────────────────
def _summary_counts(packet: dict) -> tuple[int, int]:
    violations = packet["validation"].get("rule_violations", [])
    context    = packet["validation"].get("context_flags", [])
    ai         = packet["validation"].get("ai_flags", {})

    # Guard: if ai_flags was accidentally stored as a list, wrap it
    if isinstance(ai, list):
        ai = {"flags": ai}

    errors = (
        sum(1 for v in violations if v.get("severity") == "ERROR") +
        sum(1 for f in context    if f.get("severity") == "ERROR")
    )
    warnings = (
        sum(1 for v in violations if v.get("severity") == "WARNING") +
        sum(1 for f in context    if f.get("severity") == "WARNING") +
        len(ai.get("flags", []))
    )
    return errors, warnings


# ── HTML builder ──────────────────────────────────────────────────────────────
def build_dashboard_html(packet: dict) -> str:
    header = packet.get("header", {})
    validation = packet.get("validation", {})
    errors, warnings = _summary_counts(packet)

    status_color = "#c0392b" if errors > 0 else "#d4a017" if warnings > 0 else "#27ae60"
    status_label = "⛔ ERRORS FOUND — Fix Required" if errors > 0 else \
                   "⚠️ WARNINGS — Review Recommended" if warnings > 0 else \
                   "✅ PASSED — Ready for Coordinator Review"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>ECN Dashboard — {header.get('ecn_id','')}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           margin: 0; background: #f4f6f9; color: #333; }}
    .topbar {{ background: #1a237e; color: white; padding: 16px 32px;
               display: flex; justify-content: space-between; align-items: center; }}
    .topbar h1 {{ margin: 0; font-size: 1.4em; }}
    .topbar .meta {{ font-size: 0.85em; opacity: 0.85; }}
    .status-banner {{ background: {status_color}; color: white;
                      padding: 12px 32px; font-weight: bold; font-size: 1.05em; }}
    .container {{ max-width: 1100px; margin: 24px auto; padding: 0 24px; }}
    .card {{ background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);
             margin-bottom: 24px; overflow: hidden; }}
    .card-header {{ background: #e8eaf6; padding: 12px 20px;
                    font-weight: bold; font-size: 1em; border-bottom: 1px solid #c5cae9; }}
    .card-body {{ padding: 16px 20px; }}
    .tab-bar {{ display: flex; background: #283593; }}
    .tab {{ padding: 12px 28px; color: #9fa8da; cursor: pointer;
            font-weight: bold; border-bottom: 3px solid transparent; }}
    .tab.active {{ color: white; border-bottom: 3px solid #ffeb3b; }}
    .tab-content {{ display: none; }}
    .tab-content.active {{ display: block; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ padding: 8px 10px; border: 1px solid #e0e0e0; text-align: left; }}
    th {{ background: #f5f5f5; }}
    .summary-grid {{ display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; }}
    .summary-card {{ text-align: center; padding: 20px; border-radius: 8px;
                     background: white; box-shadow: 0 2px 6px rgba(0,0,0,0.07); }}
    .summary-card .num {{ font-size: 2.5em; font-weight: bold; }}
    code {{ background: #f0f0f0; padding: 1px 5px; border-radius: 3px; }}
    footer {{ text-align: center; padding: 24px; color: #999; font-size: 0.85em; }}
  </style>
</head>
<body>

<div class="topbar">
  <h1>📋 ECN Review Dashboard</h1>
  <div class="meta">
    ECN: <strong>{header.get('ecn_id','N/A')}</strong> &nbsp;|&nbsp;
    Author: {header.get('author','N/A')} &nbsp;|&nbsp;
    Date: {header.get('date','N/A')} &nbsp;|&nbsp;
    Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
  </div>
</div>

<div class="status-banner">{status_label}</div>

<div class="container">

  <!-- Summary Cards -->
  <div class="summary-grid" style="margin-bottom:24px;margin-top:8px;">
    <div class="summary-card">
      <div class="num" style="color:#c0392b;">{errors}</div>
      <div>Errors</div>
    </div>
    <div class="summary-card">
      <div class="num" style="color:#d4a017;">{warnings}</div>
      <div>Warnings</div>
    </div>
    <div class="summary-card">
      <div class="num" style="color:#2980b9;">{len(packet.get('bom',[]))}</div>
      <div>BOM Lines</div>
    </div>
  </div>

  <!-- Tab navigation -->
  <div class="card">
    <div class="tab-bar">
      <div class="tab active" onclick="showTab('engineer')">🔧 Engineer View</div>
      <div class="tab" onclick="showTab('coordinator')">📊 BOM Coordinator View</div>
      <div class="tab" onclick="showTab('ecn-detail')">📄 ECN Detail</div>
    </div>

    <!-- Engineer View -->
    <div id="tab-engineer" class="tab-content active">
      <div class="card-body">
        <h3>⚠️ Real-Time Warnings — Fix Before Resubmitting</h3>
        <div class="card-header">Rule Engine Violations</div>
        {_render_violations(validation.get('rule_violations', []))}
        <br/>
        <div class="card-header">Context Issues</div>
        {_render_context_flags(validation.get('context_flags', []))}
        <br/>
        <div class="card-header">AI Advisory Flags</div>
        {_render_ai_flags(validation.get('ai_flags', {}))}
      </div>
    </div>

    <!-- Coordinator View -->
    <div id="tab-coordinator" class="tab-content">
      <div class="card-body">
        <h3>📦 Pre-Audited Package — BOM Coordinator Review</h3>
        <p><strong>ECN Title:</strong> {header.get('title','N/A')}</p>
        <p><strong>Change Type:</strong> {header.get('change_type','N/A')}</p>
        <p><strong>Description:</strong> {header.get('description','N/A')}</p>
        <hr/>
        <h4>All Rule Violations</h4>
        {_render_violations(validation.get('rule_violations', []))}
        <h4>Parts Context Flags</h4>
        {_render_context_flags(validation.get('context_flags', []))}
        <h4>AI Analysis</h4>
        {_render_ai_flags(validation.get('ai_flags', {}))}
        <hr/>
        <h4>BOM Lines</h4>
        <table>
          <thead>
            <tr>
              <th>Line</th><th>Part Number</th>
              <th>Description</th><th>Qty</th><th>Unit</th>
            </tr>
          </thead>
          <tbody>
            {"".join(
              f"<tr><td>{r.get('line_number','')}</td>"
              f"<td><code>{r.get('part_number','')}</code></td>"
              f"<td>{r.get('description','')}</td>"
              f"<td>{r.get('quantity','')}</td>"
              f"<td>{r.get('unit','')}</td></tr>"
              for r in packet.get('bom', [])
            )}
          </tbody>
        </table>
      </div>
    </div>

    <!-- ECN Detail -->
    <div id="tab-ecn-detail" class="tab-content">
      <div class="card-body">
        <h3>📄 Raw ECN Header</h3>
        <table>
          <tbody>
            {"".join(f"<tr><th>{k}</th><td>{v}</td></tr>"
                     for k, v in header.items())}
          </tbody>
        </table>
        <h3>Raw Validation Data</h3>
        <pre style="background:#f8f8f8;padding:12px;border-radius:6px;
                    overflow:auto;font-size:0.82em;">
{json.dumps(validation, indent=2)}
        </pre>
      </div>
    </div>

  </div><!-- /card -->
</div><!-- /container -->

<footer>ECN Checker — Auto-generated | {datetime.now().year}</footer>

<script>
function showTab(name) {{
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}}
</script>
</body>
</html>"""


# ── Public entry point ────────────────────────────────────────────────────────
def run_dashboard(packet: dict, out_path: str | None = None) -> str:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = out_path or OUT_DIR / "dashboard.html"
    html = build_dashboard_html(packet)
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info("Dashboard written to %s", output_file)
    return str(output_file)