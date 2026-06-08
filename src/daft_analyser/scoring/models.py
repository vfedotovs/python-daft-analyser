"""Data models for the sale-listing scoring report."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import List


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
