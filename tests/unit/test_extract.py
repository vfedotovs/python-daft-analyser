"""Offline tests for the shared extraction helpers (no browser/network)."""

from bs4 import BeautifulSoup

from daft_analyser.scrapers import extract


# --- scalar helpers --------------------------------------------------------


def test_normalize_key_strips_non_alphanumerics():
    assert extract.normalize_key("Price_Per-Sq M²") == "pricepersqm"
    assert extract.normalize_key("dateListed") == "datelisted"


def test_safe_str():
    assert extract.safe_str("  hi  ") == "hi"
    assert extract.safe_str("") is None
    assert extract.safe_str(None) is None
    assert extract.safe_str(42) == "42"


def test_safe_int():
    assert extract.safe_int(3) == 3
    assert extract.safe_int(" 7 ") == 7
    assert extract.safe_int(None) is None
    assert extract.safe_int("not-a-number") is None


def test_format_price_value():
    assert extract.format_price_value(135000) == "€135,000"
    assert extract.format_price_value("€2,700") == "€2,700"
    assert extract.format_price_value("") is None
    assert extract.format_price_value(None) is None


# --- find_value_by_key -----------------------------------------------------


def test_find_value_by_key_nested_and_normalised():
    data = {"a": {"b": [{"Display-Address": "1 Main St"}]}}
    assert extract.find_value_by_key(data, ["displayAddress"]) == "1 Main St"


def test_find_value_by_key_returns_none_when_absent():
    assert extract.find_value_by_key({"x": 1}, ["price"]) is None


def test_find_value_by_key_skips_non_scalar_match():
    # A matching key whose value is a dict is skipped; search continues.
    data = {"price": {"amount": 5}, "askingPrice": 250000}
    assert extract.find_value_by_key(data, ["price", "askingPrice"]) == 250000


# --- JSON-LD / __NEXT_DATA__ -----------------------------------------------


def test_extract_json_ld_objects_handles_dicts_and_lists():
    html = """
    <html><head>
    <script type="application/ld+json">{"@type": "Residence", "price": 250000}</script>
    <script type="application/ld+json">[{"a": 1}, "skip", {"b": 2}]</script>
    <script type="application/ld+json">not json</script>
    </head></html>
    """
    objs = extract.extract_json_ld_objects(BeautifulSoup(html, "html.parser"))
    assert {"@type": "Residence", "price": 250000} in objs
    assert {"a": 1} in objs and {"b": 2} in objs
    assert len(objs) == 3  # the invalid-JSON block is dropped


def test_extract_next_data():
    html = '<script id="__NEXT_DATA__">{"props": {"x": 1}}</script>'
    assert extract.extract_next_data(BeautifulSoup(html, "html.parser")) == {"props": {"x": 1}}


def test_extract_next_data_absent_returns_empty():
    assert extract.extract_next_data(BeautifulSoup("<html></html>", "html.parser")) == {}


# --- address from JSON-LD --------------------------------------------------


def test_extract_address_from_ld_string():
    assert extract.extract_address_from_ld({"address": " 1 Main St "}) == "1 Main St"


def test_extract_address_from_ld_object():
    obj = {
        "address": {
            "streetAddress": "1 Main St",
            "addressLocality": "Bandon",
            "addressRegion": "Cork",
        }
    }
    assert extract.extract_address_from_ld(obj) == "1 Main St, Bandon, Cork"


def test_extract_address_from_ld_missing():
    assert extract.extract_address_from_ld({"name": "x"}) is None
