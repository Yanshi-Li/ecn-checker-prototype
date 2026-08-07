"""
Stage 3: AI Advisory (Prompt Engineering)
- Compares ECN description against BOM changes
- Flags vague or contradicting text
- Gracefully degrades if AI is unavailable
"""

import os
import re
import json
import logging

logger = logging.getLogger(__name__)

# ── Optional OpenAI dep ──────────────────────────────────────────────────────
try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

BOM_CAP = 20  # max BOM lines sent to AI


# ── Prompt builder ───────────────────────────────────────────────────────────
def _build_prompt(packet: dict) -> str:
    header = packet.get("header", {})
    bom = packet.get("bom", [])
    truncated = len(bom) > BOM_CAP

    bom_summary = "\n".join(
        f"  Line {r.get('line_number','?')}: {r.get('part_number','?')} — "
        f"{r.get('description','?')} (qty: {r.get('quantity','?')})"
        for r in bom[:BOM_CAP]
    )

    if truncated:
        bom_summary += f"\n  ... ({len(bom) - BOM_CAP} additional lines truncated)"
        logger.warning(
            "BOM has %d lines; only first %d sent to AI. Review may be incomplete.",
            len(bom), BOM_CAP,
        )

    prompt = f"""You are an ECN (Engineering Change Notice) quality reviewer.

ECN ID      : {header.get('ecn_id', 'N/A')}
Title       : {header.get('title', 'N/A')}
Change Type : {header.get('change_type', 'N/A')}
Author      : {header.get('author', 'N/A')}
Date        : {header.get('date', 'N/A')}

ECN Description:
\"\"\"{header.get('description', '')}\"\"\"

BOM Changes:
{bom_summary}

Review tasks:
1. Does the ECN description clearly explain WHY this change is being made?
2. Are there BOM line items that CONTRADICT or are NOT mentioned in the description?
3. Is the description vague, ambiguous, or missing critical engineering context?
4. Are there any obvious risks or missing approvals implied by the changes?

Respond in JSON with this exact structure:
{{
  "overall_risk": "LOW | MEDIUM | HIGH",
  "description_quality": "CLEAR | VAGUE | CONTRADICTING",
  "flags": [
    {{
      "type": "VAGUE_TEXT | CONTRADICTION | MISSING_CONTEXT | RISK",
      "detail": "specific explanation",
      "line_number": null
    }}
  ],
  "recommendation": "short summary for the BOM Coordinator"
}}"""
    return prompt


# ── AI call ──────────────────────────────────────────────────────────────────
def _call_openai(prompt: str) -> dict:
    """Call OpenAI ChatCompletion and parse JSON response."""
    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are a precise engineering document reviewer. "
                                          "Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        max_tokens=800,
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present (e.g. ```json\n...\n```)
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return json.loads(raw)


# ── Fallback (AI unavailable) ─────────────────────────────────────────────────
def _rule_based_advisory(packet: dict) -> dict:
    """
    Fallback advisory when AI is unavailable.
    Uses simple heuristics to flag obvious issues.
    As per flowchart: 'System continues with Rule Engine checks only'.
    """
    flags = []
    description = packet["header"].get("description", "")

    if len(description) < 20:
        flags.append({
            "type": "VAGUE_TEXT",
            "detail": "ECN description is very short (< 20 characters). "
                      "Please provide a detailed explanation.",
            "line_number": None,
        })

    vague_words = ["misc", "various", "tbd", "update", "change", "fix"]
    matched_vague = [word for word in vague_words if word in description.lower()]
    if matched_vague:
        flags.append({
            "type": "VAGUE_TEXT",
            "detail": f"Description contains vague term(s): {matched_vague}. "
                      f"Please be more specific.",
            "line_number": None,
        })

    # Check if any BOM part numbers appear in the description
    bom_parts = [r.get("part_number", "") for r in packet.get("bom", [])]
    unmentioned = [p for p in bom_parts if p and p not in description]

    if unmentioned:
        flags.append({
            "type": "MISSING_CONTEXT",
            "detail": f"BOM parts not referenced in description: {unmentioned[:5]}",
            "line_number": None,
        })

    # Risk is based on number of distinct problem types flagged
    num_flags = len(flags)
    risk = "HIGH" if num_flags >= 3 else "MEDIUM" if num_flags >= 1 else "LOW"

    return {
        "overall_risk": risk,
        "description_quality": "VAGUE" if flags else "CLEAR",
        "flags": flags,
        "recommendation": (
            "AI unavailable — rule-based advisory used. "
            f"{num_flags} potential issue(s) flagged. Manual review recommended."
        ),
        "ai_available": False,
    }


# ── Public entry point ────────────────────────────────────────────────────────
def run_ai_advisory(packet: dict) -> dict:
    """
    Run AI advisory on the ECN packet.
    Appends ai_flags to packet['validation']['ai_flags'].
    Returns updated packet.
    """
    ai_result = None
    ai_available = False

    if HAS_OPENAI and os.environ.get("OPENAI_API_KEY"):
        try:
            prompt = _build_prompt(packet)
            ai_result = _call_openai(prompt)
            ai_result["ai_available"] = True
            ai_available = True
            logger.info(
                "AI Advisory complete — risk: %s, quality: %s",
                ai_result.get("overall_risk"),
                ai_result.get("description_quality"),
            )
        except Exception as exc:
            logger.warning("AI Advisory failed (%s) — falling back to rule-based.", exc)
    elif HAS_OPENAI:
        logger.warning("OPENAI_API_KEY not set — falling back to rule-based advisory.")

    if not ai_available:
        ai_result = _rule_based_advisory(packet)
        logger.info("AI Advisory: using rule-based fallback.")

    packet["validation"]["ai_flags"] = ai_result
    return packet