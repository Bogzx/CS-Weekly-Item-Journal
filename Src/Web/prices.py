"""The scheduled Steam price update.

The crawl runs Src/DB/bulk_scraper.py in a subprocess once a day, so a slow
or failing crawl never blocks a request and SQLite sees one writer at a time.
"""

import atexit
import json
import logging
import os
import subprocess
import sys

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from Src.Web.settings import BASE_DIR, repo_path

logger = logging.getLogger(__name__)

# Written to price_update_config.json on first run if it is missing. An empty
# 'collections' list means "every collection".
# 'drop_pool' limits the crawl to what the weekly drop offers (~9k market
# items, ~2.5 h); without it the job walked the whole ~35k-item market by
# name and stopped at max_items, which never reached most cases or graffiti.
DEFAULT_PRICE_UPDATE_CONFIG = {
    "collections": [],
    "drop_pool": True,
    "max_items": 10000,
    "batch_size": 100,
}

SCRAPER = os.path.join(BASE_DIR, 'Src', 'DB', 'bulk_scraper.py')


def scraper_command(config, db_path):
    """The bulk_scraper.py command line for a price_update_config.json."""
    cmd = [sys.executable, SCRAPER, '--db', os.path.abspath(db_path)]
    collections = config.get('collections', [])
    if collections:
        cmd.append('--collections')
        cmd.extend(collections)
    # Only crawl the categories the item database holds
    if config.get('drop_pool', True):
        cmd.append('--drop-pool')
    max_items = config.get('max_items', 100)
    if max_items:
        cmd.extend(['--max', str(max_items)])
    # Number of items to pull per Steam request
    batch_size = config.get('batch_size', 100)
    if batch_size:
        cmd.extend(['--batch-size', str(batch_size)])
    return cmd


def load_config(config_path):
    """Read the job's config, writing the defaults first if the file is missing.

    .gitignore used to ignore all *.json, so this file could never be
    committed and the job gave up on every install; the advertised daily
    price update never ran for anyone.
    """
    if not os.path.exists(config_path):
        logger.warning("Price update configuration not found at %s; writing defaults.", config_path)
        with open(config_path, 'w') as f:
            json.dump(DEFAULT_PRICE_UPDATE_CONFIG, f, indent=2)
    with open(config_path, 'r') as f:
        return json.load(f)


def update_prices_job(db_path):
    """Run one price crawl against `db_path` (the scheduler calls this daily).

    It used to invoke 'src/DB/update_price.py': wrong case for Linux and
    macOS (the directory is Src/), and a script that sleeps 15 s before every
    single item, over three days for one refresh. bulk_scraper.py fetches a
    page of items per request.
    """
    logger.info("Running scheduled price update job")
    try:
        config_path = repo_path(os.environ.get('PRICE_UPDATE_CONFIG', 'price_update_config.json'))
        try:
            config = load_config(config_path)
        except OSError:
            logger.exception("Could not read or write the price config at %s", config_path)
            return

        if not os.path.exists(SCRAPER):
            logger.error("Bulk scraper not found at %s", SCRAPER)
            return

        cmd = scraper_command(config, db_path)
        logger.info("Executing command: %s", ' '.join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=BASE_DIR)
        if result.returncode == 0:
            logger.info("Price update completed: %s", result.stdout)
        else:
            # The scraper reports progress on stdout; keep its tail so the log
            # shows where an interrupted crawl stopped, not just stderr.
            logger.error("Price update failed (exit %s): %s\n%s",
                         result.returncode, result.stderr, result.stdout[-2000:])
    except Exception:
        logger.exception("Error running price update job")


_scheduler = None


def init_scheduler(db_path):
    """Start the daily price update (00:00 UTC) in a background thread."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        logger.info("Shutting down existing scheduler...")
        _scheduler.shutdown(wait=False)

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        update_prices_job,
        args=[db_path],
        trigger=CronTrigger(hour=0, minute=0, timezone='UTC'),
        id='price_update_job',
        name='Daily price update',
        replace_existing=True
    )
    _scheduler.start()
    logger.info("Scheduler started, price updates will run daily at 00:00 UTC")
    atexit.register(shutdown_scheduler)


def shutdown_scheduler():
    """Safely shut down the scheduler."""
    if _scheduler is not None and _scheduler.running:
        logger.info("Shutting down scheduler...")
        try:
            _scheduler.shutdown(wait=False)
            logger.info("Scheduler successfully shut down")
        except Exception:
            logger.exception("Error shutting down scheduler")
