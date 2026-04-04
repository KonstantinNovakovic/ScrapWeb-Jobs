from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass
class JobListing:
    site: str
    title: str
    company: str
    location: str
    link: str
    date_posted: str

    def unique_id(self) -> str:
        return f'{self.site}:{self.link.strip()}'


class ScraperError(Exception):
    pass


class BaseScraper:
    site_name = ''

    def scrape(self) -> list[JobListing]:
        raise NotImplementedError


class InfostudScraper(BaseScraper):
    site_name = 'infostud'
    base_url = 'https://poslovi.infostud.com'
    search_url = 'https://poslovi.infostud.com/oglasi-za-posao'

    def __init__(self, delay_seconds: float = 2.0, timeout: int = 20) -> None:
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                'User-Agent': 'ScrapWebJobsBot/1.0 (+local personal use; low-frequency scraping)',
            }
        )

    def scrape(self) -> list[JobListing]:
        # 1) try discover RSS feed
        rss_url = self._discover_rss_url()
        if rss_url:
            logger.info('Infostud RSS discovered: %s', rss_url)
            try:
                return self._scrape_rss(rss_url)
            except ScraperError as exc:
                logger.warning('RSS parse failed, fallback to HTML: %s', exc)

        # 2) fallback HTML
        return self._scrape_html()

    def _discover_rss_url(self) -> str | None:
        try:
            r = self.session.get(self.base_url, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            logger.warning('RSS discovery skipped (homepage unavailable): %s', exc)
            return None

        soup = BeautifulSoup(r.text, 'html.parser')
        for tag in soup.select('link[rel="alternate"]'):
            href = tag.get('href', '').strip()
            typ = (tag.get('type') or '').lower()
            if href and ('rss' in typ or href.endswith('.xml')):
                return urljoin(self.base_url, href)

        time.sleep(self.delay_seconds)
        for path in ('/rss', '/feed', '/rss.xml', '/oglasi-za-posao/rss'):
            candidate = urljoin(self.base_url, path)
            try:
                c = self.session.get(candidate, timeout=self.timeout)
            except requests.RequestException:
                continue
            if c.ok and 'xml' in c.headers.get('Content-Type', '').lower():
                return candidate
        return None

    def _scrape_rss(self, rss_url: str) -> list[JobListing]:
        try:
            r = self.session.get(rss_url, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise ScraperError(f'Failed RSS request: {exc}') from exc

        soup = BeautifulSoup(r.text, 'xml')
        items = soup.find_all('item')
        if not items:
            raise ScraperError('No <item> in RSS feed.')

        jobs: list[JobListing] = []
        for item in items:
            title = (item.findtext('title') or '').strip()
            link = (item.findtext('link') or '').strip()
            date_posted = (item.findtext('pubDate') or '').strip() or datetime.utcnow().isoformat()
            if not title or not link:
                continue
            jobs.append(
                JobListing(
                    site=self.site_name,
                    title=title,
                    company='Nepoznato',
                    location='Nepoznato',
                    link=link,
                    date_posted=date_posted,
                )
            )
        return jobs

    def _scrape_html(self) -> list[JobListing]:
        try:
            r = self.session.get(self.search_url, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            raise ScraperError(f'Failed to fetch listings page: {exc}') from exc

        soup = BeautifulSoup(r.text, 'html.parser')
        cards = soup.select('article') or soup.select('.job') or soup.select('.job-list-item')

        jobs: list[JobListing] = []
        for card in cards:
            parsed = self._parse_card(card)
            if parsed:
                jobs.append(parsed)

        if not jobs:
            jobs = self._parse_json_ld(soup)

        if not jobs:
            raise ScraperError(
                'No job listings parsed from HTML. Site structure changed or anti-bot protection active.'
            )

        return jobs

    def _parse_card(self, card: Any) -> JobListing | None:
        link_el = card.select_one('a[href*="/posao/"]') or card.select_one('a[href]')
        if not link_el:
            return None

        title = (link_el.get_text(' ', strip=True) or '').strip()
        href = (link_el.get('href') or '').strip()
        if not title or not href:
            return None

        company_el = card.select_one('.company') or card.select_one("[class*='company']")
        location_el = card.select_one('.location') or card.select_one("[class*='location']")
        date_el = card.select_one('time') or card.select_one("[class*='date']")

        return JobListing(
            site=self.site_name,
            title=title,
            company=company_el.get_text(' ', strip=True) if company_el else 'Nepoznato',
            location=location_el.get_text(' ', strip=True) if location_el else 'Nepoznato',
            link=urljoin(self.base_url, href),
            date_posted=date_el.get_text(' ', strip=True) if date_el else datetime.utcnow().isoformat(),
        )

    def _parse_json_ld(self, soup: BeautifulSoup) -> list[JobListing]:
        jobs: list[JobListing] = []
        for tag in soup.select('script[type="application/ld+json"]'):
            raw = (tag.string or '').strip()
            if 'JobPosting' not in raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:
                continue

            items: list[dict[str, Any]]
            if isinstance(payload, list):
                items = [x for x in payload if isinstance(x, dict)]
            elif isinstance(payload, dict):
                items = [payload]
            else:
                items = []

            for item in items:
                if item.get('@type') != 'JobPosting':
                    continue
                title = str(item.get('title', '')).strip()
                link = str(item.get('url', '')).strip()
                if not title or not link:
                    continue

                company = 'Nepoznato'
                org = item.get('hiringOrganization')
                if isinstance(org, dict):
                    company = str(org.get('name', '')).strip() or company

                location = 'Nepoznato'
                loc = item.get('jobLocation')
                if isinstance(loc, dict):
                    addr = loc.get('address')
                    if isinstance(addr, dict):
                        location = str(addr.get('addressLocality', '')).strip() or location

                date_posted = str(item.get('datePosted', '')).strip() or datetime.utcnow().isoformat()

                jobs.append(
                    JobListing(
                        site=self.site_name,
                        title=title,
                        company=company,
                        location=location,
                        link=urljoin(self.base_url, link),
                        date_posted=date_posted,
                    )
                )
        return jobs
