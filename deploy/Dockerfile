# Build from the repository root, e.g.:
#   docker build -f deploy/Dockerfile -t daft-scraper .
# (docker-compose.yml sets context: .. and dockerfile: deploy/Dockerfile.)
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Europe/London

RUN apt-get update && apt-get install -y --no-install-recommends \
    cron \
    tzdata \
    # Playwright Chromium dependencies
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libatspi2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2 \
    libdbus-1-3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uv is the single dependency toolchain; uv.lock is the source of truth.
RUN pip install --no-cache-dir uv

# Install locked dependencies (incl. the `upload` extra) then the package
# itself into the system interpreter, so the daft-* console scripts land on
# the default PATH used by cron. Splitting deps from the project keeps the
# Docker layer cache warm across source-only changes.
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv export --frozen --no-emit-project --extra upload --no-hashes -o /tmp/requirements.txt \
    && uv pip install --system --no-cache -r /tmp/requirements.txt \
    && uv pip install --system --no-cache --no-deps .
RUN playwright install --with-deps chromium

COPY scripts/run_scrapers.sh ./run_scrapers.sh
COPY deploy/crontab /etc/cron.d/scraper-cron

RUN chmod +x /app/run_scrapers.sh \
    && chmod 0644 /etc/cron.d/scraper-cron \
    && crontab /etc/cron.d/scraper-cron \
    && touch /var/log/cron.log

CMD /app/run_scrapers.sh >> /var/log/cron.log 2>&1 && cron && tail -f /var/log/cron.log
