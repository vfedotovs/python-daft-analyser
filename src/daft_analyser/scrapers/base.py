"""Shared Playwright browser lifecycle and scrape orchestration.

``BaseDaftScraper`` holds everything the sale and rent scrapers have in common:
platform detection, stealth browser setup, page fetching, cookie/human-behavior
handling, and the three-pass ``scrape_listing`` pipeline. Subclasses customise
behavior via class attributes and by implementing the ``_fill_*`` /
``_new_record`` hooks.
"""

from __future__ import annotations

import logging
import platform
import random
import re
import time
from typing import Any, Generic, TypeVar
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext
from playwright_stealth import Stealth

from . import extract

BASE_URL = "https://www.daft.ie"

R = TypeVar("R")


class BaseDaftScraper(Generic[R]):
    # --- Subclass configuration -------------------------------------------
    LOGGER_NAME: str = "daft_scraper"
    CHROME_VERSION: str = "133.0.0.0"
    CHROMIUM_ARGS: list[str] = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
    ]
    NAV_WAIT_UNTIL: str = "domcontentloaded"
    DISMISS_COOKIES: bool = False
    SIMULATE_HUMAN: bool = False
    # CSS selector + URL regexes identifying listing links for this section.
    LISTING_HREF_SELECTOR: str = "a[href]"
    # Anchored regex validating a full listing URL.
    LISTING_URL_RE: re.Pattern[str] = re.compile(r".*")
    # Loose regex used with re.findall over raw HTML text.
    LISTING_URL_TEXT_RE: str = r""

    def __init__(self, timeout: int = 30, headless: bool = True) -> None:
        self.timeout = timeout
        self.headless = headless
        self.logger = logging.getLogger(self.LOGGER_NAME)
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        nav_platform, self._user_agent = self._detect_platform()
        self.logger.info("Detected platform: %s | UA: %s", nav_platform, self._user_agent)
        self._stealth = Stealth(
            navigator_platform_override=nav_platform,
            navigator_vendor_override="Google Inc.",
        )

    # --- Platform / browser ------------------------------------------------

    def _detect_platform(self) -> tuple[str, str]:
        """Return (navigator_platform, user_agent) matching the current OS/arch."""
        system = platform.system()
        machine = platform.machine()
        if system == "Darwin":
            return "MacIntel", (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{self.CHROME_VERSION} Safari/537.36"
            )
        # Linux — distinguish x86_64 vs aarch64 (ARM/Graviton)
        if machine in ("aarch64", "arm64"):
            arch = "aarch64"
        else:
            arch = "x86_64"
        return f"Linux {arch}", (
            f"Mozilla/5.0 (X11; Linux {arch}) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{self.CHROME_VERSION} Safari/537.36"
        )

    def _viewport(self) -> dict[str, int]:
        """Override to randomise; defaults to a fixed 1920x1080 desktop."""
        return {"width": 1920, "height": 1080}

    def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        self.logger.debug("Launching Chromium (headless=%s)...", self.headless)
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            headless=self.headless,
            args=self.CHROMIUM_ARGS,
        )
        self.logger.debug("Chromium launched successfully")
        self._context = self._browser.new_context(
            user_agent=self._user_agent,
            viewport=self._viewport(),
            locale="en-IE",
            timezone_id="Europe/Dublin",
        )
        self._stealth.apply_stealth_sync(self._context)

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

    def __enter__(self):
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    # --- Human-like behavior ----------------------------------------------

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

    # --- Fetching ----------------------------------------------------------

    def fetch_html(self, url: str) -> str:
        self._ensure_browser()
        assert self._context is not None
        page = self._context.new_page()
        try:
            try:
                page.goto(url, timeout=self.timeout * 1000, wait_until=self.NAV_WAIT_UNTIL)
            except Exception as e:
                self.logger.debug(
                    "Navigation with %s timed out: %s, retrying with domcontentloaded",
                    self.NAV_WAIT_UNTIL, e,
                )
                page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")

            if self.DISMISS_COOKIES:
                self._dismiss_cookies(page)
            if self.SIMULATE_HUMAN:
                self._human_behavior(page)

            # Wait for actual listing content to render (JS challenge + SSR hydration)
            try:
                page.wait_for_selector(self.LISTING_HREF_SELECTOR, timeout=15_000)
            except Exception:
                self.logger.debug("Selector wait timed out, falling back to fixed wait")
                page.wait_for_timeout(5000)
            return page.content()
        finally:
            page.close()

    # --- Search results ----------------------------------------------------

    def get_listing_urls_from_search(self, search_url: str) -> list[str]:
        """Default HTML-based discovery: fetch the search page and harvest
        listing links via BeautifulSoup + a regex fallback over raw HTML."""
        html = self.fetch_html(search_url)
        self.logger.debug("Search page HTML length: %d chars", len(html))
        soup = BeautifulSoup(html, "html.parser")
        return self._harvest_listing_urls(soup, html)

    def _harvest_listing_urls(self, soup: BeautifulSoup, html: str) -> list[str]:
        urls: set[str] = set()

        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href:
                continue
            full = urljoin(BASE_URL, href)
            if self.LISTING_URL_RE.match(full):
                urls.add(full.rstrip("/"))

        if self.LISTING_URL_TEXT_RE:
            for m in re.findall(self.LISTING_URL_TEXT_RE, html):
                if self.LISTING_URL_RE.match(m):
                    urls.add(m.rstrip("/"))

        return sorted(urls)

    # --- Listing scrape pipeline ------------------------------------------

    def scrape_listing(self, url: str) -> R:
        html = self.fetch_html(url)
        soup = BeautifulSoup(html, "html.parser")

        record = self._new_record(url)

        # 1) Structured data (JSON-LD)
        self._fill_from_json_ld(record, extract.extract_json_ld_objects(soup))
        # 2) Next.js payloads and other script JSON
        self._fill_from_dict_guessing(record, extract.extract_next_data(soup))
        # 3) Visible text and metadata fallbacks
        self._fill_from_text_fallback(record, soup, html)

        return record

    # --- Hooks for subclasses ---------------------------------------------

    def _new_record(self, url: str) -> R:
        raise NotImplementedError

    def _fill_from_json_ld(self, record: R, objs: list[dict[str, Any]]) -> None:
        raise NotImplementedError

    def _fill_from_dict_guessing(self, record: R, data: dict[str, Any]) -> None:
        raise NotImplementedError

    def _fill_from_text_fallback(self, record: R, soup: BeautifulSoup, html: str) -> None:
        raise NotImplementedError


def scrape_search(
    scraper: BaseDaftScraper[R],
    search_url: str,
    max_listings: int,
    delay_min: float,
    delay_max: float,
) -> list[R]:
    """Discover listing URLs from a search page and scrape each one, with a
    randomised delay between requests. Returns the collected records."""
    logger = scraper.logger
    urls = scraper.get_listing_urls_from_search(search_url)

    if not urls:
        logger.error("No listing URLs found. The page may require JavaScript or has blocked scraping.")
        return []

    if max_listings and max_listings > 0:
        urls = urls[:max_listings]

    logger.info("Found %d listing URLs", len(urls))

    records: list[R] = []
    for idx, url in enumerate(urls, start=1):
        try:
            records.append(scraper.scrape_listing(url))
            logger.info("[%d/%d] OK  %s", idx, len(urls), url)
        except Exception as exc:
            logger.error("[%d/%d] ERR %s -> %s", idx, len(urls), url, exc)

        if idx < len(urls):
            time.sleep(random.uniform(delay_min, delay_max))

    return records
