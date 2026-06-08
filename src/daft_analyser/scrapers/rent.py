#!/usr/bin/env python3
"""Scrape Daft.ie rent listings from a search URL.

Extracts:
- listing URL
- address
- rent price
- property type
- BER rating
- double bedrooms
- bathrooms
- available from
- furnished
- lease
- date listed
- view count
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from bs4 import BeautifulSoup

from . import extract
from .base import BaseDaftScraper, scrape_search
from ..io.writers import default_output_path, write_json
from ..logging_config import setup_logging

LISTING_URL_RE = re.compile(r"^https?://www\.daft\.ie/for-rent/[\w\-.,%/]+/?$", re.IGNORECASE)


@dataclass
class RentListingRecord:
    url: str
    address: str | None = None
    rent_price: str | None = None
    property_type: str | None = None
    ber_rating: str | None = None
    double_bedroom: int | None = None
    bathroom: int | None = None
    available_from: str | None = None
    furnished: str | None = None
    lease: str | None = None
    date_listed: str | None = None
    views: str | None = None


def _format_rent_price(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return f"€{v:,.0f} per month"
    s = str(v).strip()
    if not s:
        return None
    return s


class DaftRentScraper(BaseDaftScraper[RentListingRecord]):
    LOGGER_NAME = "daft_rent_scraper"
    CHROME_VERSION = "122.0.0.0"
    CHROMIUM_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]
    NAV_WAIT_UNTIL = "domcontentloaded"
    DISMISS_COOKIES = False
    SIMULATE_HUMAN = False
    LISTING_HREF_SELECTOR = "a[href*='/for-rent/']"
    LISTING_URL_RE = LISTING_URL_RE
    LISTING_URL_TEXT_RE = r"https://www\.daft\.ie/for-rent/[\w\-.,%/]+"

    # --- Extraction hooks --------------------------------------------------

    def _new_record(self, url: str) -> RentListingRecord:
        return RentListingRecord(url=url)

    def _fill_from_json_ld(self, record: RentListingRecord, objs: list[dict[str, Any]]) -> None:
        for obj in objs:
            if not record.address:
                address = extract.extract_address_from_ld(obj)
                if address:
                    record.address = address

            if not record.rent_price:
                price = extract.find_value_by_key(obj, ["price", "monthlyRent", "rentPrice"])
                if price is not None:
                    record.rent_price = _format_rent_price(price)

            if not record.date_listed:
                value = extract.find_value_by_key(obj, ["datePosted", "datePublished", "dateCreated"])
                if value is not None:
                    record.date_listed = str(value)

    def _fill_from_dict_guessing(self, record: RentListingRecord, data: dict[str, Any]) -> None:
        if not data:
            return

        if not record.address:
            # Prefer displayAddress (the property address) over generic "address"
            # which may match the agent's office address.
            record.address = extract.safe_str(
                extract.find_value_by_key(data, ["displayAddress"])
            ) or extract.safe_str(
                extract.find_value_by_key(data, ["seoAddress", "formattedAddress"])
            )

        if not record.rent_price:
            price = extract.find_value_by_key(
                data, ["price", "monthlyRent", "rentPrice", "rent", "monthlyPrice"]
            )
            if price is not None:
                record.rent_price = _format_rent_price(price)

        if not record.property_type:
            record.property_type = extract.safe_str(
                extract.find_value_by_key(
                    data, ["propertyType", "category", "propertyCategory"]
                )
            )

        if not record.ber_rating:
            ber = extract.find_value_by_key(data, ["ber", "berRating", "energyRating", "energyLabel"])
            if ber is not None:
                record.ber_rating = extract.safe_str(ber)

        if record.double_bedroom is None:
            beds = extract.find_value_by_key(
                data, ["numBedrooms", "bedrooms", "numBeds", "bedroomCount", "doubleBedroom"]
            )
            if beds is not None:
                record.double_bedroom = extract.safe_int(beds)

        if record.bathroom is None:
            baths = extract.find_value_by_key(
                data, ["numBathrooms", "bathrooms", "bathroomCount", "numBaths"]
            )
            if baths is not None:
                record.bathroom = extract.safe_int(baths)

        if not record.available_from:
            record.available_from = extract.safe_str(
                extract.find_value_by_key(
                    data, ["availableFrom", "availableDate", "moveInDate", "availabilityDate"]
                )
            )

        if not record.furnished:
            record.furnished = extract.safe_str(
                extract.find_value_by_key(
                    data, ["furnished", "furnishing", "furnishType", "isFurnished"]
                )
            )

        if not record.lease:
            record.lease = extract.safe_str(
                extract.find_value_by_key(
                    data, ["leaseTerm", "lease", "leaseLength", "minimumLease", "leaseDuration"]
                )
            )

        if not record.date_listed:
            record.date_listed = extract.safe_str(
                extract.find_value_by_key(
                    data, ["dateListed", "listedDate", "datePublished", "publishDate", "datePosted"]
                )
            )

        if not record.views:
            views = extract.find_value_by_key(
                data, ["views", "viewCount", "pageViews", "numViews", "totalViews"]
            )
            if views is not None:
                record.views = extract.safe_str(views)

    def _fill_from_text_fallback(self, record: RentListingRecord, soup: BeautifulSoup, html: str) -> None:
        page_text = soup.get_text(" ", strip=True)

        # Address
        if not record.address:
            h1 = soup.find("h1")
            if h1:
                record.address = extract.safe_str(h1.get_text(" ", strip=True))

        if not record.address:
            for prop in ("og:title", "twitter:title"):
                meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
                if meta and meta.get("content"):
                    record.address = extract.safe_str(meta["content"])
                    break

        # Rent price
        if not record.rent_price:
            m = re.search(r"€\s?[\d,.]+\s*(?:per\s*month|p\.?m\.?|/\s*month|pcm)?", page_text, re.IGNORECASE)
            if m:
                record.rent_price = m.group(0).strip()

        # Property type (e.g. "2 Bed 1 Bath Apartment")
        if not record.property_type:
            m = re.search(r"(\d+\s*Bed(?:room)?s?\s+\d+\s*Bath(?:room)?s?\s+\w+)", page_text, re.IGNORECASE)
            if m:
                record.property_type = m.group(1).strip()

        # BER rating
        if not record.ber_rating:
            m = re.search(
                r"\bBER\b\s*[:\-]?\s*(A[1-3]|B[1-3]|C[1-3]|D[1-2]?|E[1-2]?|F|G|Exempt)",
                page_text, re.IGNORECASE,
            )
            if m:
                record.ber_rating = m.group(1).upper()
            else:
                m2 = re.search(r'"ber(?:Rating)?"\s*:\s*"([A-G][1-3]?|Exempt)"', html, re.IGNORECASE)
                if m2:
                    record.ber_rating = m2.group(1).upper()

        # Bedrooms
        if record.double_bedroom is None:
            m = re.search(r"(\d+)\s*(?:Double\s*)?Bed(?:room)?s?", page_text, re.IGNORECASE)
            if m:
                record.double_bedroom = int(m.group(1))

        # Bathrooms
        if record.bathroom is None:
            m = re.search(r"(\d+)\s*Bath(?:room)?s?", page_text, re.IGNORECASE)
            if m:
                record.bathroom = int(m.group(1))

        # Available from
        if not record.available_from:
            m = re.search(
                r"(?:Available\s*(?:from)?)\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?,?\s*\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|Immediately)",
                page_text, re.IGNORECASE,
            )
            if m:
                record.available_from = m.group(1).strip()

        # Furnished
        if not record.furnished:
            m = re.search(r"(?:Furnished)\s*[:\-]?\s*(Yes|No|Furnished|Unfurnished|Part(?:ly|\s*Furnished))", page_text, re.IGNORECASE)
            if m:
                record.furnished = m.group(1).strip()
            elif re.search(r"\bFurnished\b", page_text, re.IGNORECASE):
                record.furnished = "Yes"
            elif re.search(r"\bUnfurnished\b", page_text, re.IGNORECASE):
                record.furnished = "No"

        # Lease
        if not record.lease:
            m = re.search(
                r"(?:Lease|Minimum\s*Lease)\s*[:\-]?\s*(Minimum\s*\d+\s*(?:Year|Month)s?|\d+\s*(?:Year|Month)s?\s*(?:Minimum)?|Flexible)",
                page_text, re.IGNORECASE,
            )
            if m:
                record.lease = m.group(1).strip()

        # Date listed
        if not record.date_listed:
            m = re.search(
                r"(?:Date\s*(?:Entered|Listed)|Listed\s*on|Listing\s*date)\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                page_text, re.IGNORECASE,
            )
            if m:
                record.date_listed = m.group(1).strip()
            else:
                m2 = re.search(r'"(?:dateListed|datePosted|datePublished)"\s*:\s*"([^\"]+)"', html)
                if m2:
                    record.date_listed = m2.group(1).strip()

        # Views
        if not record.views:
            m = re.search(r"(?:Views?|View\s*count|Page\s*views?)\s*[:\-]?\s*([\d,]+\d)", page_text, re.IGNORECASE)
            if m:
                record.views = m.group(1)
            else:
                m2 = re.search(r'"(?:viewCount|views|numViews|totalViews)"\s*:\s*([\d,]+\d)', html, re.IGNORECASE)
                if m2:
                    record.views = m2.group(1)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape Daft.ie rent listing details from a search page URL")
    p.add_argument(
        "--search-url",
        default="https://www.daft.ie/property-for-rent/cork-city?sort=publishDateDesc",
        help="Daft search results URL",
    )
    p.add_argument("--output", default=None, help="Output JSON file path (default: timestamped)")
    p.add_argument("--max-listings", type=int, default=30, help="Max number of listings to scrape (0 = all)")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum delay between listing requests")
    p.add_argument("--delay-max", type=float, default=2.5, help="Maximum delay between listing requests")
    p.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    p.add_argument("--visible", action="store_true", help="Show browser window (disable headless mode)")
    return p.parse_args()


def main() -> int:
    logger = setup_logging("daft_rent_scraper")
    args = parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    if args.output is None:
        args.output = default_output_path(f"rent_cork_city_{timestamp}.json")

    if args.delay_max < args.delay_min:
        logger.error("--delay-max must be >= --delay-min")
        return 2

    with DaftRentScraper(timeout=args.timeout, headless=not args.visible) as scraper:
        try:
            records = scrape_search(
                scraper, args.search_url, args.max_listings, args.delay_min, args.delay_max
            )
        except Exception as exc:
            logger.error("Failed to load search page: %s", exc)
            return 1

        if not records:
            return 1

        write_json(args.output, records)

        logger.info("Saved %d records to %s", len(records), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
