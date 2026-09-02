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
import httpx



def _load_local_env() -> None:
    """Load local .env values without requiring extra packages."""
    repo_root = Path(__file__).resolve().parent.parent.parent
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


def _get_config_value(key: str, default: str = "") -> str:
    """Read Streamlit secrets first, then retain local environment support."""
    try:
        import streamlit as st
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        if get_script_run_ctx(suppress_warning=True) is not None:
            value = st.secrets.get(key)
            if value is not None:
                return str(value).strip()
    except Exception:
        # No Streamlit runtime/secrets configured: use the established CLI path.
        pass

    return os.environ.get(key, default).strip()




# ── Optional OpenAI dep ──────────────────────────────────────────────────────


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
VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
VALID_DESCRIPTION_QUALITIES = {"CLEAR", "VAGUE", "CONTRADICTING"}


# ── Prompt builder ───────────────────────────────────────────────────────────
def _build_prompt(packet: dict) -> str:
    header = packet.get("header", {})
    bom = packet.get("bom", [])
    truncated = len(bom) > BOM_CAP

    # Map PDF-parsed keys to prompt-friendly values
    ecn_id      = header.get("change_notice_number") or header.get("ecn_id", "N/A")
    title       = header.get("name_of_change") or header.get("title", "N/A")
    description = header.get("description") or header.get("description_of_change", "")
    change_type = header.get("change_type", "N/A")
    author      = header.get("author", "N/A")
    date        = header.get("date", "N/A")
    affected    = header.get("products_affected") or header.get("affected_parts", "N/A")
    reason      = header.get("reason_for_change", "N/A")

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

ECN ID            : {ecn_id}
Title             : {title}
Change Type       : {change_type}
Author            : {author}
Date              : {date}
Products Affected : {affected}
Reason for Change : {reason}

ECN Description:
\"\"\"{description}\"\"\"

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
}}

Consistency requirements:
- Return an empty `flags` array only when `overall_risk` is LOW and
  `description_quality` is CLEAR.
- For MEDIUM/HIGH risk, VAGUE/CONTRADICTING quality, or either condition,
  include at least one flag with a specific, evidence-based detail.
- Do not use a high-risk rating unless the returned flags support it."""
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
    """Resolve provider config, preferring OpenAI when both providers are set."""
    openai_key = _get_config_value("OPENAI_API_KEY")
    if openai_key:
        return {
            "provider": "openai",
            "api_key": openai_key,
            "base_url": _get_config_value(
                "OPENAI_BASE_URL", "https://gateway.aitools.corp.fisherpaykel.com"
            ),
            "model": _get_config_value("OPENAI_MODEL", "gpt-4o-mini"),
        }

    gemini_key = _get_config_value("GEMINI_API_KEY")
    if gemini_key:
        return {
            "provider": "gemini",
            "api_key": gemini_key,
            "base_url": _get_config_value(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            "model": _get_config_value("GEMINI_MODEL", "gemini-2.5-flash"),
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
    #  NEW: strip incomplete last line (truncated string) then re-close
    lines = cleaned.splitlines()
    while lines:
        try:
            candidate = "\n".join(lines)
            # Remove trailing comma/incomplete field and close the object
            candidate = re.sub(r',\s*"[^"]*"?\s*:\s*"[^"]*$', "", candidate)
            candidate = re.sub(r',\s*$', "", candidate)
            if not candidate.endswith("}"):
                candidate += "}"
            return json.loads(candidate)
        except json.JSONDecodeError:
            lines.pop()  # drop last line and retry

    raise json.JSONDecodeError("Could not repair truncated JSON", raw, 0)

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


def _normalise_ai_result(result: dict) -> dict:
    """Return a display-safe AI result and expose unsupported AI conclusions.

    Providers occasionally return a non-clear risk or quality label without the
    detailed flags requested by the prompt. Rather than presenting that as
    "No AI flags", add an explicit advisory explaining that the model did not
    supply evidence for its conclusion.
    """
    if not isinstance(result, dict):
        raise ValueError("AI response must be a JSON object")

    risk = str(result.get("overall_risk", "UNKNOWN")).upper().strip()
    if risk not in VALID_RISK_LEVELS:
        risk = "UNKNOWN"

    quality = str(result.get("description_quality", "UNKNOWN")).upper().strip()
    if quality not in VALID_DESCRIPTION_QUALITIES:
        quality = "UNKNOWN"

    raw_flags = result.get("flags", [])
    flags = [flag for flag in raw_flags if isinstance(flag, dict)] if isinstance(raw_flags, list) else []
    response_complete = isinstance(raw_flags, list) and len(flags) == len(raw_flags)
    recommendation = str(result.get("recommendation") or "").strip()
    needs_evidence = risk in {"MEDIUM", "HIGH"} or quality in {"VAGUE", "CONTRADICTING"}

    if not response_complete or (needs_evidence and not flags):
        detail = (
            "The AI returned a non-clear assessment without any supporting flags. "
            "Review the ECN manually; the assessment alone is not evidence of a specific issue."
            if response_complete
            else "The AI returned flags in an invalid format. Review the ECN manually."
        )
        flags.append(_rule_flag("AI_RESPONSE_INCOMPLETE", "REVIEW_REQUIRED", detail))
        response_complete = False
        if not recommendation:
            recommendation = "AI response needs manual review because supporting details were incomplete."

    return {
        "overall_risk": risk,
        "description_quality": quality,
        "flags": flags,
        "recommendation": recommendation,
        "response_status": "COMPLETE" if response_complete else "INCOMPLETE",
    }


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
        max_tokens=1500,
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
    description = (
        packet["header"].get("description")
        or packet["header"].get("description_of_change", "")
    )
    affected_products = _split_csv_values(
        packet.get("header", {}).get("products_affected")
        or packet.get("header", {}).get("affected_parts", "")
    )
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
        "response_status": "COMPLETE",
    }




# ── Public entry point ────────────────────────────────────────────────────────
def run_ai_advisory(packet: dict) -> dict:
    config = _resolve_llm_config()
    ai_result = None

    if HAS_OPENAI and config:
        try:
            prompt = _build_prompt(packet)
            ai_result = _normalise_ai_result(_call_openai(prompt, config))
            ai_result["ai_available"] = True
            logger.info(
                "AI Advisory complete — risk: %s; response: %s",
                ai_result.get("overall_risk"),
                ai_result.get("response_status"),
            )
        except Exception as exc:
            logger.warning("AI Advisory failed (%s) — falling back to rule-based.", exc)
            ai_result = None
    else:
        logger.warning("No API key or openai package — falling back to rule-based.")

    if ai_result is None:
        ai_result = _rule_based_advisory(packet)
        logger.info("AI Advisory: using rule-based fallback.")
        logger.info("ai_flags stored: %s", ai_result)
    packet["validation"]["ai_flags"] = ai_result
    return packet