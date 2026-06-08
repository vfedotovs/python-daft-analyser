#!/bin/bash
set -e

cd /app

echo "=========================================="
echo "Scraper run started at $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# Run sale scraper
echo "[$(date '+%H:%M:%S')] Starting sale scraper..."
if daft-scrape-sales; then
    echo "[$(date '+%H:%M:%S')] Sale scraper completed successfully"
else
    echo "[$(date '+%H:%M:%S')] Sale scraper FAILED"
fi

# Run rent scraper (30 listings)
echo "[$(date '+%H:%M:%S')] Starting rent scraper..."
if daft-scrape-rentals --max-listings 30; then
    echo "[$(date '+%H:%M:%S')] Rent scraper completed successfully"
else
    echo "[$(date '+%H:%M:%S')] Rent scraper FAILED"
fi

# Upload sale files to S3
echo "[$(date '+%H:%M:%S')] Uploading sale files to S3..."
for f in data/daft_listings_*.csv data/daft_listings_*.json; do
    [ -e "$f" ] || continue
    if daft-upload "$f" sale/; then
        echo "[$(date '+%H:%M:%S')] Uploaded $f -> s3://$S3_BUCKET/sale/$(basename "$f")"
        rm "$f"
    else
        echo "[$(date '+%H:%M:%S')] FAILED to upload $f"
    fi
done

# Upload rent files to S3
echo "[$(date '+%H:%M:%S')] Uploading rent files to S3..."
for f in data/rent_cork_city_*.json; do
    [ -e "$f" ] || continue
    if daft-upload "$f" rent/; then
        echo "[$(date '+%H:%M:%S')] Uploaded $f -> s3://$S3_BUCKET/rent/$(basename "$f")"
        rm "$f"
    else
        echo "[$(date '+%H:%M:%S')] FAILED to upload $f"
    fi
done

echo "[$(date '+%H:%M:%S')] Scraper run finished"
echo ""
