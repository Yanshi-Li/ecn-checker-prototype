import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from stages.dashboard import _render_ai_flags


def test_dashboard_does_not_report_no_flags_for_unsupported_non_clear_assessment():
    html = _render_ai_flags(
        {
            "overall_risk": "HIGH",
            "description_quality": "VAGUE",
            "flags": [],
            "ai_available": True,
            "response_status": "INCOMPLETE",
        }
    )

    assert "Manual review is required" in html
    assert "No AI flags." not in html
    assert "Response Status: <strong>INCOMPLETE</strong>" in html


def test_dashboard_reports_no_flags_only_for_a_clear_assessment():
    html = _render_ai_flags(
        {
            "overall_risk": "LOW",
            "description_quality": "CLEAR",
            "flags": [],
            "ai_available": True,
            "response_status": "COMPLETE",
        }
    )

    assert "✅ No AI flags." in html
    assert "Manual review is required" not in html
