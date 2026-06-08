#!/usr/bin/env python3
"""Scrape Daft.ie sale listings from a search URL.

Extracts:
- listing URL
- address
- price
- price per sq meter
- BER rating
- date listed
- view count
"""

from __future__ import annotations

import argparse
import random
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import extract
from .base import BASE_URL, BaseDaftScraper, scrape_search
from ..io.writers import default_output_path, write_csv, write_json
from ..logging_config import setup_logging

LISTING_URL_RE = re.compile(r"^https?://www\.daft\.ie/for-sale/[\w\-.,%/]+/?$", re.IGNORECASE)

SALE_FIELDS = [
    "url",
    "address",
    "price",
    "price_per_sq_meter",
    "ber_rating",
    "date_listed",
    "view_count",
]


@dataclass
class ListingRecord:
    url: str
    address: str | None = None
    price: str | None = None
    price_per_sq_meter: str | None = None
    ber_rating: str | None = None
    date_listed: str | None = None
    view_count: str | None = None


class DaftScraper(BaseDaftScraper[ListingRecord]):
    LOGGER_NAME = "daft_sale_scraper"
    CHROME_VERSION = "133.0.0.0"
    CHROMIUM_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]
    NAV_WAIT_UNTIL = "networkidle"
    DISMISS_COOKIES = True
    SIMULATE_HUMAN = True
    LISTING_HREF_SELECTOR = "a[href*='/for-sale/']"
    LISTING_URL_RE = LISTING_URL_RE
    LISTING_URL_TEXT_RE = r"https://www\.daft\.ie/for-sale/[\w\-.,%/]+"

    def _viewport(self) -> dict[str, int]:
        return {"width": random.randint(1280, 1440), "height": random.randint(800, 900)}

    def get_listing_urls_from_search(self, search_url: str) -> list[str]:
        self.logger.info("Loading search results page: %s", search_url)
        self._ensure_browser()
        assert self._context is not None
        page = self._context.new_page()
        try:
            try:
                page.goto(search_url, timeout=self.timeout * 1000, wait_until="networkidle")
            except Exception as e:
                self.logger.debug("Navigation timed out: %s", e)

            # Take debug screenshot
            screenshot_path = default_output_path("debug_view.png")
            page.screenshot(path=screenshot_path)
            self.logger.debug("Debug screenshot saved as %s", screenshot_path)

            self._dismiss_cookies(page)
            self._human_behavior(page)

            # Primary: use Playwright locators to find listing links (works even with JS-rendered content)
            urls: set[str] = set()
            links = page.locator('a[href*="/for-sale/"]')
            count = links.count()
            self.logger.debug("Found %d raw links via Playwright locator", count)

            for i in range(count):
                href = links.nth(i).get_attribute("href")
                if href:
                    full = urljoin(BASE_URL, href)
                    if LISTING_URL_RE.match(full):
                        urls.add(full.rstrip("/"))

            # Fallback: parse full HTML with BeautifulSoup
            if not urls:
                html = page.content()
                self.logger.debug("Search page HTML length: %d chars", len(html))
                soup = BeautifulSoup(html, "html.parser")
                urls.update(self._harvest_listing_urls(soup, html))

            return sorted(urls)
        finally:
            page.close()

    # --- Extraction hooks --------------------------------------------------

    def _new_record(self, url: str) -> ListingRecord:
        return ListingRecord(url=url)

    def _fill_from_json_ld(self, record: ListingRecord, objs: list[dict[str, Any]]) -> None:
        for obj in objs:
            if not record.address:
                address = extract.extract_address_from_ld(obj)
                if address:
                    record.address = address

            if not record.price:
                price = extract.find_value_by_key(obj, ["price", "askingPrice"])
                if price is not None:
                    record.price = extract.format_price_value(price)

            if not record.date_listed:
                value = extract.find_value_by_key(obj, ["datePosted", "datePublished", "dateCreated"])
                if value is not None:
                    record.date_listed = str(value)

    def _fill_from_dict_guessing(self, record: ListingRecord, data: dict[str, Any]) -> None:
        if not data:
            return

        if not record.address:
            record.address = extract.safe_str(
                extract.find_value_by_key(
                    data,
                    [
                        "displayAddress",
                        "address",
                        "streetAddress",
                        "formattedAddress",
                        "seoAddress",
                    ],
                )
            )

        if not record.price:
            record.price = extract.format_price_value(
                extract.find_value_by_key(data, ["price", "askingPrice", "salePrice"])
            )

        if not record.price_per_sq_meter:
            ppm = extract.find_value_by_key(
                data,
                ["pricePerSqM", "pricePerSqm", "price_per_sqm", "pricePerSquareMeter", "pricePerSqMetre"],
            )
            if ppm is not None:
                record.price_per_sq_meter = extract.safe_str(ppm)

        if not record.ber_rating:
            ber = extract.find_value_by_key(data, ["ber", "berRating", "energyRating", "energyLabel"])
            if ber is not None:
                record.ber_rating = extract.safe_str(ber)

        if not record.date_listed:
            date_listed = extract.find_value_by_key(
                data,
                ["dateListed", "listedDate", "datePublished", "publishDate", "datePosted"],
            )
            if date_listed is not None:
                record.date_listed = extract.safe_str(date_listed)

        if not record.view_count:
            views = extract.find_value_by_key(data, ["views", "viewCount", "pageViews", "numViews", "totalViews"])
            if views is not None:
                record.view_count = extract.safe_str(views)

    def _fill_from_text_fallback(self, record: ListingRecord, soup: BeautifulSoup, html: str) -> None:
        page_text = soup.get_text(" ", strip=True)

        if not record.address:
            # Main title often contains the address.
            h1 = soup.find("h1")
            if h1:
                record.address = extract.safe_str(h1.get_text(" ", strip=True))

        if not record.address:
            for prop in ("og:title", "twitter:title"):
                meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
                if meta and meta.get("content"):
                    record.address = extract.safe_str(meta["content"])
                    break

        if not record.price:
            m = re.search(r"€\s?[\d,.]+(?:\s?(?:million|m))?", page_text, re.IGNORECASE)
            if m:
                record.price = m.group(0).strip()

        if not record.price_per_sq_meter:
            patterns = [
                r"(€\s?[\d,.]+(?:\.\d+)?\s*/\s*m²)",
                r"(€\s?[\d,.]+(?:\.\d+)?\s*per\s*sq\.?\s*m(?:eter|etre)?)",
                r"(€\s?[\d,.]+(?:\.\d+)?\s*/\s*sq\.?\s*m)",
            ]
            for p in patterns:
                m = re.search(p, page_text, re.IGNORECASE)
                if m:
                    record.price_per_sq_meter = m.group(1).strip()
                    break

        if not record.ber_rating:
            # BER examples: A1, B2, C3, Exempt
            m = re.search(r"\bBER\b\s*[:\-]?\s*(A[1-3]|B[1-3]|C[1-3]|D[1-2]?|E[1-2]?|F|G|Exempt)", page_text, re.IGNORECASE)
            if m:
                record.ber_rating = m.group(1).upper()
            else:
                m2 = re.search(r'"ber(?:Rating)?"\s*:\s*"([A-G][1-3]?|Exempt)"', html, re.IGNORECASE)
                if m2:
                    record.ber_rating = m2.group(1).upper()

        if not record.date_listed:
            m = re.search(
                r"(?:Date\s*listed|Listed\s*on|Listing\s*date)\s*[:\-]?\s*([A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}|\d{1,2}[/-]\d{1,2}[/-]\d{2,4})",
                page_text,
                re.IGNORECASE,
            )
            if m:
                record.date_listed = m.group(1).strip()
            else:
                # ISO-like date inside scripts.
                m2 = re.search(r'"(?:dateListed|datePosted|datePublished)"\s*:\s*"([^\"]+)"', html)
                if m2:
                    record.date_listed = m2.group(1).strip()

        if not record.view_count:
            m = re.search(r"(?:Views?|View\s*count|Page\s*views?)\s*[:\-]?\s*([\d,]+)", page_text, re.IGNORECASE)
            if m:
                record.view_count = m.group(1).replace(",", "")
            else:
                m2 = re.search(r'"(?:viewCount|views|numViews|totalViews)"\s*:\s*([\d,]+)', html, re.IGNORECASE)
                if m2:
                    record.view_count = m2.group(1).replace(",", "")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Scrape Daft.ie listing details from a search page URL")
    p.add_argument(
        "--search-url",
        default="https://www.daft.ie/property-for-sale/bandon-cork?salePrice_to=250000&salePrice_from=100000",
        help="Daft search results URL",
    )
    p.add_argument("--output-csv", default=None, help="Output CSV file path (default: timestamped)")
    p.add_argument("--output-json", default=None, help="Output JSON file path (default: timestamped)")
    p.add_argument("--max-listings", type=int, default=0, help="Max number of listings to scrape (0 = all)")
    p.add_argument("--delay-min", type=float, default=1.0, help="Minimum delay between listing requests")
    p.add_argument("--delay-max", type=float, default=2.5, help="Maximum delay between listing requests")
    p.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds")
    p.add_argument("--visible", action="store_true", help="Show browser window (disable headless mode)")
    return p.parse_args()


def main() -> int:
    logger = setup_logging("daft_sale_scraper")
    args = parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output_csv is None:
        args.output_csv = default_output_path(f"daft_listings_{timestamp}.csv")
    if args.output_json is None:
        args.output_json = default_output_path(f"daft_listings_{timestamp}.json")

    if args.delay_max < args.delay_min:
        logger.error("--delay-max must be >= --delay-min")
        return 2

    with DaftScraper(timeout=args.timeout, headless=not args.visible) as scraper:
        try:
            records = scrape_search(
                scraper, args.search_url, args.max_listings, args.delay_min, args.delay_max
            )
        except Exception as exc:
            logger.error("Failed to load search page: %s", exc)
            return 1

        if not records:
            return 1

        write_csv(args.output_csv, records, SALE_FIELDS)
        write_json(args.output_json, records)

        logger.info("Saved %d records to %s and %s", len(records), args.output_csv, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
