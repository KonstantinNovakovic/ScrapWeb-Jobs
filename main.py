from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from src.filter import filter_jobs
from src.notifier import format_jobs_message, send_telegram_message
from src.scraper import InfostudScraper, JobListing, ScraperError
from src.storage import load_seen, save_seen

CONFIG_PATH = Path('config.json')


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError('config.json not found. Copy config.example.json and fill values.')
    cfg = json.loads(path.read_text(encoding='utf-8'))
    required = ['keywords', 'location', 'sites', 'telegram_token', 'chat_id']
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")
    return cfg


def scrape_sites(sites: list[str]) -> list[JobListing]:
    jobs: list[JobListing] = []
    for site in sites:
        if site.lower() != 'infostud':
            logging.warning("Unsupported site '%s' (currently only infostud).", site)
            continue
        scraper = InfostudScraper()
        try:
            site_jobs = scraper.scrape()
            jobs.extend(site_jobs)
            logging.info('Scraped %d jobs from %s', len(site_jobs), site)
        except ScraperError as exc:
            logging.error('Scraping failed for %s: %s', site, exc)
    return jobs


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = load_config()
    except Exception as exc:
        logging.error('Config error: %s', exc)
        return 1

    scraped = scrape_sites(config['sites'])
    matched = filter_jobs(scraped, config.get('keywords', []), config.get('location', ''))
    seen = load_seen()
    new_jobs = [job for job in matched if job.unique_id() not in seen]

    if not new_jobs:
        logging.info('No new matching jobs. Silent run.')
        return 0

    message = format_jobs_message(new_jobs)
    try:
        send_telegram_message(config['telegram_token'], str(config['chat_id']), message)
    except Exception as exc:
        logging.error('Telegram send failed: %s', exc)
        return 1

    for job in new_jobs:
        seen.add(job.unique_id())
    save_seen(seen)
    logging.info('Sent %d new jobs and updated seen_jobs.json', len(new_jobs))
    return 0


if __name__ == '__main__':
    sys.exit(main())
