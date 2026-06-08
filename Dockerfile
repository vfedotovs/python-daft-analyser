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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

# Install the daft_analyser package — provides the daft-scrape-sales /
# daft-scrape-rentals / daft-upload console scripts used by run_scrapers.sh
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir --no-deps .

COPY run_scrapers.sh .
COPY crontab /etc/cron.d/scraper-cron

RUN chmod +x /app/run_scrapers.sh \
    && chmod 0644 /etc/cron.d/scraper-cron \
    && crontab /etc/cron.d/scraper-cron \
    && touch /var/log/cron.log

CMD /app/run_scrapers.sh >> /var/log/cron.log 2>&1 && cron && tail -f /var/log/cron.log
