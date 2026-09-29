from scripts.stages.dashboard import _render_ai_flags, _render_bom_lines



def test_dashboard_lists_change_defining_bom_fields():
    html = _render_bom_lines([
        {
            "line_number": "1",
            "part_number": "P-1",
            "description": "Bracket",
            "parent_part_no": "A-100",
            "parent_part_description": "Assembly",
            "quantity": "2",
            "unit": "EA",
            "action": "ADD",
            "source": "MBOM",
            "change_section": "BOM_STRUCTURE",
        }
    ])

    for label in ("Parent Part", "Parent Description", "Qty", "Action", "Source", "Change Section"):
        assert label in html
    for value in ("P-1", "A-100", "2", "ADD", "MBOM", "BOM_STRUCTURE"):
        assert value in html


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
