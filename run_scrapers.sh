#!/bin/bash
set -e

cd /app

echo "=========================================="
echo "Scraper run started at $(date '+%Y-%m-%d %H:%M:%S')"
echo "=========================================="

# Run sale scraper
echo "[$(date '+%H:%M:%S')] Starting sale scraper..."
if python3 daft_scraper.py; then
    echo "[$(date '+%H:%M:%S')] Sale scraper completed successfully"
else
    echo "[$(date '+%H:%M:%S')] Sale scraper FAILED"
fi

# Run rent scraper (30 listings)
echo "[$(date '+%H:%M:%S')] Starting rent scraper..."
if python3 daft_rent_scraper.py --max-listings 30; then
    echo "[$(date '+%H:%M:%S')] Rent scraper completed successfully"
else
    echo "[$(date '+%H:%M:%S')] Rent scraper FAILED"
fi

# Upload sale files to S3
echo "[$(date '+%H:%M:%S')] Uploading sale files to S3..."
for f in daft_listings_*.csv daft_listings_*.json; do
    [ -e "$f" ] || continue
    if python3 upload_to_s3.py "$f" sale/; then
        echo "[$(date '+%H:%M:%S')] Uploaded $f -> s3://$S3_BUCKET/sale/$f"
        rm "$f"
    else
        echo "[$(date '+%H:%M:%S')] FAILED to upload $f"
    fi
done

# Upload rent files to S3
echo "[$(date '+%H:%M:%S')] Uploading rent files to S3..."
for f in rent_cork_city_*.json; do
    [ -e "$f" ] || continue
    if python3 upload_to_s3.py "$f" rent/; then
        echo "[$(date '+%H:%M:%S')] Uploaded $f -> s3://$S3_BUCKET/rent/$f"
        rm "$f"
    else
        echo "[$(date '+%H:%M:%S')] FAILED to upload $f"
    fi
done

echo "[$(date '+%H:%M:%S')] Scraper run finished"
echo ""
