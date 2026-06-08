"""Scoring components, phase logic, flags, and the score_listings orchestrator."""

from __future__ import annotations

from datetime import date
from typing import List

from .finance import (
    DEFAULT_GREEN_RATE,
    compute_nvs,
    compute_tmc,
    is_green_mortgage_eligible,
)
from .models import SaleListing, ScoredListing

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Location tier keywords (address substring matching)
LOCATION_TIERS = {
    1: ["cork city centre", "city centre", "grand parade", "patrick street",
        "oliver plunkett", "south mall", "north main street", "south main street",
        "washington street", "western road", "mardyke"],
    2: ["douglas", "ballincollig", "carrigaline", "blackrock", "rochestown",
        "wilton", "togher", "bishopstown", "turner's cross", "ballyphehane",
        "montenotte", "sunday's well", "blackpool", "glanmire", "midleton"],
    3: ["cobh", "passage west", "crosshaven", "kinsale", "fermoy",
        "mallow", "youghal", "macroom", "dunmanway", "clonakilty"],
    4: ["bandon", "skibbereen", "bantry", "kanturk", "millstreet",
        "charleville", "mitchelstown", "lismore"],
}
TIER_SCORES = {1: 20, 2: 15, 3: 10, 4: 5}

# Phase dates (2026)
PHASE_SALE_FOCUS_END = date(2026, 5, 1)
PHASE_DUAL_TRACK_END = date(2026, 6, 1)


# ---------------------------------------------------------------------------
# Scoring components
# ---------------------------------------------------------------------------

def score_freshness(days_on_market: int) -> float:
    """0-40 points. ≤2 days=40, linear decay to 0 at 60+ days."""
    if days_on_market <= 2:
        return 40.0
    if days_on_market >= 60:
        return 0.0
    return round(40.0 * (1.0 - (days_on_market - 2) / 58.0), 1)


def score_staleness(days_on_market: int, view_count: int) -> float:
    """0-20 points. Motivated seller proxy: high views + long DOM = negotiable.

    Logic: normalise DOM (0-90 days → 0-1) and views (0-30000 → 0-1),
    average them, scale to 20.
    """
    dom_norm = min(days_on_market / 90.0, 1.0)
    views_norm = min(view_count / 30000.0, 1.0)
    return round(20.0 * (dom_norm * 0.5 + views_norm * 0.5), 1)


def score_mortgage_vs_rent(tmc: float, avg_rent: float) -> float:
    """0-20 points. TMC/rent ratio: ≤0.6→20, linear to 0 at 1.5."""
    if avg_rent <= 0:
        return 0.0
    ratio = tmc / avg_rent
    if ratio <= 0.6:
        return 20.0
    if ratio >= 1.5:
        return 0.0
    return round(20.0 * (1.0 - (ratio - 0.6) / 0.9), 1)


def score_location(address: str) -> float:
    """0-20 points based on address keyword matching to location tiers."""
    addr_lower = address.lower()
    for tier, keywords in LOCATION_TIERS.items():
        for kw in keywords:
            if kw in addr_lower:
                return float(TIER_SCORES[tier])
    return float(TIER_SCORES[4])  # default to lowest tier


# ---------------------------------------------------------------------------
# Phase logic
# ---------------------------------------------------------------------------

def get_phase(today: date) -> str:
    if today < PHASE_SALE_FOCUS_END:
        return "SALE_FOCUS"
    elif today < PHASE_DUAL_TRACK_END:
        return "DUAL_TRACK"
    else:
        return "RENTAL_FOCUS"


def apply_phase_penalty(score: float, phase: str) -> float:
    if phase == "RENTAL_FOCUS":
        return round(score * 0.7, 1)
    return score


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def generate_flags(listing: SaleListing, phase: str) -> List[str]:
    flags = []

    # Stale + high views = motivated seller
    if listing.days_on_market >= 10 and listing.view_count >= 5000:
        flags.append("STALE_HIGH_VIEWS")

    # Suspicious price_per_sqm
    if listing.price_per_sqm > 0 and listing.price_per_sqm < 500:
        flags.append("DATA_QUALITY_WARNING")

    # Agent address instead of property address
    if "south main street" in listing.address.lower() and "bandon" in listing.url:
        flags.append("AGENT_ADDRESS")

    # Missing BER
    if not listing.ber_rating:
        flags.append("NO_BER")

    # Phase warnings
    if phase == "DUAL_TRACK":
        flags.append("CONSIDER_RENTAL_BACKUP")
    elif phase == "RENTAL_FOCUS":
        flags.append("PRIORITISE_RENTALS")

    return flags


# ---------------------------------------------------------------------------
# Priority label
# ---------------------------------------------------------------------------

def priority_label(nvs: float) -> str:
    if nvs <= 0:
        return "NO_DATA"
    if nvs < 3800:
        return "CRITICAL"
    if nvs <= 4600:
        return "STANDARD"
    return "LOW"


# ---------------------------------------------------------------------------
# Main scoring
# ---------------------------------------------------------------------------

def score_listings(listings: List[SaleListing], avg_rent: float,
                   loan_amount: float, rate: float, term: int,
                   service_charge_mo: float,
                   today: date) -> List[ScoredListing]:
    phase = get_phase(today)
    scored = []

    for lst in listings:
        green = is_green_mortgage_eligible(lst.ber_rating)
        effective_rate = DEFAULT_GREEN_RATE if green else rate

        tmc = compute_tmc(lst.ber_rating, loan_amount,
                          effective_rate, term, service_charge_mo)
        nvs = compute_nvs(lst.price, lst.sqm, lst.ber_rating)

        fresh = score_freshness(lst.days_on_market)
        stale = score_staleness(lst.days_on_market, lst.view_count)
        mvr = score_mortgage_vs_rent(tmc, avg_rent)
        loc = score_location(lst.address)

        raw_total = fresh + stale + mvr + loc
        total = apply_phase_penalty(raw_total, phase)

        flags = generate_flags(lst, phase)
        label = priority_label(nvs)

        scored.append(ScoredListing(
            listing=lst,
            freshness_score=fresh,
            staleness_score=stale,
            mortgage_vs_rent_score=mvr,
            location_tier_score=loc,
            total_score=total,
            tmc_estimate=tmc,
            nvs=nvs,
            green_mortgage=green,
            priority_label=label,
            flags=flags,
        ))

    scored.sort(key=lambda s: s.total_score, reverse=True)
    return scored
