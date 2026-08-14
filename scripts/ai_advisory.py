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
from pathlib import Path


def _load_local_env() -> None:
    """Load local .env values without requiring extra packages."""
    repo_root = Path(__file__).resolve().parent.parent
    env_path = repo_root / ".env"
    if not env_path.exists():
        return

    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_local_env()

logger = logging.getLogger(__name__)

# ── Optional OpenAI dep ──────────────────────────────────────────────────────
try:
    import openai
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

BOM_CAP = 20  # max BOM lines sent to AI
PART_NUMBER_PATTERN = re.compile(r"\b[A-Z]{1,4}-\d{2,8}(?:-[A-Z0-9]+)?\b")
ACTION_ALIASES = {
    "add": "ADD",
    "insert": "ADD",
    "introduce": "ADD",
    "remove": "REMOVE",
    "delete": "REMOVE",
    "drop": "REMOVE",
    "replace": "REPLACE",
    "swap": "REPLACE",
    "substitute": "REPLACE",
    "modify": "MODIFY",
    "update": "MODIFY",
    "change": "MODIFY",
}
VERB_FIRST_WORDS = {"replace", "add", "remove", "update", "change", "fix", "modify"}


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
 
Validate semantic advisory rules:
- A01: Description must semantically align with BOM actions.
- A02: Parts mentioned in the description must appear in BOM rows.
- A03: Action verbs in description must align with BOM task/action values.
- A04: Products affected must align with BOM parent assemblies when parent fields exist.
- A05: Part descriptions should begin with a noun-like naming word, not an action verb.
 
Return only a single compact JSON object. No markdown fences, no prose, no comments.
Use this exact structure:
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


def _extract_actions(text: str) -> set[str]:
    actions = set()
    lowered = (text or "").lower()
    for token, normalized in ACTION_ALIASES.items():
        if token in lowered:
            actions.add(normalized)
    return actions


def _extract_bom_actions(packet: dict) -> set[str]:
    actions = set()
    for row in packet.get("bom", []):
        raw = (
            row.get("action")
            or row.get("task")
            or row.get("change_type")
            or ""
        )
        mapped = ACTION_ALIASES.get(str(raw).strip().lower())
        if mapped:
            actions.add(mapped)
    header_action = ACTION_ALIASES.get(
        str(packet.get("header", {}).get("change_type", "")).strip().lower()
    )
    if header_action:
        actions.add(header_action)
    return actions


def _split_csv_values(value: str) -> set[str]:
    if not value:
        return set()
    items = []
    for token in re.split(r"[;,/|]", value):
        cleaned = token.strip()
        if cleaned:
            items.append(cleaned)
    return set(items)


def _rule_flag(rule_id: str, flag_type: str, detail: str, line_number=None) -> dict:
    return {
        "rule_id": rule_id,
        "type": flag_type,
        "detail": detail,
        "line_number": line_number,
    }


# ── AI call ──────────────────────────────────────────────────────────────────
def _resolve_llm_config() -> dict | None:
    """Resolve provider config for OpenAI-compatible API clients."""
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key:
        return {
            "provider": "gemini",
            "api_key": gemini_key,
            "base_url": os.environ.get(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            "model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        }

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        return {
            "provider": "openai",
            "api_key": openai_key,
            "base_url": os.environ.get("OPENAI_BASE_URL", "https://gateway.aitools.corp.fisherpaykel.com/v1"),
            "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        }

    return None


def _try_parse_json(raw: str) -> dict:
    """Parse a JSON object from model output, tolerating markdown fences or truncation."""
    if not raw:
        raise json.JSONDecodeError("empty response", raw, 0)

    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start == -1:
        raise
    candidate = cleaned[start:]
    if candidate.endswith(","):
        candidate = candidate.rstrip(", ")
    while candidate.count("{") > candidate.count("}"):
        candidate += "}"
    if candidate and candidate[-1] == ",":
        candidate = candidate.rstrip(", ")
    if candidate.count("[") > candidate.count("]"):
        candidate += "]" * (candidate.count("[") - candidate.count("]"))
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        end = candidate.rfind("}")
        if end > start:
            repaired = candidate[:end + 1].rstrip(", ")
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass
        raise


def _call_openai(prompt: str, config: dict) -> dict:
    """Call OpenAI-compatible ChatCompletion endpoint and parse JSON response."""
    client_kwargs = {"api_key": config["api_key"]}
    if config.get("base_url"):
        client_kwargs["base_url"] = config["base_url"]
    client = openai.OpenAI(**client_kwargs)
    response = client.chat.completions.create(
        model=config["model"],
        messages=[
            {"role": "system", "content": "You are a precise engineering document reviewer. "
                                          "Always respond with valid JSON only."},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
        temperature=0.2,
        max_tokens=800,
    )
    raw = response.choices[0].message.content.strip()
    return _try_parse_json(raw)


# ── Fallback (AI unavailable) ─────────────────────────────────────────────────
def _rule_based_advisory(packet: dict) -> dict:
    """
    Fallback advisory when AI is unavailable.
    Uses simple heuristics to flag obvious issues.
    As per flowchart: 'System continues with Rule Engine checks only'.
    """
    flags = []
    description = packet["header"].get("description", "")
    description_actions = _extract_actions(description)
    bom_actions = _extract_bom_actions(packet)

    if len(description) < 20:
        flags.append(
            _rule_flag(
                "A01",
                "VAGUE_TEXT",
                "ECN description is very short (< 20 characters). "
                "Please provide a detailed explanation.",
            )
        )

    vague_words = ["misc", "various", "tbd", "update", "change", "fix"]
    matched_vague = [word for word in vague_words if word in description.lower()]
    if matched_vague:
        flags.append(
            _rule_flag(
                "A01",
                "VAGUE_TEXT",
                f"Description contains vague term(s): {matched_vague}. "
                f"Please be more specific.",
            )
        )

    # Check if any BOM part numbers appear in the description
    bom_parts = {
        str(r.get("part_number", "")).strip()
        for r in packet.get("bom", [])
        if str(r.get("part_number", "")).strip()
    }
    description_parts = set(PART_NUMBER_PATTERN.findall(description))
    unmentioned = sorted([p for p in bom_parts if p not in description])

    if unmentioned:
        flags.append(
            _rule_flag(
                "A01",
                "MISSING_CONTEXT",
                f"BOM parts not referenced in description: {unmentioned[:5]}",
            )
        )

    extra_description_parts = sorted(description_parts - bom_parts)
    if extra_description_parts:
        flags.append(
            _rule_flag(
                "A02",
                "MISSING_CONTEXT",
                f"Description mentions parts not found in BOM rows: {extra_description_parts[:5]}",
            )
        )

    if description_actions and bom_actions and description_actions.isdisjoint(bom_actions):
        flags.append(
            _rule_flag(
                "A03",
                "CONTRADICTION",
                f"Description actions {sorted(description_actions)} do not align with BOM actions {sorted(bom_actions)}.",
            )
        )

    affected_products = _split_csv_values(packet.get("header", {}).get("affected_parts", ""))
    bom_parents = {
        str(
            row.get("parent_part_no")
            or row.get("parent")
            or row.get("parent_part")
            or row.get("assembly")
            or row.get("module")
            or row.get("parent_part_module")
            or ""
        ).strip()
        for row in packet.get("bom", [])
    }
    bom_parents = {value for value in bom_parents if value}
    if affected_products and bom_parents and affected_products.isdisjoint(bom_parents):
        flags.append(
            _rule_flag(
                "A04",
                "CONTRADICTION",
                f"Products affected {sorted(affected_products)} do not align with BOM parent assemblies {sorted(bom_parents)}.",
            )
        )

    for row in packet.get("bom", []):
        part_desc = str(row.get("description", "")).strip()
        if not part_desc:
            continue
        first_word = part_desc.split()[0].lower()
        if first_word in VERB_FIRST_WORDS:
            flags.append(
                _rule_flag(
                    "A05",
                    "VAGUE_TEXT",
                    f"Part description should start with a naming noun, not action verb '{first_word}'.",
                    row.get("line_number", "?"),
                )
            )

    # Risk is based on number of distinct problem types flagged
    num_flags = len(flags)
    risk = "HIGH" if num_flags >= 3 else "MEDIUM" if num_flags >= 1 else "LOW"
    if any(flag["type"] == "CONTRADICTION" for flag in flags):
        quality = "CONTRADICTING"
    elif flags:
        quality = "VAGUE"
    else:
        quality = "CLEAR"

    return {
        "overall_risk": risk,
        "description_quality": quality,
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
    llm_config = _resolve_llm_config()

    if HAS_OPENAI and llm_config:
        try:
            prompt = _build_prompt(packet)
            ai_result = _call_openai(prompt, llm_config)
            ai_result["ai_available"] = True
            ai_available = True
            logger.info(
                "AI Advisory complete (%s:%s) — risk: %s, quality: %s",
                llm_config["provider"],
                llm_config["model"],
                ai_result.get("overall_risk"),
                ai_result.get("description_quality"),
            )
        except Exception as exc:
            logger.warning("AI Advisory failed (%s) — falling back to rule-based.", exc)
    elif HAS_OPENAI:
        logger.warning(
            "No GEMINI_API_KEY or OPENAI_API_KEY set — falling back to rule-based advisory."
        )

    if not ai_available:
        ai_result = _rule_based_advisory(packet)
        logger.info("AI Advisory: using rule-based fallback.")

    packet["validation"]["ai_flags"] = ai_result
    return packet