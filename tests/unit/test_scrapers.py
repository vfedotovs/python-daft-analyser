"""Offline wiring tests: drive scrape_listing with canned HTML (no browser).

These confirm BaseDaftScraper.scrape_listing correctly orchestrates each
subclass's _new_record / _fill_* hooks across the JSON-LD, __NEXT_DATA__, and
text-fallback passes.
"""

from daft_analyser.scrapers.sale import DaftScraper, ListingRecord
from daft_analyser.scrapers.rent import DaftRentScraper, RentListingRecord


SALE_HTML = """
<html><head>
<script type="application/ld+json">
{"@type": "SingleFamilyResidence",
 "address": {"streetAddress": "1 Main St", "addressLocality": "Bandon"},
 "price": 250000, "datePublished": "2026-03-01"}
</script>
<script id="__NEXT_DATA__">
{"props": {"pageProps": {"listing": {"pricePerSqM": 3200, "berRating": "C1",
 "viewCount": 1234}}}}
</script>
</head><body><h1>1 Main St, Bandon</h1></body></html>
"""

RENT_HTML = """
<html><head>
<script id="__NEXT_DATA__">
{"props": {"pageProps": {"listing": {"displayAddress": "5 River Rd, Cork",
 "monthlyRent": 1800, "propertyType": "Apartment", "berRating": "B2",
 "numBedrooms": 2, "numBathrooms": 1, "viewCount": 567}}}}
</script>
</head><body><h1>5 River Rd</h1></body></html>
"""


def test_sale_scrape_listing_populates_record(monkeypatch):
    scraper = DaftScraper()
    monkeypatch.setattr(scraper, "fetch_html", lambda url: SALE_HTML)

    rec = scraper.scrape_listing("https://www.daft.ie/for-sale/x/1")

    assert isinstance(rec, ListingRecord)
    assert rec.address == "1 Main St, Bandon"
    assert rec.price == "€250,000"
    assert rec.price_per_sq_meter == "3200"
    assert rec.ber_rating == "C1"
    assert rec.date_listed == "2026-03-01"
    assert rec.view_count == "1234"


def test_rent_scrape_listing_populates_record(monkeypatch):
    scraper = DaftRentScraper()
    monkeypatch.setattr(scraper, "fetch_html", lambda url: RENT_HTML)

    rec = scraper.scrape_listing("https://www.daft.ie/for-rent/x/1")

    assert isinstance(rec, RentListingRecord)
    assert rec.address == "5 River Rd, Cork"
    assert rec.rent_price == "€1,800 per month"
    assert rec.property_type == "Apartment"
    assert rec.ber_rating == "B2"
    assert rec.double_bedroom == 2
    assert rec.bathroom == 1
    assert rec.views == "567"
