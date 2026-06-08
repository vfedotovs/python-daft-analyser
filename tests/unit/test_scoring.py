"""Offline tests for the scoring subpackage (finance math + scoring components)."""

from datetime import date

from daft_analyser.scoring import finance, scoring
from daft_analyser.scoring.models import SaleListing


# --- finance ---------------------------------------------------------------


def test_monthly_mortgage_annuity():
    # €180k at 3.5% over 30y ≈ €808.28/mo
    pmt = finance.monthly_mortgage(180_000, 0.035, 30)
    assert round(pmt, 2) == 808.28


def test_monthly_mortgage_zero_rate_is_straight_line():
    assert finance.monthly_mortgage(120_000, 0.0, 10) == 1000.0


def test_compute_tmc_adds_service_and_heating():
    # mortgage(808.28) + service(50) + heating(C1=100)
    tmc = finance.compute_tmc("C1", 180_000, 0.035, 30, 50)
    assert tmc == round(808.28 + 50 + 100, 2)


def test_compute_tmc_unknown_ber_uses_default_heating():
    tmc = finance.compute_tmc("", 180_000, 0.035, 30, 50)
    assert tmc == round(808.28 + 50 + finance.DEFAULT_HEATING, 2)


def test_is_green_mortgage_eligible():
    assert finance.is_green_mortgage_eligible("B3") is True
    assert finance.is_green_mortgage_eligible("C1") is False


def test_compute_nvs_applies_retrofit_cost():
    # G-rated retrofit cost is +25,000; (250000 + 25000) / 100 = 2750
    assert finance.compute_nvs(250_000, 100, "G") == 2750.0
    assert finance.compute_nvs(250_000, 0, "G") == 0.0


# --- scoring components ----------------------------------------------------


def test_score_freshness_bounds():
    assert scoring.score_freshness(0) == 40.0
    assert scoring.score_freshness(60) == 0.0
    assert scoring.score_freshness(100) == 0.0


def test_score_location_tiers():
    assert scoring.score_location("Patrick Street, Cork City Centre") == 20.0
    assert scoring.score_location("Douglas, Cork") == 15.0
    assert scoring.score_location("Nowhere-ville") == 5.0  # default lowest tier


def test_get_phase():
    assert scoring.get_phase(date(2026, 4, 1)) == "SALE_FOCUS"
    assert scoring.get_phase(date(2026, 5, 15)) == "DUAL_TRACK"
    assert scoring.get_phase(date(2026, 7, 1)) == "RENTAL_FOCUS"


def test_priority_label():
    assert scoring.priority_label(0) == "NO_DATA"
    assert scoring.priority_label(3000) == "CRITICAL"
    assert scoring.priority_label(4000) == "STANDARD"
    assert scoring.priority_label(5000) == "LOW"


# --- orchestrator ----------------------------------------------------------


def test_score_listings_sorts_desc_and_populates():
    listings = [
        SaleListing(
            url="https://www.daft.ie/for-sale/a/1", address="Douglas, Cork",
            price=250_000, price_per_sqm=2500, sqm=100, ber_rating="B2",
            date_listed=date(2026, 4, 1), view_count=6000, days_on_market=1,
        ),
        SaleListing(
            url="https://www.daft.ie/for-sale/b/2", address="Nowhere",
            price=300_000, price_per_sqm=3000, sqm=100, ber_rating="G",
            date_listed=date(2026, 4, 1), view_count=10, days_on_market=80,
        ),
    ]
    scored = scoring.score_listings(
        listings, avg_rent=2197, loan_amount=180_000, rate=0.035,
        term=30, service_charge_mo=50, today=date(2026, 4, 15),
    )
    assert len(scored) == 2
    # Sorted by total_score descending.
    assert scored[0].total_score >= scored[1].total_score
    # The fresh, green-mortgage, well-located listing should win.
    assert scored[0].listing.address == "Douglas, Cork"
    assert scored[0].green_mortgage is True
