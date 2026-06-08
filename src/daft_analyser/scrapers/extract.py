"""Pure HTML/JSON extraction helpers shared by the sale and rent scrapers.

These functions have no browser or network dependencies, so they can be unit
tested offline against saved HTML/JSON fixtures.
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup


def normalize_key(k: str) -> str:
    """Lowercase a JSON key and strip everything but alphanumerics."""
    return re.sub(r"[^a-z0-9]", "", k.lower())


def safe_str(v: Any) -> str | None:
    """Coerce a value to a non-empty stripped string, or None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def safe_int(v: Any) -> int | None:
    """Coerce a value to an int, or None."""
    if v is None:
        return None
    if isinstance(v, int):
        return v
    try:
        return int(str(v).strip())
    except (ValueError, TypeError):
        return None


def format_price_value(v: Any) -> str | None:
    """Format a numeric price as '€135,000'; pass through non-empty strings."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return f"€{v:,.0f}"
    s = str(v).strip()
    if not s:
        return None
    return s


def find_value_by_key(obj: Any, key_hints: list[str]) -> Any:
    """Depth-first search a nested dict/list for the first scalar value whose
    (normalised) key matches one of ``key_hints``."""
    hints = {normalize_key(k) for k in key_hints}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            for k, v in node.items():
                nk = normalize_key(str(k))
                if nk in hints:
                    if isinstance(v, (str, int, float)):
                        return v
                found = walk(v)
                if found is not None:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found is not None:
                    return found
        return None

    return walk(obj)


def extract_json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """Parse all <script type="application/ld+json"> blocks into dicts."""
    out: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        text = (script.string or script.get_text() or "").strip()
        if not text:
            continue
        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
        elif isinstance(obj, list):
            out.extend([x for x in obj if isinstance(x, dict)])
    return out


def extract_next_data(soup: BeautifulSoup) -> dict[str, Any]:
    """Parse the Next.js __NEXT_DATA__ payload into a dict (empty if absent)."""
    script = soup.find("script", id="__NEXT_DATA__")
    if not script:
        return {}
    text = (script.string or script.get_text() or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def extract_address_from_ld(obj: dict[str, Any]) -> str | None:
    """Build a single-line address from a JSON-LD object's 'address' field."""
    address = obj.get("address")
    if isinstance(address, str):
        return address.strip() or None
    if isinstance(address, dict):
        parts = [
            address.get("streetAddress"),
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("postalCode"),
            address.get("addressCountry"),
        ]
        cleaned = [str(p).strip() for p in parts if p]
        if cleaned:
            return ", ".join(cleaned)
    return None
