import pytest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
from ai_advisory import _build_prompt, _resolve_llm_config, _rule_based_advisory, run_ai_advisory
from stages import ai_advisory as advisory_impl
from intake import build_ecn_packet, REQUIRED_ECN_FIELDS


def _packet(description="", bom=None, header_overrides=None):
    header = {f: "val" for f in REQUIRED_ECN_FIELDS}
    header["description"] = description
    if header_overrides:
        header.update(header_overrides)
    return build_ecn_packet([header], bom or [])


def test_fallback_vague_short_description():
    packet = _packet(description="fix")
    result = _rule_based_advisory(packet)
    assert result["description_quality"] == "VAGUE"
    assert any(f["type"] == "VAGUE_TEXT" for f in result["flags"])


def test_fallback_good_description():
    packet = _packet(
        description="Replacing capacitor AB-1234 with AB-5678 to resolve thermal failures."
    )
    result = _rule_based_advisory(packet)
    assert result["overall_risk"] in ("LOW", "MEDIUM")


def test_fallback_unmentioned_parts():
    packet = _packet(
        description="Updating the resistor assembly.",
        bom=[{"part_number": "AB-9999", "quantity": "1", "line_number": "1"}]
    )
    result = _rule_based_advisory(packet)
    assert any(f["type"] == "MISSING_CONTEXT" for f in result["flags"])


def test_result_structure():
    packet = _packet(description="Some description text here for testing.")
    result = _rule_based_advisory(packet)
    assert "overall_risk" in result
    assert "description_quality" in result
    assert "flags" in result
    assert "recommendation" in result
    assert result["response_status"] == "COMPLETE"


def test_normalise_adds_review_flag_for_unsupported_non_clear_assessment():
    result = advisory_impl._normalise_ai_result(
        {
            "overall_risk": "HIGH",
            "description_quality": "VAGUE",
            "flags": [],
            "recommendation": "",
        }
    )

    assert result["response_status"] == "INCOMPLETE"
    assert result["flags"][0]["rule_id"] == "AI_RESPONSE_INCOMPLETE"
    assert "supporting flags" in result["flags"][0]["detail"]
    assert result["recommendation"]


def test_normalise_keeps_a_supported_or_clear_assessment_complete():
    result = advisory_impl._normalise_ai_result(
        {
            "overall_risk": "LOW",
            "description_quality": "CLEAR",
            "flags": [],
            "recommendation": "No action required.",
        }
    )

    assert result["response_status"] == "COMPLETE"
    assert result["flags"] == []


@pytest.mark.parametrize("raw_flags", [None, "not-a-list", [{"type": "RISK"}, "invalid"]])
def test_normalise_marks_invalid_flag_shapes_incomplete(raw_flags):
    result = advisory_impl._normalise_ai_result(
        {
            "overall_risk": "LOW",
            "description_quality": "CLEAR",
            "flags": raw_flags,
        }
    )

    assert result["response_status"] == "INCOMPLETE"
    assert result["flags"][-1]["rule_id"] == "AI_RESPONSE_INCOMPLETE"


def test_live_ai_path_normalises_an_incomplete_model_response(monkeypatch):
    packet = _packet(description="A detailed description for a mocked AI call.")
    monkeypatch.setattr(advisory_impl, "HAS_OPENAI", True)
    monkeypatch.setattr(advisory_impl, "_resolve_llm_config", lambda: {"api_key": "test"})
    monkeypatch.setattr(
        advisory_impl,
        "_call_openai",
        lambda prompt, config: {
            "overall_risk": "HIGH",
            "description_quality": "VAGUE",
            "flags": [],
        },
    )

    result = run_ai_advisory(packet)["validation"]["ai_flags"]
    assert result["ai_available"] is True
    assert result["response_status"] == "INCOMPLETE"
    assert result["flags"][0]["rule_id"] == "AI_RESPONSE_INCOMPLETE"



# ── Tests reflecting ECN-2026-002 (cost reduction, well-formed) ──────────────

def test_ecn_2026_002_good_description():
    # ECN-2026-002 has a detailed, specific description — should not be VAGUE
    packet = _packet(
        description=(
            "Replace Resistor R301 (C-300) with lower-cost equivalent C-350 "
            "to reduce unit cost by 15%. Supplier-D has been qualified and approved."
        ),
        bom=[{"part_number": "C-300", "quantity": "4", "line_number": "1"},
             {"part_number": "C-350", "quantity": "4", "line_number": "2"}]
    )
    result = _rule_based_advisory(packet)
    assert result["description_quality"] != "VAGUE"
    assert result["overall_risk"] in ("LOW", "MEDIUM")


def test_ecn_2026_002_parts_mentioned_in_description():
    # Both C-300 and C-350 are referenced in the description — no MISSING_CONTEXT
    packet = _packet(
        description=(
            "Replacing C-300 resistor with C-350 low-cost alternative. "
            "Supplier-D qualified. 15% cost saving expected."
        ),
        bom=[{"part_number": "C-300", "quantity": "4", "line_number": "1"},
             {"part_number": "C-350", "quantity": "4", "line_number": "2"}]
    )
    result = _rule_based_advisory(packet)
    assert not any(f["type"] == "MISSING_CONTEXT" for f in result["flags"])


# ── Tests reflecting ECN-2026-003 (stock shortage, blank description) ────────

def test_ecn_2026_003_blank_description_is_vague():
    # ECN-2026-003 has a blank description — must be flagged as VAGUE
    packet = _packet(description="")
    result = _rule_based_advisory(packet)
    assert result["description_quality"] == "VAGUE"
    assert any(f["type"] == "VAGUE_TEXT" for f in result["flags"])


def test_ecn_2026_003_unmentioned_parts_flagged():
    # C-200 and C-260 are in the BOM but description is blank — MISSING_CONTEXT expected
    packet = _packet(
        description="",
        bom=[{"part_number": "C-200", "quantity": "1", "line_number": "1"},
             {"part_number": "C-260", "quantity": "1", "line_number": "2"}]
    )
    result = _rule_based_advisory(packet)
    assert any(f["type"] == "MISSING_CONTEXT" for f in result["flags"])


def test_prompt_contains_node3_semantic_rules():
    prompt = _build_prompt(_packet(description="replace AB-1001 with AB-1002"))
    assert "A01" in prompt
    assert "A02" in prompt
    assert "A03" in prompt
    assert "A04" in prompt
    assert "A05" in prompt


def test_semantic_A02_description_parts_must_exist_in_bom():
    packet = _packet(
        description="Replace HE-1021 with C-350 due to quality drift.",
        bom=[{"part_number": "C-350", "quantity": "1", "line_number": "1"}],
    )
    result = _rule_based_advisory(packet)
    assert any(f.get("rule_id") == "A02" for f in result["flags"])


def test_semantic_A03_action_mismatch_flagged():
    packet = _packet(
        description="Replace C-300 with C-350 to reduce cost.",
        bom=[{"part_number": "C-350", "quantity": "1", "line_number": "1", "action": "ADD"}],
        header_overrides={"change_type": "add"},
    )
    result = _rule_based_advisory(packet)
    assert any(f.get("rule_id") == "A03" and f["type"] == "CONTRADICTION" for f in result["flags"])
    assert result["description_quality"] == "CONTRADICTING"


def test_semantic_A04_products_affected_vs_parent_assembly():
    packet = _packet(
        description="Add AB-2001 to DW900 assembly for reliability improvement.",
        bom=[
            {
                "part_number": "AB-2001",
                "quantity": "1",
                "line_number": "1",
                "action": "ADD",
                "parent_part_no": "DW900",
            }
        ],
        header_overrides={"affected_parts": "RF600"},
    )
    result = _rule_based_advisory(packet)
    assert any(f.get("rule_id") == "A04" for f in result["flags"])


def test_semantic_A05_part_description_naming_word_check():
    packet = _packet(
        description="Add AB-2001 to improve assembly robustness.",
        bom=[
            {
                "part_number": "AB-2001",
                "description": "Replace connector harness",
                "quantity": "1",
                "line_number": "2",
                "action": "ADD",
            }
        ],
    )
    result = _rule_based_advisory(packet)
    assert any(f.get("rule_id") == "A05" for f in result["flags"])


def test_llm_config_prefers_gemini_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    config = _resolve_llm_config()
    assert config["provider"] == "gemini"
    assert config["model"] == "gemini-2.5-flash"


def test_llm_config_uses_openai_when_gemini_missing(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    config = _resolve_llm_config()
    assert config["provider"] == "openai"
    assert config["model"] == "gpt-4o-mini"