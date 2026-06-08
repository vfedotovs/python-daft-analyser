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
import json
import logging
import os
import platform
import random
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

logger = logging.getLogger("daft_rent_scraper")

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext
from playwright_stealth import Stealth

BASE_URL = "https://www.daft.ie"
DATA_DIR = os.environ.get("DATA_DIR", "data")


def _default_output_path(filename: str) -> str:
    """Resolve a default output filename inside DATA_DIR, creating the dir."""
    os.makedirs(DATA_DIR, exist_ok=True)
    return os.path.join(DATA_DIR, filename)


def _detect_platform() -> tuple[str, str]:
    """Return (navigator_platform, user_agent) matching the current OS/arch."""
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin":
        return "MacIntel", (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        )
    # Linux — distinguish x86_64 vs aarch64 (ARM/Graviton)
    if machine in ("aarch64", "arm64"):
        arch = "aarch64"
    else:
        arch = "x86_64"
    return f"Linux {arch}", (
        f"Mozilla/5.0 (X11; Linux {arch}) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
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


class DaftRentScraper:
    def __init__(self, timeout: int = 30, headless: bool = True) -> None:
        self.timeout = timeout
        self.headless = headless
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        nav_platform, self._user_agent = _detect_platform()
        logger.info("Detected platform: %s | UA: %s", nav_platform, self._user_agent)
        self._stealth = Stealth(
            navigator_platform_override=nav_platform,
            navigator_vendor_override="Google Inc.",
        )

    def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        logger.debug("Launching Chromium (headless=%s)...", self.headless)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        logger.debug("Chromium launched successfully")
        self._context = self._browser.new_context(
            user_agent=self._user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )
        self._stealth.apply_stealth_sync(self._context)

    def fetch_html(self, url: str) -> str:
        self._ensure_browser()
        assert self._context is not None
        page = self._context.new_page()
        try:
            page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
            # Wait for actual listing content to render (JS challenge + SSR hydration)
            try:
                page.wait_for_selector("a[href*='/for-rent/']", timeout=15_000)
            except Exception:
                logger.debug("Selector wait timed out, falling back to fixed wait")
                page.wait_for_timeout(5000)
            return page.content()
        finally:
            page.close()

    def close(self) -> None:
        if self._context:
            self._context.close()
            self._context = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None

    def __enter__(self) -> "DaftRentScraper":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def get_listing_urls_from_search(self, search_url: str) -> list[str]:
        html = self.fetch_html(search_url)
        logger.debug("Search page HTML length: %d chars", len(html))
        logger.debug("Search page HTML snippet: %.500s", html)
        soup = BeautifulSoup(html, "html.parser")

        urls: set[str] = set()

        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue
            full = urljoin(BASE_URL, href)
            if LISTING_URL_RE.match(full):
                urls.add(full.rstrip("/"))

        for m in re.findall(r"https://www\.daft\.ie/for-rent/[\w\-.,%/]+", html):
            if LISTING_URL_RE.match(m):
                urls.add(m.rstrip("/"))

        return sorted(urls)

    def scrape_listing(self, url: str) -> RentListingRecord:
        html = self.fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        record = RentListingRecord(url=url)

        # 1) Structured data (JSON-LD)
        json_ld = self._extract_json_ld_objects(soup)
        self._fill_from_json_ld(record, json_ld)

        # 2) Next.js payloads
        next_data = self._extract_next_data(soup)
        self._fill_from_dict_guessing(record, next_data)

        # 3) Visible text and metadata fallbacks
        self._fill_from_text_fallback(record, soup, html)

        return record

    @staticmethod
    def _extract_json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
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

    def _fill_from_json_ld(self, record: RentListingRecord, objs: list[dict[str, Any]]) -> None:
        for obj in objs:
            if not record.address:
                address = self._extract_address_from_ld(obj)
                if address:
                    record.address = address

            if not record.rent_price:
                price = self._find_value_by_key(obj, ["price", "monthlyRent", "rentPrice"])
                if price is not None:
                    record.rent_price = self._format_rent_price(price)

            if not record.date_listed:
                value = self._find_value_by_key(obj, ["datePosted", "datePublished", "dateCreated"])
                if value is not None:
                    record.date_listed = str(value)

    @staticmethod
    def _extract_next_data(soup: BeautifulSoup) -> dict[str, Any]:
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

    def _fill_from_dict_guessing(self, record: RentListingRecord, data: dict[str, Any]) -> None:
        if not data:
            return

        if not record.address:
            # Prefer displayAddress (the property address) over generic "address"
            # which may match the agent's office address.
            record.address = self._safe_str(
                self._find_value_by_key(data, ["displayAddress"])
            ) or self._safe_str(
                self._find_value_by_key(data, ["seoAddress", "formattedAddress"])
            )

        if not record.rent_price:
            price = self._find_value_by_key(
                data, ["price", "monthlyRent", "rentPrice", "rent", "monthlyPrice"]
            )
            if price is not None:
                record.rent_price = self._format_rent_price(price)

        if not record.property_type:
            record.property_type = self._safe_str(
                self._find_value_by_key(
                    data, ["propertyType", "category", "propertyCategory"]
                )
            )

        if not record.ber_rating:
            ber = self._find_value_by_key(data, ["ber", "berRating", "energyRating", "energyLabel"])
            if ber is not None:
                record.ber_rating = self._safe_str(ber)

        if record.double_bedroom is None:
            beds = self._find_value_by_key(
                data, ["numBedrooms", "bedrooms", "numBeds", "bedroomCount", "doubleBedroom"]
            )
            if beds is not None:
                record.double_bedroom = self._safe_int(beds)

        if record.bathroom is None:
            baths = self._find_value_by_key(
                data, ["numBathrooms", "bathrooms", "bathroomCount", "numBaths"]
            )
            if baths is not None:
                record.bathroom = self._safe_int(baths)

        if not record.available_from:
            record.available_from = self._safe_str(
                self._find_value_by_key(
                    data, ["availableFrom", "availableDate", "moveInDate", "availabilityDate"]
                )
            )

        if not record.furnished:
            record.furnished = self._safe_str(
                self._find_value_by_key(
                    data, ["furnished", "furnishing", "furnishType", "isFurnished"]
                )
            )

        if not record.lease:
            record.lease = self._safe_str(
                self._find_value_by_key(
                    data, ["leaseTerm", "lease", "leaseLength", "minimumLease", "leaseDuration"]
                )
            )

        if not record.date_listed:
            record.date_listed = self._safe_str(
                self._find_value_by_key(
                    data, ["dateListed", "listedDate", "datePublished", "publishDate", "datePosted"]
                )
            )

        if not record.views:
            views = self._find_value_by_key(
                data, ["views", "viewCount", "pageViews", "numViews", "totalViews"]
            )
            if views is not None:
                record.views = self._safe_str(views)

    def _fill_from_text_fallback(self, record: RentListingRecord, soup: BeautifulSoup, html: str) -> None:
        page_text = soup.get_text(" ", strip=True)

        # Address
        if not record.address:
            h1 = soup.find("h1")
            if h1:
                record.address = self._safe_str(h1.get_text(" ", strip=True))

        if not record.address:
            for prop in ("og:title", "twitter:title"):
                meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
                if meta and meta.get("content"):
                    record.address = self._safe_str(meta["content"])
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

    @staticmethod
    def _extract_address_from_ld(obj: dict[str, Any]) -> str | None:
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

    def _find_value_by_key(self, obj: Any, key_hints: list[str]) -> Any:
        hints = {self._normalize_key(k) for k in key_hints}

        def walk(node: Any) -> Any:
            if isinstance(node, dict):
                for k, v in node.items():
                    nk = self._normalize_key(str(k))
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

    @staticmethod
    def _normalize_key(k: str) -> str:
        return re.sub(r"[^a-z0-9]", "", k.lower())

    @staticmethod
    def _safe_str(v: Any) -> str | None:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    @staticmethod
    def _safe_int(v: Any) -> int | None:
        if v is None:
            return None
        if isinstance(v, int):
            return v
        try:
            return int(str(v).strip())
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _format_rent_price(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return f"€{v:,.0f} per month"
        s = str(v).strip()
        if not s:
            return None
        return s


def write_json(path: str, records: list[RentListingRecord]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2, ensure_ascii=False)


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
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    args = parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    if args.output is None:
        args.output = _default_output_path(f"rent_cork_city_{timestamp}.json")

    if args.delay_max < args.delay_min:
        logger.error("--delay-max must be >= --delay-min")
        return 2

    with DaftRentScraper(timeout=args.timeout, headless=not args.visible) as scraper:
        try:
            urls = scraper.get_listing_urls_from_search(args.search_url)
        except Exception as exc:
            logger.error("Failed to load search page: %s", exc)
            return 1

        if not urls:
            logger.error("No listing URLs found. The page may require JavaScript or has blocked scraping.")
            return 1

        if args.max_listings and args.max_listings > 0:
            urls = urls[: args.max_listings]

        logger.info("Found %d listing URLs", len(urls))

        records: list[RentListingRecord] = []
        for idx, url in enumerate(urls, start=1):
            try:
                rec = scraper.scrape_listing(url)
                records.append(rec)
                logger.info("[%d/%d] OK  %s", idx, len(urls), url)
            except Exception as exc:
                logger.error("[%d/%d] ERR %s -> %s", idx, len(urls), url, exc)

            if idx < len(urls):
                time.sleep(random.uniform(args.delay_min, args.delay_max))

        write_json(args.output, records)

        logger.info("Saved %d records to %s", len(records), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
