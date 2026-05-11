"""Profile loader + cheap pre-filter.

The full LLM-based qualifier runs in workers/agents/qualify.py; this module
is the cheap regex pass that obviously-rejects junk before we spend tokens.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

PROFILE_PATH = Path(__file__).parent.parent / "profile.yaml"

# Hard reject: titles that are never worth qualifying further. Cheap regex.
HARD_REJECT_TITLE_PATTERNS = [
    r"\b(jr\.?|junior|entry[- ]level|associate engineer)\b",
    r"\b(staff|principal|distinguished)\s+(software|engineer)",
    r"\b(ml|machine learning)\s+(researcher|research scientist)\b",
    r"\bpretraining\b",
    r"\bmlops\b.*\b(platform|infrastructure)\b",
    r"\b(data\s+scientist|quantitative\s+analyst)\b",
    r"\b(office\s+manager|executive\s+assistant|receptionist|secretary)\b",
    r"\b(security\s+clearance|government\s+clearance|TS/?SCI)\b",
]

# Hard reject: location keywords that indicate on-site somewhere we won't go.
ON_SITE_REJECT_PATTERNS = [
    r"\bon[- ]site\b.*\b(NYC|New York|San Francisco|SF|Seattle|Austin|Boston|Chicago|LA|Los Angeles|London|Berlin|Paris|Tokyo|Singapore|Bangalore|Dubai)\b",
    r"\bmust be in\b.*\b(NYC|New York|San Francisco|SF|Seattle|Austin|Boston|Chicago|LA|London|Berlin|Paris)\b",
    r"\bin[- ]office\b.*\b(\d+\s+days/week|required)\b",
]


@lru_cache(maxsize=1)
def load_profile() -> dict[str, Any]:
    """Load profile.yaml. Cached for the worker's lifetime."""
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def hard_reject(title: str, description: str | None, location: str | None) -> str | None:
    """Return a reject reason string if the listing is obvious junk, else None.

    This is the cheap pre-filter. Survivors go to the LLM qualifier.
    """
    text = " ".join(filter(None, [title, location, (description or "")[:1500]])).lower()
    if not title:
        return "no title"
    title_l = title.lower()

    for pat in HARD_REJECT_TITLE_PATTERNS:
        if re.search(pat, title_l, re.I):
            return f"title_pattern: {pat}"

    for pat in ON_SITE_REJECT_PATTERNS:
        if re.search(pat, text, re.I):
            return f"on_site_unwanted: {pat}"

    return None


def profile_for_prompt() -> str:
    """Render the profile as a compact text block for inclusion in LLM prompts."""
    p = load_profile()
    lines: list[str] = []
    lines.append(f"NAME: {p['identity']['name']} (brand: {p['identity']['brand']})")
    lines.append(f"BASED: {p['identity']['base']}")
    # Schema can be either legacy `languages: [...]` or new
    # `native_language` + `bonus_languages: [...]`. Support both.
    ident = p["identity"]
    if "languages" in ident:
        lines.append(f"LANGUAGES: {', '.join(ident['languages'])}")
    else:
        native = ident.get("native_language", "English")
        bonus = ident.get("bonus_languages") or []
        lines.append(f"NATIVE LANGUAGE: {native}")
        if bonus:
            lines.append(
                f"BONUS LANGUAGES (only invoke when company explicitly has matching geo/customer signal): "
                f"{', '.join(bonus)}"
            )
    lines.append(f"REMOTE OK: {p['geography']['remote_ok']}; ON-SITE OK IN: {', '.join(p['geography']['on_site_ok_in'])}")
    lines.append(
        f"COMP FLOORS: full-time ${p['comp']['full_time_min_usd_year']:,}/yr, "
        f"consulting ${p['comp']['consulting_day_rate_min_usd']}/day, "
        f"retainer ${p['comp']['retainer_floor_usd_month']:,}/mo"
    )
    lines.append("EDGES (use these in letters):")
    for e in p["edges"]:
        lines.append(f"  - {e}")
    lines.append("TIER 1 (apply directly):")
    for r in p["roles"]["tier_1_apply"]:
        lines.append(f"  - {r}")
    lines.append("TIER 2 (pitch consulting instead of hire):")
    for r in p["roles"]["tier_2_pitch_consulting"]:
        lines.append(f"  - {r}")
    lines.append("REJECT (auto-skip):")
    for r in p["roles"]["reject"]:
        lines.append(f"  - {r}")
    return "\n".join(lines)
