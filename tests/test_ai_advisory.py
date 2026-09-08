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


def test_fallback_does_not_emit_legacy_vague_rule():
    result = _rule_based_advisory(_packet(description="fix"))
    assert result["description_quality"] == "CLEAR"
    assert {flag["rule_id"] for flag in result["flags"]} == {"S01", "S05"}
    assert all(flag["evaluation_status"] == "NOT_EVALUATED" for flag in result["flags"])



def test_fallback_good_description():
    packet = _packet(
        description="Replacing capacitor AB-1234 with AB-5678 to resolve thermal failures."
    )
    result = _rule_based_advisory(packet)
    assert result["overall_risk"] in ("LOW", "MEDIUM")


def test_fallback_marks_llm_owned_alignment_rule_not_evaluated():
    result = _rule_based_advisory(_packet(
        description="Updating the resistor assembly.",
        bom=[{"part_number": "AB-9999", "quantity": "1", "line_number": "1"}],
    ))
    assert any(flag["rule_id"] == "S01" and flag["evaluation_status"] == "NOT_EVALUATED"
               for flag in result["flags"])



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


def test_normalise_enriches_canonical_flag_with_catalogue_metadata():
    result = advisory_impl._normalise_ai_result({
        "overall_risk": "MEDIUM",
        "description_quality": "VAGUE",
        "flags": [{
            "rule_id": "S02",
            "type": "MISSING_CONTEXT",
            "detail": "HE-1021 is not in the BOM.",
            "evidence": "HE-1021",
        }],
    })

    flag = result["flags"][0]
    assert result["response_status"] == "COMPLETE"
    assert flag["rule_id"] == "S02"
    assert flag["severity"] == "BLOCKER"
    assert flag["gate_effect"] == "FAIL"
    assert flag["evidence"] == "HE-1021"



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

def test_ecn_2026_003_blank_description_is_not_legacy_vague():
    packet = _packet(description="")
    result = _rule_based_advisory(packet)
    assert result["description_quality"] == "CLEAR"
    assert any(f["rule_id"] == "S01" and f["evaluation_status"] == "NOT_EVALUATED"
               for f in result["flags"])



def test_ecn_2026_003_bom_context_is_not_attributed_to_s01_without_llm():
    packet = _packet(
        description="",
        bom=[{"part_number": "C-200", "quantity": "1", "line_number": "1"},
             {"part_number": "C-260", "quantity": "1", "line_number": "2"}]
    )
    result = _rule_based_advisory(packet)
    assert not any(f["type"] == "MISSING_CONTEXT" for f in result["flags"])
    assert any(f["rule_id"] == "S01" and f["evaluation_status"] == "NOT_EVALUATED"
               for f in result["flags"])



def test_prompt_contains_catalogue_semantic_rules():
    prompt = _build_prompt(_packet(description="replace AB-1001 with AB-1002"))
    for rule_id in ("S01", "S02", "S03", "S04", "S05"):
        assert rule_id in prompt

    assert "A01" not in prompt
    assert "A05" not in prompt



def test_semantic_S02_description_parts_must_exist_in_bom():
    packet = _packet(
        description="Replace HE-1021 with C-350 due to quality drift.",
        bom=[{"part_number": "C-350", "quantity": "1", "line_number": "1"}],
    )
    result = _rule_based_advisory(packet)
    assert any(f.get("rule_id") == "S02" for f in result["flags"])


def test_semantic_S03_action_mismatch_flagged():
    packet = _packet(
        description="Replace C-300 with C-350 to reduce cost.",
        bom=[{"part_number": "C-350", "quantity": "1", "line_number": "1", "action": "ADD"}],
        header_overrides={"change_type": "add"},
    )
    result = _rule_based_advisory(packet)
    assert any(f.get("rule_id") == "S03" and f["type"] == "CONTRADICTION" for f in result["flags"])
    assert result["description_quality"] == "CONTRADICTING"


def test_semantic_S04_products_affected_vs_parent_assembly():
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
    assert any(f.get("rule_id") == "S04" for f in result["flags"])


def test_semantic_S05_is_not_evaluated_without_llm():
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
    assert any(f.get("rule_id") == "S05" and f["evaluation_status"] == "NOT_EVALUATED"
               for f in result["flags"])




def test_openai_failure_retries_with_gemini(monkeypatch):
    packet = _packet(description="A detailed description for provider failover.")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    calls = []

    def fake_call(prompt, config):
        calls.append(config["provider"])
        if config["provider"] == "openai":
            raise RuntimeError("SSL certificate verify failed")
        return {
            "overall_risk": "LOW",
            "description_quality": "CLEAR",
            "flags": [],
            "recommendation": "No action required.",
        }

    monkeypatch.setattr(advisory_impl, "HAS_OPENAI", True)
    monkeypatch.setattr(advisory_impl, "_call_openai", fake_call)

    result = run_ai_advisory(packet)["validation"]["ai_flags"]

    assert calls == ["openai", "gemini"]
    assert result["provider"] == "gemini"
    assert result["ai_available"] is True


def test_llm_config_prefers_openai_key(monkeypatch):

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-key")
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    config = _resolve_llm_config()
    assert config["provider"] == "openai"
    assert config["model"] == "gpt-4o-mini"


def test_llm_config_uses_gemini_when_openai_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    config = _resolve_llm_config()
    assert config["provider"] == "gemini"
    assert config["model"] == "gemini-2.5-flash"