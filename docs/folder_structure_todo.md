# Folder Structure Improvements — TODO

A review of the current project layout with concrete restructuring proposals.
The project works today; these changes are about maintainability, testability,
and reducing the heavy code duplication between the two scrapers.

## Action items — priority / effort / impact

Priority = do-it-first ranking. Effort = rough dev time (S ≤1h, M ½–1 day,
L 1–2 days). Impact = maintainability/risk-reduction payoff.

| # | Action item | Priority | Effort | Impact | Risk | Depends on |
|---|-------------|----------|--------|--------|------|------------|
| 1 | Write runtime outputs (CSV/JSON, `debug_view.png`) to a configurable `data/` dir; gitignore it; update `run_scrapers.sh` globs | P0 | S | Medium — declutters root, stops artifacts mixing with source | Low | — |
| 2 | Declare `boto3` in `pyproject.toml`; drop ad-hoc `pip install boto3` from Dockerfile; add optional dep groups (`upload`, `scoring`) | P0 | S | High — fixes silent dependency drift, reproducible builds | Low | — |
| 3 | Create `tests/{unit,integration}/`; split unit vs real-S3 tests; add `integration` pytest marker for `-m "not integration"` in CI | P0 | S | High — safety net before any refactor; unblocks CI | Low | — |
| 4 | Introduce `src/daft_analyser/` package; move `upload_to_s3.py` → `storage/s3.py` first; add packaging config | P1 | M | High — enables clean imports, unblocks all later moves | Medium | 2, 3 |
| 5 | Extract shared scraper core (`scrapers/base.py` + `extract.py`); refactor both scrapers to reuse it | P1 | L | Very High — removes ~300 dup lines; one place to fix anti-bot logic | Medium | 3, 4 |
| 6 | Split `scoring_report.py` into `scoring/{models,finance,scoring,report}.py` | P2 | M | Medium — readability; already banner-sectioned, mostly mechanical | Low | 4 |
| 7 | Add CLI entry points / `[project.scripts]`; update `run_scrapers.sh` + Dockerfile `COPY` paths | P2 | M | Medium — clean commands, decouples orchestration from file paths | Medium | 4, 5 |
| 8 | Move deploy files to `deploy/`, orchestrator to `scripts/`; fix compose build context + Dockerfile paths | P3 | S | Low–Medium — tidiness; touches deployment so verify the image builds | Medium | 7 |
| 9 | Drop or auto-generate `requirements.txt` (`uv export`); switch Dockerfile to `uv sync` to unify toolchain | P3 | S | Medium — single dependency source of truth | Medium | 2 |

**Suggested sequencing:** P0 items (1–3) are independent, low-risk quick wins —
do them first in any order. They also build the test safety net that makes the
P1 refactors (4–5, the highest-impact work) safe. P2/P3 are cleanup that follows
naturally once the package exists.


## Current structure

Everything lives flat in the repository root:

```
python-daft-analyser/
├── daft_scraper.py          # sale scraper (567 lines)
├── daft_rent_scraper.py     # rent scraper (571 lines)
├── scoring_report.py        # scoring/ranking report (564 lines)
├── upload_to_s3.py          # S3 upload helper (54 lines)
├── test_s3_uploads.py       # the only test file
├── run_scrapers.sh          # orchestration: scrape → upload → cleanup
├── crontab                  # daily 09:00 cron entry
├── Dockerfile               # cron + Playwright Chromium image
├── docker-compose.yml
├── pyproject.toml / uv.lock / requirements.txt
├── .env.example
├── README.md / LICENSE / .gitignore
└── (timestamped CSV/JSON outputs land here at runtime)
```

### Problems

1. **Massive duplication between the two scrapers.** `daft_scraper.py` and
   `daft_rent_scraper.py` contain near-identical copies of `_detect_platform`,
   `_ensure_browser`, `_extract_json_ld_objects`, `_extract_next_data`,
   `_find_value_by_key`, `_normalize_key`, `_safe_str`, `_extract_address_from_ld`,
   browser lifecycle (`close`/`__enter__`/`__exit__`), and `main()` boilerplate
   (logging setup, arg parsing, delay loop, write loop). A fix or anti-bot tweak
   has to be made in two places.
2. **No package boundary.** Scripts import each other by bare module name
   (`from upload_to_s3 import upload_file`), which only works because everything
   is in root and on `sys.path`. This is fragile and blocks moving files.
3. **Source, tests, config, docs, and runtime outputs all share one directory.**
   Generated `daft_listings_*.csv/json`, `rent_cork_city_*.json`, and
   `debug_view.png` are written into the project root, mixing artifacts with
   source.
4. **Tests aren't isolated.** One `test_*.py` in root; no `tests/` dir, no
   separation of unit vs. integration (the S3 integration tests hit real AWS).
5. **`requirements.txt` and `pyproject.toml` can drift.** `boto3` is installed
   ad-hoc in the Dockerfile (`pip install ... boto3`) and is not declared in
   either dependency file.
6. **`docs/` referenced but absent.** This file is the first occupant.

## Proposed structure

Adopt a `src/` package layout with a shared core module that both scrapers
build on:

```
python-daft-analyser/
├── src/
│   └── daft_analyser/
│       ├── __init__.py
│       ├── scrapers/
│       │   ├── __init__.py
│       │   ├── base.py          # BaseDaftScraper: browser lifecycle,
│       │   │                    #   _detect_platform, fetch_html, stealth,
│       │   │                    #   cookie dismissal, human behavior
│       │   ├── extract.py       # shared parsing: JSON-LD, __NEXT_DATA__,
│       │   │                    #   _find_value_by_key, _normalize_key,
│       │   │                    #   _safe_str/_safe_int, address-from-LD
│       │   ├── sale.py          # DaftScraper + ListingRecord (sale-specific)
│       │   └── rent.py          # DaftRentScraper + RentListingRecord
│       ├── scoring/
│       │   ├── __init__.py
│       │   ├── models.py        # SaleListing, ScoredListing, RentComparable
│       │   ├── finance.py       # mortgage/TMC/NVS/green-mortgage calcs
│       │   ├── scoring.py       # freshness/staleness/location/phase scoring
│       │   └── report.py        # load CSV/JSON, print_report, export_json
│       ├── storage/
│       │   ├── __init__.py
│       │   └── s3.py            # upload_file (was upload_to_s3.py)
│       └── io/
│           ├── __init__.py
│           └── writers.py       # shared write_csv / write_json
│
├── cli/  (or console_scripts entry points in pyproject.toml)
│   ├── scrape_sales.py          # thin wrappers around the package main()s
│   ├── scrape_rentals.py
│   ├── score.py
│   └── upload.py
│
├── tests/
│   ├── unit/
│   │   ├── test_extract.py      # _find_value_by_key, parsers, finance math
│   │   ├── test_scoring.py
│   │   └── test_upload.py       # the existing TestUploadFileUnit class
│   ├── integration/
│   │   └── test_s3_uploads.py   # the real-S3 tests (marked, opt-in)
│   ├── fixtures/                # saved HTML/JSON samples for offline parser tests
│   └── conftest.py
│
├── scripts/
│   └── run_scrapers.sh          # orchestration script
│
├── deploy/
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── crontab
│
├── data/                        # gitignored runtime outputs (CSV/JSON/screenshots)
│   └── .gitkeep
│
├── docs/
│   └── folder_structure_todo.md
│
├── pyproject.toml               # single source of dependency truth
├── uv.lock
├── .env.example
├── README.md
├── LICENSE
└── .gitignore
```

## Migration steps (incremental, lowest-risk first)

These are ordered so each step is independently shippable and testable.

- [ ] **1. Add `data/` for runtime outputs.** Make the scrapers write to a
  configurable output dir (default `data/`) instead of the repo root; same for
  `debug_view.png`. Add `data/` to `.gitignore`. Update `run_scrapers.sh`
  glob paths accordingly. Lowest-risk, immediate cleanup.

- [ ] **2. Declare `boto3` as a real dependency** in `pyproject.toml` (and
  `requirements.txt` if kept) and drop the ad-hoc `pip install ... boto3` from
  the Dockerfile. Consider an optional `[project.optional-dependencies]` group
  (`upload`, `scoring`) so the scraper image stays lean.

- [ ] **3. Create `tests/` with `unit/` and `integration/`.** Move
  `test_s3_uploads.py`'s `TestUploadFileUnit` into `tests/unit/` and the
  S3-hitting classes into `tests/integration/`. Register an `integration`
  pytest marker so CI can run `pytest -m "not integration"` by default.

- [ ] **4. Introduce the `daft_analyser` package under `src/`.** Start by moving
  `upload_to_s3.py` → `src/daft_analyser/storage/s3.py` (smallest, self-contained)
  and updating the test import. Add `[tool.setuptools]`/`[tool.hatch]` packaging
  config or `[tool.uv]` so `src/` is importable.

- [ ] **5. Extract the shared scraper core** into `scrapers/base.py` and
  `scrapers/extract.py`, then refactor both scrapers to subclass/import it. This
  is the highest-value change — it eliminates ~300 lines of duplication. Guard it
  with new offline parser tests (step 3's fixtures) so behavior is preserved.

- [ ] **6. Split `scoring_report.py`** into `scoring/{models,finance,scoring,report}.py`.
  It's already cleanly sectioned by comment banners, so this is mostly mechanical.

- [ ] **7. Add thin CLI entry points** (or `[project.scripts]` console_scripts in
  `pyproject.toml`, e.g. `daft-scrape-sales = "daft_analyser.scrapers.sale:main"`).
  Update `run_scrapers.sh` and the Dockerfile `COPY` lines to match the new paths.

- [ ] **8. Move deployment files** into `deploy/` and the orchestration script into
  `scripts/`. Update `docker-compose.yml` `build:` context and Dockerfile `COPY`
  paths.

## Notes / decisions to confirm

- **`src/` layout vs. flat package.** `src/` prevents accidental imports of the
  un-installed package during tests and is the modern default; if you prefer
  simplicity, a top-level `daft_analyser/` package (no `src/`) is also fine and
  needs less packaging config.
- **CLI wrappers vs. console_scripts.** `[project.scripts]` is cleaner and gives
  real commands on `PATH` after `uv sync`, but requires the package to be
  installed (it is, with `uv`). Keep `main()` functions importable either way.
- **Keep `requirements.txt`?** With `uv`/`pyproject.toml` + `uv.lock` as the
  source of truth, `requirements.txt` is redundant. Either delete it or generate
  it from the lock (`uv export`) so it can't drift. The Dockerfile currently uses
  `requirements.txt`; switching it to `uv sync` would unify the toolchain.
- The two scrapers have small intentional differences (sale uses extra Chromium
  flags + a `get_listing_urls_from_search` that uses Playwright locators with a
  BeautifulSoup fallback; rent is HTML-only). Preserve these as overrides in the
  subclasses rather than flattening them away.
```