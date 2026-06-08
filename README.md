# python-daft-analyser
This project is an independent tool for personal data analysis and is not affiliated with, endorsed by, or connected to Daft.ie in any way.


```bash
pip install -r requirements.txt
python3 daft_scraper.py --search-url
"https://www.daft.ie/property-for-sale/bandon-cork?salePrice_to=225000&salePrice_from=100000"
```

## To use: Install playwright browsers (one-time)
```bash
uv run playwright install chromium
```

## Run scraper
```bash
uv run python3 daft_scraper.py --search-url "https://www.daft.ie/property-for-sale/..."
```

## Debug with visible browser
```bash
uv run python3 daft_scraper.py --visible --search-url "..."
```


## Rent Scraper (Cork City)
## Run with defaults (30 listings, Cork City)
```bash
uv run python3 daft_rent_scraper.py
```

## Scrape a single listing with visible browser
```bash
uv run python3 daft_rent_scraper.py --max-listings 1 --visible
```
## Custom search URL
```bash
uv run python3 daft_rent_scraper.py --search-url "https://www.daft.ie/property-for-rent/cork-city?sort=publishDateDesc"
```

## Custom output file
```bash
uv run python3 daft_rent_scraper.py --output my_rentals.json

Output: JSON file (rent_cork_city_YYYYMMDD_HHMM.json) with fields:
url, address, rent_price, property_type, ber_rating, double_bedroom, bathroom, available_from, furnished, lease, date_listed, views
```



## Scoring Report
### Ranks sale listings 0-100 by purchase priority. Uses BER-adjusted pricing, true monthly cost estimates, and time-degradation phases (SALE_FOCUS -> DUAL_TRACK -> RENTAL_FOCUS).

## Basic usage (sale CSV only, uses default avg Cork rent of €2,197/mo)
```bash
python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv
```

## With rent comparables (computes avg rent from JSON)
```bash
python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv --rent-json rent_cork_city_20260301_1701.json
```

## Show only top 5 listings
```bash
python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv --top 5
```

## Filter by minimum score
```bash
python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv --min-score 70
```

## Export JSON report
```bash
python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv --output scored_report.json
```

## Override financial parameters
```bash
python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv --avg-rent 2300 --loan-amount 200000 --mortgage-rate 0.04
```

## Full example: rent comps + top 5 + JSON export
```bash
python3 scoring_report.py --sale-csv daft_listings_20260301_180820.csv --rent-json rent_cork_city_20260301_1701.json --top 5 --output report.json
```
