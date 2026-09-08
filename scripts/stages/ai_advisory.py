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

from rule_catalogue import rules_for_engine






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

VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
VALID_DESCRIPTION_QUALITIES = {"CLEAR", "VAGUE", "CONTRADICTING"}


# ── Prompt builder ───────────────────────────────────────────────────────────
def _semantic_rules() -> list[dict]:
    """Return the active S rules used by the AI Advisory stage."""
    return [rule for rule in rules_for_engine("ai_advisory") if rule["id"].startswith("S")]


def _rule_instructions() -> str:
    lines = []
    for rule in _semantic_rules():
        fields = ", ".join(rule.get("fields", [rule.get("field", "")]))
        lines.append(
            f'- {rule["id"]} ({rule["check"]}): {rule["message"]} '
            f"Fields: {fields}."
        )
    return "\n".join(lines)


def _build_prompt(packet: dict) -> str:
    header = packet.get("header", {})
    bom = packet.get("bom", [])
    truncated = len(bom) > BOM_CAP

    # Map PDF-parsed keys to prompt-friendly values
    change_notice_number = header.get("change_notice_number", "N/A")
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

Change Notice Number : {change_notice_number}
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

Validate these active semantic rules from the policy catalogue:
{_rule_instructions()}
Use only these canonical rule IDs in flags. Do not invent or use legacy A rule IDs.

Return only a single compact JSON object. No markdown fences, no prose, no comments.
Use this exact structure:
{{
  "overall_risk": "LOW | MEDIUM | HIGH",
    "description_quality": "CLEAR | VAGUE | CONTRADICTING",
  "flags": [
    {{
      "rule_id": "S01 | S02 | S03 | S04 | S05",
      "type": "VAGUE_TEXT | CONTRADICTION | MISSING_CONTEXT | RISK",
      "detail": "specific explanation",
      "line_number": null,
      "evidence": "relevant description excerpt or BOM facts"
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


def _rule_flag(
    rule_id: str,
    flag_type: str,
    detail: str,
    line_number=None,
    evidence=None,
    evaluation_status: str = "FAIL",
) -> dict:
    rule = next((item for item in _semantic_rules() if item["id"] == rule_id), None)
    flag = {
        "rule_id": rule_id,
        "type": flag_type,
        "detail": detail,
                "line_number": line_number,
        "evaluation_status": evaluation_status,
        "review_required": evaluation_status != "PASS",
        "evidence": evidence if evidence is not None else detail,
    }

    if rule:
        flag.update({
            "severity": rule["severity"],
            "gate_effect": rule["gate_effect"],
            "message": rule["message"],
        })
    return flag


# ── AI call ──────────────────────────────────────────────────────────────────
def _provider_config(provider: str) -> dict | None:
    if provider == "openai":
        api_key = _get_config_value("OPENAI_API_KEY")
        if not api_key:
            return None
        return {
            "provider": "openai",
            "api_key": api_key,
            "base_url": _get_config_value(
                "OPENAI_BASE_URL", "https://gateway.aitools.corp.fisherpaykel.com"
            ),
            "model": _get_config_value("OPENAI_MODEL", "gpt-4o-mini"),
        }

    if provider == "gemini":
        api_key = _get_config_value("GEMINI_API_KEY")
        if not api_key:
            return None
        return {
            "provider": "gemini",
            "api_key": api_key,
            "base_url": _get_config_value(
                "GEMINI_BASE_URL",
                "https://generativelanguage.googleapis.com/v1beta/openai/",
            ),
            "model": _get_config_value("GEMINI_MODEL", "gemini-2.5-flash"),
        }

    raise ValueError(f"Unsupported LLM provider: {provider}")


def _resolve_llm_config() -> dict | None:
    """Resolve OpenAI first, while allowing Gemini to be used as failover."""
    return _provider_config("openai") or _provider_config("gemini")


def _llm_attempts(config: dict | None) -> list[dict]:
    """Return the selected provider followed by Gemini failover when available."""
    if not config:
        return []
    attempts = [config]
    if config.get("provider") == "openai":
        gemini_config = _provider_config("gemini")
        if gemini_config:
            attempts.append(gemini_config)
    return attempts




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
    """Normalise model flags and require canonical catalogue rule IDs."""
    if not isinstance(result, dict):
        raise ValueError("AI response must be a JSON object")

    risk = str(result.get("overall_risk", "UNKNOWN")).upper().strip()
    if risk not in VALID_RISK_LEVELS:
        risk = "UNKNOWN"
    quality = str(result.get("description_quality", "UNKNOWN")).upper().strip()
    if quality not in VALID_DESCRIPTION_QUALITIES:
        quality = "UNKNOWN"

    raw_flags = result.get("flags", [])
    source_flags = [flag for flag in raw_flags if isinstance(flag, dict)] if isinstance(raw_flags, list) else []
    valid_rule_ids = {rule["id"] for rule in _semantic_rules()}
    flags = []
    valid_flags = True
    for flag in source_flags:
        rule_id = flag.get("rule_id")
        if rule_id not in valid_rule_ids:
            valid_flags = False
            flags.append(_rule_flag(
                "AI_RESPONSE_INCOMPLETE", "REVIEW_REQUIRED",
                "AI returned a flag without a valid catalogue S rule ID.", evidence=flag,
            ))
            continue
        flags.append(_rule_flag(
            rule_id, str(flag.get("type", "RISK")), str(flag.get("detail", "")),
            flag.get("line_number"), flag.get("evidence"),
        ))

    response_complete = isinstance(raw_flags, list) and len(source_flags) == len(raw_flags) and valid_flags
    recommendation = str(result.get("recommendation") or "").strip()
    needs_evidence = risk in {"MEDIUM", "HIGH"} or quality in {"VAGUE", "CONTRADICTING"}
    if not response_complete or (needs_evidence and not flags):
        detail = (
            "The AI returned a non-clear assessment without any supporting flags. "
            "Review the ECN manually; the assessment alone is not evidence of a specific issue."
            if response_complete else "The AI returned flags in an invalid format. Review the ECN manually."
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
        # The configured reasoning model only accepts temperature=1.
        # Keep this compatible with both the corporate LiteLLM gateway and
        # standard OpenAI-compatible providers.
        temperature=1,
        max_tokens=1500,


    )
    raw = response.choices[0].message.content.strip()
    return _try_parse_json(raw)


# ── Fallback (AI unavailable) ─────────────────────────────────────────────────
def _rule_based_advisory(packet: dict) -> dict:
    """Evaluate the catalogue's semantic-heuristic S rules without an LLM."""
    flags = []
    description = (
        packet["header"].get("description")
        or packet["header"].get("description_of_change", "")
    )
    description_actions = _extract_actions(description)
    bom_actions = _extract_bom_actions(packet)

    for rule_id in ("S01", "S05"):
        flags.append(_rule_flag(
            rule_id, "NOT_EVALUATED",
            "This catalogue rule requires the LLM advisory and was not evaluated because AI is unavailable.",
            evaluation_status="NOT_EVALUATED",
        ))

    bom_parts = {
        str(row.get("part_number", "")).strip()
        for row in packet.get("bom", [])
        if str(row.get("part_number", "")).strip()
    }
    description_parts = set(PART_NUMBER_PATTERN.findall(description))
    extra_description_parts = sorted(description_parts - bom_parts)
    if extra_description_parts:
        flags.append(_rule_flag(
            "S02", "MISSING_CONTEXT",
            f"Description mentions parts not found in BOM rows: {extra_description_parts[:5]}"
        ))

    if description_actions and bom_actions and description_actions.isdisjoint(bom_actions):
        flags.append(_rule_flag(
            "S03", "CONTRADICTION",
            f"Description actions {sorted(description_actions)} do not align with BOM actions {sorted(bom_actions)}."
        ))

    affected_products = _split_csv_values(
        packet.get("header", {}).get("products_affected")
        or packet.get("header", {}).get("affected_parts", "")
    )
    bom_parents = {
        str(
            row.get("parent_part_no") or row.get("parent") or row.get("parent_part")
            or row.get("assembly") or row.get("module") or row.get("parent_part_module") or ""
        ).strip()
        for row in packet.get("bom", [])
    }
    bom_parents = {value for value in bom_parents if value}
    if affected_products and bom_parents and affected_products.isdisjoint(bom_parents):
        flags.append(_rule_flag(
            "S04", "CONTRADICTION",
            f"Products affected {sorted(affected_products)} do not align with BOM parent assemblies {sorted(bom_parents)}."
        ))

    evaluated_flags = [flag for flag in flags if flag["evaluation_status"] == "FAIL"]
    risk = "HIGH" if len(evaluated_flags) >= 3 else "MEDIUM" if evaluated_flags else "LOW"
    if any(flag["type"] == "CONTRADICTION" for flag in evaluated_flags):
        quality = "CONTRADICTING"
    elif evaluated_flags:
        quality = "VAGUE"
    else:
        quality = "CLEAR"

    return {
        "overall_risk": risk,
        "description_quality": quality,
        "flags": flags,
        "recommendation": (
            "AI unavailable — catalogue semantic heuristics used. "
            f"{len(evaluated_flags)} potential issue(s) flagged; S01 and S05 require manual review."
        ),
        "ai_available": False,
        "response_status": "COMPLETE",
    }


# ── Public entry point ────────────────────────────────────────────────────────
def run_ai_advisory(packet: dict) -> dict:
    configured_rules = rules_for_engine("ai_advisory")
    logger.info("AI Advisory catalogue mapping: %d semantic rule(s).", len(configured_rules))

    
    config = _resolve_llm_config()


    if config and "provider" not in config:
        config = {**config, "provider": "openai"}
    ai_result = None


    if HAS_OPENAI and config:
        prompt = _build_prompt(packet)
        attempts = _llm_attempts(config)
        for attempt_number, provider_config in enumerate(attempts):
            try:
                ai_result = _normalise_ai_result(_call_openai(prompt, provider_config))
                ai_result["ai_available"] = True
                ai_result["provider"] = provider_config["provider"]
                logger.info(
                    "AI Advisory complete with %s — risk: %s; response: %s",
                    provider_config["provider"],
                    ai_result.get("overall_risk"),
                    ai_result.get("response_status"),
                )
                break
            except Exception as exc:
                next_provider = (
                    attempts[attempt_number + 1]["provider"]
                    if attempt_number + 1 < len(attempts)
                    else "rule-based"
                )
                logger.warning(
                    "AI Advisory %s attempt failed (%s); trying %s.",
                    provider_config["provider"], exc, next_provider,
                )
                ai_result = None
    else:
        logger.warning("No API key or openai package — falling back to rule-based.")

    if ai_result is None:
        ai_result = _rule_based_advisory(packet)
        logger.info("AI Advisory: using rule-based fallback.")
        logger.info("ai_flags stored: %s", ai_result)
    packet["validation"]["ai_flags"] = ai_result
    return packet