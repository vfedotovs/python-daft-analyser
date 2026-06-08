#!/usr/bin/env python3
"""Daft.ie Sale Listing Scoring Report.

Ranks sale listings 0-100 by purchase priority for a September 1st move-in
deadline. Applies BER-adjusted pricing, true monthly cost estimates, and
time-degradation phases.

Usage:
    python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv
    python3 scoring_report.py --sale-csv <file>.csv --rent-json <file>.json --top 5 --output report.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
from datetime import date, datetime
from typing import List, Optional

from .finance import (
    DEFAULT_AVG_RENT,
    DEFAULT_LOAN_AMOUNT,
    DEFAULT_MORTGAGE_RATE,
    DEFAULT_SERVICE_CHARGE_MO,
    DEFAULT_TERM_YEARS,
)
from .models import RentComparable, SaleListing, ScoredListing
from .scoring import get_phase, score_listings

logger = logging.getLogger(__name__)


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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

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
