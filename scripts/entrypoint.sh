#!/bin/bash
# Container entrypoint: surface scraper activity on stdout so it can be
# followed with `docker logs -f`, then keep running for the daily cron job.
set -u

LOG=/var/log/cron.log
log() { echo "[entrypoint $(date '+%H:%M:%S')] $*"; }

log "daft-scraper container starting"
log "timezone=${TZ:-unset} log_level=${LOG_LEVEL:-INFO}"

# Start the cron daemon for the scheduled daily run.
cron
log "cron started; schedule:"
crontab -l | sed 's/^/[entrypoint]   /'

# Run the scrapers once immediately, streaming output to BOTH the container
# log (stdout, captured by `docker logs`) and the file that cron appends to.
log "running initial scrape now (this can take several minutes)..."
/app/run_scrapers.sh 2>&1 | tee -a "$LOG"
log "initial scrape finished"

# Keep the container alive and surface output from future cron-triggered runs.
log "idle — waiting for the next scheduled run; following $LOG"
tail -f "$LOG"
