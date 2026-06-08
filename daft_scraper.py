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
import csv
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

logger = logging.getLogger("daft_sale_scraper")

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext
from playwright_stealth import Stealth

BASE_URL = "https://www.daft.ie"


def _detect_platform() -> tuple[str, str]:
    """Return (navigator_platform, user_agent) matching the current OS/arch."""
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin":
        return "MacIntel", (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/133.0.0.0 Safari/537.36"
        )
    # Linux — distinguish x86_64 vs aarch64 (ARM/Graviton)
    if machine in ("aarch64", "arm64"):
        arch = "aarch64"
    else:
        arch = "x86_64"
    return f"Linux {arch}", (
        f"Mozilla/5.0 (X11; Linux {arch}) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/133.0.0.0 Safari/537.36"
    )
LISTING_URL_RE = re.compile(r"^https?://www\.daft\.ie/for-sale/[\w\-.,%/]+/?$", re.IGNORECASE)


@dataclass
class ListingRecord:
    url: str
    address: str | None = None
    price: str | None = None
    price_per_sq_meter: str | None = None
    ber_rating: str | None = None
    date_listed: str | None = None
    view_count: str | None = None


class DaftScraper:
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
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        logger.debug("Chromium launched successfully")
        self._context = self._browser.new_context(
            user_agent=self._user_agent,
            viewport={"width": random.randint(1280, 1440), "height": random.randint(800, 900)},
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )
        self._stealth.apply_stealth_sync(self._context)

    @staticmethod
    def _human_behavior(page) -> None:
        """Simulate human-like mouse movements and scrolling."""
        for _ in range(random.randint(5, 10)):
            x, y = random.randint(100, 1000), random.randint(100, 1000)
            page.mouse.move(x, y, steps=random.randint(20, 40))
            time.sleep(random.uniform(0.1, 0.4))
        page.mouse.wheel(0, random.randint(600, 1500))
        time.sleep(random.uniform(2.0, 5.0))

    @staticmethod
    def _dismiss_cookies(page) -> None:
        """Try to dismiss Daft's cookie consent banner."""
        try:
            btn = page.locator('button:has-text("Accept All"), #didomi-notice-agree-button')
            if btn.is_visible(timeout=5000):
                btn.click()
                time.sleep(random.uniform(1.0, 2.0))
        except Exception:
            pass

    def fetch_html(self, url: str) -> str:
        self._ensure_browser()
        assert self._context is not None
        page = self._context.new_page()
        try:
            try:
                page.goto(url, timeout=self.timeout * 1000, wait_until="networkidle")
            except Exception as e:
                logger.debug("Navigation with networkidle timed out: %s, retrying with domcontentloaded", e)
                page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")

            self._dismiss_cookies(page)
            self._human_behavior(page)

            # Wait for actual listing content to render
            try:
                page.wait_for_selector("a[href*='/for-sale/']", timeout=15_000)
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

    def __enter__(self) -> "DaftScraper":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def get_listing_urls_from_search(self, search_url: str) -> list[str]:
        self._ensure_browser()
        assert self._context is not None
        page = self._context.new_page()
        try:
            try:
                page.goto(search_url, timeout=self.timeout * 1000, wait_until="networkidle")
            except Exception as e:
                logger.debug("Navigation timed out: %s", e)

            # Take debug screenshot
            page.screenshot(path="debug_view.png")
            logger.debug("Debug screenshot saved as debug_view.png")

            self._dismiss_cookies(page)
            self._human_behavior(page)

            # Primary: use Playwright locators to find listing links (works even with JS-rendered content)
            urls: set[str] = set()
            links = page.locator('a[href*="/for-sale/"]')
            count = links.count()
            logger.debug("Found %d raw links via Playwright locator", count)

            for i in range(count):
                href = links.nth(i).get_attribute("href")
                if href:
                    full = urljoin(BASE_URL, href)
                    if LISTING_URL_RE.match(full):
                        urls.add(full.rstrip("/"))

            # Fallback: parse full HTML with BeautifulSoup
            if not urls:
                html = page.content()
                logger.debug("Search page HTML length: %d chars", len(html))
                soup = BeautifulSoup(html, "html.parser")

                for a in soup.select("a[href]"):
                    href = a.get("href", "").strip()
                    if not href:
                        continue
                    full = urljoin(BASE_URL, href)
                    if LISTING_URL_RE.match(full):
                        urls.add(full.rstrip("/"))

                for m in re.findall(r"https://www\.daft\.ie/for-sale/[\w\-.,%/]+", html):
                    if LISTING_URL_RE.match(m):
                        urls.add(m.rstrip("/"))

            return sorted(urls)
        finally:
            page.close()

    def scrape_listing(self, url: str) -> ListingRecord:
        html = self.fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        record = ListingRecord(url=url)

        # 1) Structured data (JSON-LD)
        json_ld = self._extract_json_ld_objects(soup)
        self._fill_from_json_ld(record, json_ld)

        # 2) Next.js payloads and other script JSON
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

    def _fill_from_json_ld(self, record: ListingRecord, objs: list[dict[str, Any]]) -> None:
        for obj in objs:
            if not record.address:
                address = self._extract_address_from_ld(obj)
                if address:
                    record.address = address

            if not record.price:
                price = self._find_value_by_key(obj, ["price", "askingPrice"])
                if price is not None:
                    record.price = self._format_price_value(price)

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

    def _fill_from_dict_guessing(self, record: ListingRecord, data: dict[str, Any]) -> None:
        if not data:
            return

        if not record.address:
            record.address = self._safe_str(
                self._find_value_by_key(
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
            record.price = self._format_price_value(
                self._find_value_by_key(data, ["price", "askingPrice", "salePrice"])
            )

        if not record.price_per_sq_meter:
            ppm = self._find_value_by_key(
                data,
                ["pricePerSqM", "pricePerSqm", "price_per_sqm", "pricePerSquareMeter", "pricePerSqMetre"],
            )
            if ppm is not None:
                record.price_per_sq_meter = self._safe_str(ppm)

        if not record.ber_rating:
            ber = self._find_value_by_key(data, ["ber", "berRating", "energyRating", "energyLabel"])
            if ber is not None:
                record.ber_rating = self._safe_str(ber)

        if not record.date_listed:
            date_listed = self._find_value_by_key(
                data,
                ["dateListed", "listedDate", "datePublished", "publishDate", "datePosted"],
            )
            if date_listed is not None:
                record.date_listed = self._safe_str(date_listed)

        if not record.view_count:
            views = self._find_value_by_key(data, ["views", "viewCount", "pageViews", "numViews", "totalViews"])
            if views is not None:
                record.view_count = self._safe_str(views)

    def _fill_from_text_fallback(self, record: ListingRecord, soup: BeautifulSoup, html: str) -> None:
        page_text = soup.get_text(" ", strip=True)

        if not record.address:
            # Main title often contains the address.
            h1 = soup.find("h1")
            if h1:
                record.address = self._safe_str(h1.get_text(" ", strip=True))

        if not record.address:
            for prop in ("og:title", "twitter:title"):
                meta = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
                if meta and meta.get("content"):
                    record.address = self._safe_str(meta["content"])
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
    def _format_price_value(v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return f"€{v:,.0f}"
        s = str(v).strip()
        if not s:
            return None
        return s


def write_csv(path: str, records: list[ListingRecord]) -> None:
    fields = [
        "url",
        "address",
        "price",
        "price_per_sq_meter",
        "ber_rating",
        "date_listed",
        "view_count",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for rec in records:
            writer.writerow(asdict(rec))


def write_json(path: str, records: list[ListingRecord]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in records], f, indent=2, ensure_ascii=False)


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
    logging.basicConfig(
        level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

    args = parse_args()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.output_csv is None:
        args.output_csv = f"daft_listings_{timestamp}.csv"
    if args.output_json is None:
        args.output_json = f"daft_listings_{timestamp}.json"

    if args.delay_max < args.delay_min:
        logger.error("--delay-max must be >= --delay-min")
        return 2

    with DaftScraper(timeout=args.timeout, headless=not args.visible) as scraper:
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

        records: list[ListingRecord] = []
        for idx, url in enumerate(urls, start=1):
            try:
                rec = scraper.scrape_listing(url)
                records.append(rec)
                logger.info("[%d/%d] OK  %s", idx, len(urls), url)
            except Exception as exc:
                logger.error("[%d/%d] ERR %s -> %s", idx, len(urls), url, exc)

            if idx < len(urls):
                time.sleep(random.uniform(args.delay_min, args.delay_max))

        write_csv(args.output_csv, records)
        write_json(args.output_json, records)

        logger.info("Saved %d records to %s and %s", len(records), args.output_csv, args.output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
