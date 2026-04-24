from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

from src.filter import filter_jobs
from src.notifier import format_jobs_message, send_telegram_message
from src.scraper import (
    BaseScraper,
    HelloWorldScraper,
    InfostudScraper,
    JobListing,
    JobicyScraper,
    JobertyScraper,
    JoobleScraper,
    ScraperError,
)
from src.storage import load_seen, save_seen

CONFIG_PATH = Path('config.json')


def _normalize_string_list(value: object, key: str) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return [item.strip() for item in value if item.strip()]
    raise ValueError(f"Config key '{key}' must be a string or list of strings.")


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError('config.json not found. Copy config.example.json and fill values.')
    cfg = json.loads(path.read_text(encoding='utf-8'))
    required = ['keywords', 'location', 'sites', 'telegram_token', 'chat_id']
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"Missing config keys: {', '.join(missing)}")
    cfg['keywords'] = _normalize_string_list(cfg.get('keywords', []), 'keywords')
    cfg['exclude_keywords'] = _normalize_string_list(
        cfg.get('exclude_keywords', []), 'exclude_keywords'
    )
    cfg['location'] = _normalize_string_list(cfg.get('location', []), 'location')
    cfg['sites'] = _normalize_string_list(cfg.get('sites', []), 'sites')
    if 'jooble_api_key' in cfg and not isinstance(cfg['jooble_api_key'], str):
        raise ValueError("Config key 'jooble_api_key' must be a string.")
    return cfg


def scrape_sites(sites: list[str], keywords: list[str], jooble_api_key: str | None = None) -> list[JobListing]:
    scraper_map = {
        'infostud': InfostudScraper,
        'helloworld': HelloWorldScraper,
        'jooble': JoobleScraper,
        'jobicy': JobicyScraper,
        'joberty': JobertyScraper,
    }
    jobs: list[JobListing] = []
    supported_sites: list[tuple[str, type[BaseScraper]]] = []

    for site in sites:
        scraper_cls = scraper_map.get(site.lower())
        if scraper_cls is None:
            logging.warning("Unsupported site '%s'.", site)
            continue
        supported_sites.append((site, scraper_cls))

    for index, (site, scraper_cls) in enumerate(supported_sites):
        site_key = site.lower()
        scraper_keywords = keywords if site_key in {'infostud', 'helloworld', 'jooble', 'jobicy'} else None
        scraper_api_key = jooble_api_key if site_key == 'jooble' else None
        scraper = scraper_cls(keywords=scraper_keywords, api_key=scraper_api_key)
        try:
            site_jobs = scraper.scrape()
            jobs.extend(site_jobs)
            logging.info('Scraped %d jobs from %s', len(site_jobs), site)
        except ScraperError as exc:
            logging.warning('Scraping failed for %s: %s', site, exc)
        except Exception as exc:
            logging.warning('Unexpected scraping failure for %s: %s', site, exc)
        if index < len(supported_sites) - 1:
            time.sleep(2.0)
    return jobs


def main() -> int:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        config = load_config()
    except Exception as exc:
        logging.error('Config error: %s', exc)
        return 1

    scraped = scrape_sites(
        config['sites'],
        config.get('keywords', []),
        config.get('jooble_api_key'),
    )
    matched = filter_jobs(
        scraped,
        config.get('keywords', []),
        config.get('location', []),
        config.get('exclude_keywords', []),
    )
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
