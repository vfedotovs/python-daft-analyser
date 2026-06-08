"""Financial constants and calculations: mortgage, true monthly cost, NVS."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Defaults
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


# ---------------------------------------------------------------------------
# Calculations
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
