#!/usr/bin/env python3
"""Daft.ie Sale Listing Scoring Report.

Ranks sale listings 0-100 by purchase priority for a September 1st move-in
deadline. Applies BER-adjusted pricing, true monthly cost estimates, and
time-degradation phases.

Usage:
    python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv
    python3 scoring_report.py --sale-csv <file>.csv --rent-json <file>.json --top 5 --output report.json
"""

import argparse
import csv
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_AVG_RENT = 2197  # Cork avg rent €/mo
DEFAULT_LOAN_AMOUNT = 180_000
DEFAULT_MORTGAGE_RATE = 0.035
DEFAULT_GREEN_RATE = 0.030
DEFAULT_TERM_YEARS = 30
DEFAULT_SERVICE_CHARGE_MO = 50

# BER heating cost estimates (€/month)
BER_HEATING = {
    "A1": 30, "A2": 40, "A3": 50,
    "B1": 60, "B2": 70, "B3": 80,
    "C1": 100, "C2": 120, "C3": 140,
    "D1": 170, "D2": 200, "D": 185,
    "E1": 220, "E2": 250, "E": 235,
    "F": 280,
    "G": 340,
}
DEFAULT_HEATING = 185  # assume D-range if missing

# BER retrofit cost adjustments for NVS
BER_RETROFIT_COST = {
    "A1": -10_000, "A2": -10_000, "A3": -10_000,
    "B1": -10_000, "B2": -10_000, "B3": -10_000,
    "C1": 0, "C2": 0, "C3": 0,
    "D1": 15_000, "D2": 15_000, "D": 15_000,
    "E1": 20_000, "E2": 20_000, "E": 20_000,
    "F": 22_000,
    "G": 25_000,
}

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
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class SaleListing:
    url: str
    address: str
    price: float
    price_per_sqm: float
    sqm: float
    ber_rating: str
    date_listed: date
    view_count: int
    days_on_market: int


@dataclass
class ScoredListing:
    listing: SaleListing
    freshness_score: float
    staleness_score: float
    mortgage_vs_rent_score: float
    location_tier_score: float
    total_score: float
    tmc_estimate: float
    nvs: float
    green_mortgage: bool
    priority_label: str
    flags: List[str] = field(default_factory=list)


@dataclass
class RentComparable:
    address: str
    rent_price: float
    ber_rating: str


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_price(raw: str) -> float:
    """Extract numeric price from strings like '€135,000' or '€2,700'."""
    cleaned = re.sub(r"[€,\s]", "", raw.strip())
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_date(raw: str) -> date:
    """Parse YYYY-MM-DD date string."""
    return datetime.strptime(raw.strip(), "%Y-%m-%d").date()


def normalise_address(raw: str) -> str:
    """Collapse multiline addresses into a single line."""
    return re.sub(r"\s*\n\s*", ", ", raw.strip())


def load_sale_csv(filepath: str, today: date) -> List[SaleListing]:
    """Load sale listings from CSV, handling multiline quoted fields."""
    listings = []
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        try:
            price = parse_price(row.get("price", "0"))
            ppsm = parse_price(row.get("price_per_sq_meter", "0"))
            sqm = price / ppsm if ppsm > 0 else 0.0
            ber = row.get("ber_rating", "").strip()
            dl = parse_date(row.get("date_listed", "2026-01-01"))
            dom = (today - dl).days
            vc_raw = row.get("view_count", "0")
            vc = int(re.sub(r"[,\s]", "", vc_raw))

            address = normalise_address(row.get("address", ""))

            listings.append(SaleListing(
                url=row.get("url", "").strip(),
                address=address,
                price=price,
                price_per_sqm=ppsm,
                sqm=round(sqm, 1),
                ber_rating=ber,
                date_listed=dl,
                view_count=vc,
                days_on_market=max(dom, 0),
            ))
        except Exception as e:
            logger.warning("Skipping row: %s — %s", row.get("url", "?"), e)

    return listings


def load_rent_json(filepath: str) -> List[RentComparable]:
    """Load rent comparables from JSON."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    comps = []
    for item in data:
        rent_str = item.get("rent_price", "€0 per month")
        rent_val = parse_price(rent_str.replace("per month", ""))
        comps.append(RentComparable(
            address=item.get("address", ""),
            rent_price=rent_val,
            ber_rating=item.get("ber_rating", ""),
        ))
    return comps


def compute_avg_rent(comps: List[RentComparable]) -> float:
    """Compute average rent from comparables, ignoring zeros."""
    prices = [c.rent_price for c in comps if c.rent_price > 0]
    return sum(prices) / len(prices) if prices else DEFAULT_AVG_RENT


# ---------------------------------------------------------------------------
# Financial Calculations
# ---------------------------------------------------------------------------

def monthly_mortgage(principal: float, annual_rate: float, years: int) -> float:
    """Annuity formula for monthly mortgage repayment."""
    if annual_rate <= 0 or years <= 0:
        return principal / (years * 12) if years > 0 else 0.0
    r = annual_rate / 12
    n = years * 12
    return principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)


def compute_tmc(ber: str, loan_amount: float,
                rate: float, term: int, service_charge_mo: float) -> float:
    """True Monthly Cost = mortgage + service charge + heating."""
    mortgage = monthly_mortgage(loan_amount, rate, term)
    heating = BER_HEATING.get(ber, DEFAULT_HEATING)
    return round(mortgage + service_charge_mo + heating, 2)


def is_green_mortgage_eligible(ber: str) -> bool:
    """BER A1-B3 qualifies for green mortgage rate."""
    return ber in ("A1", "A2", "A3", "B1", "B2", "B3")


def compute_nvs(price: float, sqm: float, ber: str) -> float:
    """BER-Adjusted Normalised Value Score (€/m² after retrofit adjustment)."""
    retrofit = BER_RETROFIT_COST.get(ber, 15_000)
    adjusted = price + retrofit
    if sqm <= 0:
        return 0.0
    return round(adjusted / sqm, 2)


# ---------------------------------------------------------------------------
# Scoring Components
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
# Phase Logic
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
# Priority Label
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
# Main Scoring
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


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_report(scored: List[ScoredListing], avg_rent: float,
                 today: date, top_n: Optional[int],
                 min_score: Optional[float]) -> None:
    phase = get_phase(today)

    print(f"\n{'=' * 65}")
    print(f"  DAFT PROPERTY SCORING REPORT")
    print(f"{'=' * 65}")
    print(f"  Date: {today}  |  Phase: {phase}  |  Avg Cork Rent: €{avg_rent:,.0f}/mo")
    print(f"{'=' * 65}\n")

    # Data limitations
    print("  Known Data Limitations:")
    print("  - No description text → cannot filter 'tenant in situ', 'cash buyers only'")
    print("  - No service charge data → using €50/mo estimate")
    print("  - No price history → cannot detect price drops")
    print("  - Some listings show agent address instead of property address")
    print()

    display = scored
    if min_score is not None:
        display = [s for s in display if s.total_score >= min_score]
    if top_n is not None:
        display = display[:top_n]

    # Header
    print(f" {'#':>2}  {'Score':>5}  {'Priority':>8}  {'Price':>10}  {'SQM':>5}  "
          f"{'€/m²':>6}  {'NVS':>7}  {'BER':>3}  {'DOM':>3}  {'Views':>6}  "
          f"{'TMC/mo':>7}  Flags")
    print(f" {'—' * 2}  {'—' * 5}  {'—' * 8}  {'—' * 10}  {'—' * 5}  "
          f"{'—' * 6}  {'—' * 7}  {'—' * 3}  {'—' * 3}  {'—' * 6}  "
          f"{'—' * 7}  {'—' * 20}")

    for i, s in enumerate(display, 1):
        l = s.listing
        ber_display = l.ber_rating if l.ber_rating else "—"
        flag_str = ", ".join(s.flags) if s.flags else ""
        print(f" {i:>2}  {s.total_score:>5.1f}  {s.priority_label:>8}  "
              f"€{l.price:>9,.0f}  {l.sqm:>4.0f}m²  "
              f"€{l.price_per_sqm:>5,.0f}  €{s.nvs:>6,.0f}  "
              f"{ber_display:>3}  {l.days_on_market:>3}  {l.view_count:>6,}  "
              f"€{s.tmc_estimate:>6,.0f}  {flag_str}")

    print()

    # Breakdown for top listing
    if display:
        top = display[0]
        print(f"  --- Scoring Breakdown (#{1}: {top.listing.address[:50]}) ---")
        print(f"    Freshness:        {top.freshness_score:>5.1f}/40  |  "
              f"Staleness: {top.staleness_score:>5.1f}/20  |  "
              f"Mortgage vs Rent: {top.mortgage_vs_rent_score:>5.1f}/20  |  "
              f"Location: {top.location_tier_score:>5.1f}/20")
        if top.green_mortgage:
            print(f"    Green mortgage eligible (3.0% rate)")
        print()

    print(f"  Total listings scored: {len(scored)}")
    if min_score is not None:
        print(f"  Shown (min score {min_score}): {len(display)}")
    print()


def export_json(scored: List[ScoredListing], filepath: str,
                avg_rent: float, today: date) -> None:
    phase = get_phase(today)

    def listing_to_dict(s: ScoredListing) -> dict:
        l = s.listing
        return {
            "rank": None,  # filled below
            "total_score": s.total_score,
            "priority_label": s.priority_label,
            "url": l.url,
            "address": l.address,
            "price": l.price,
            "sqm": l.sqm,
            "price_per_sqm": l.price_per_sqm,
            "ber_rating": l.ber_rating,
            "date_listed": l.date_listed.isoformat(),
            "days_on_market": l.days_on_market,
            "view_count": l.view_count,
            "nvs": s.nvs,
            "tmc_estimate": s.tmc_estimate,
            "green_mortgage": s.green_mortgage,
            "scores": {
                "freshness": s.freshness_score,
                "staleness": s.staleness_score,
                "mortgage_vs_rent": s.mortgage_vs_rent_score,
                "location_tier": s.location_tier_score,
            },
            "flags": s.flags,
        }

    entries = []
    for i, s in enumerate(scored, 1):
        d = listing_to_dict(s)
        d["rank"] = i
        entries.append(d)

    output = {
        "report_date": today.isoformat(),
        "phase": phase,
        "avg_rent": avg_rent,
        "total_listings": len(scored),
        "listings": entries,
    }

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info("JSON report written to %s", filepath)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Score and rank Daft.ie sale listings by purchase priority."
    )
    parser.add_argument("--sale-csv", required=True, help="Path to sale listings CSV")
    parser.add_argument("--rent-json", help="Path to rent comparables JSON")
    parser.add_argument("--output", help="Path to write JSON report")
    parser.add_argument("--top", type=int, help="Show only top N listings")
    parser.add_argument("--min-score", type=float, help="Minimum score threshold")
    parser.add_argument("--avg-rent", type=float, help=f"Override avg rent (default: €{DEFAULT_AVG_RENT})")
    parser.add_argument("--loan-amount", type=float, default=DEFAULT_LOAN_AMOUNT,
                        help=f"Mortgage loan amount (default: €{DEFAULT_LOAN_AMOUNT:,})")
    parser.add_argument("--mortgage-rate", type=float, default=DEFAULT_MORTGAGE_RATE,
                        help=f"Annual mortgage rate (default: {DEFAULT_MORTGAGE_RATE})")

    args = parser.parse_args()
    today = date.today()

    # Load sale listings
    listings = load_sale_csv(args.sale_csv, today)
    logger.info("Loaded %d sale listings from %s", len(listings), args.sale_csv)

    # Load rent comparables and compute avg rent
    avg_rent = DEFAULT_AVG_RENT
    if args.rent_json:
        comps = load_rent_json(args.rent_json)
        avg_rent = compute_avg_rent(comps)
        logger.info("Computed avg rent: €%.0f/mo from %d comparables", avg_rent, len(comps))
    if args.avg_rent:
        avg_rent = args.avg_rent

    # Score
    scored = score_listings(
        listings, avg_rent,
        args.loan_amount, args.mortgage_rate, DEFAULT_TERM_YEARS,
        DEFAULT_SERVICE_CHARGE_MO, today
    )

    # Output
    print_report(scored, avg_rent, today, args.top, args.min_score)

    if args.output:
        export_json(scored, args.output, avg_rent, today)


if __name__ == "__main__":
    main()
