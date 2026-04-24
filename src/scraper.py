from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urljoin

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
    base_url = ''
    search_url = ''

    def __init__(
        self,
        keywords: list[str] | None = None,
        delay_seconds: float = 2.0,
        timeout: int = 20,
        api_key: str | None = None,
    ) -> None:
        self.keywords = [keyword.strip() for keyword in (keywords or []) if keyword.strip()]
        self.api_key = (api_key or '').strip()
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                'User-Agent': (
                    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
                ),
            }
        )

    def scrape(self) -> list[JobListing]:
        raise NotImplementedError

    def _fetch_search_page(self, url: str | None = None) -> BeautifulSoup:
        try:
            response = self.session.get(url or self.search_url, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ScraperError(f'Failed to fetch listings page: {exc}') from exc
        return BeautifulSoup(response.text, 'html.parser')

    def _build_search_url(self, keyword: str) -> str:
        return f'{self.search_url}?{urlencode({"q": keyword})}'

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
                if isinstance(loc, list):
                    loc = next((entry for entry in loc if isinstance(entry, dict)), None)
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


class InfostudScraper(BaseScraper):
    site_name = 'infostud'
    base_url = 'https://poslovi.infostud.com'
    search_url = 'https://poslovi.infostud.com/oglasi-za-posao'

    def scrape(self) -> list[JobListing]:
        jobs_by_link: dict[str, JobListing] = {}
        search_urls = self._search_urls()

        for index, search_url in enumerate(search_urls):
            try:
                site_jobs = self._scrape_html(search_url)
                for job in site_jobs:
                    jobs_by_link[job.link] = job
            except ScraperError as exc:
                logger.warning('Infostud search failed for %s: %s', search_url, exc)

            if index < len(search_urls) - 1:
                time.sleep(self.delay_seconds)

        return list(jobs_by_link.values())

    def _search_urls(self) -> list[str]:
        if not self.keywords:
            return [self.search_url]
        return [self._build_search_url(keyword) for keyword in self.keywords]

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

    def _scrape_html(self, search_url: str) -> list[JobListing]:
        soup = self._fetch_search_page(search_url)
        cards = soup.select('div.search-job-card')

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
        title_el = card.select_one('h2[id*="job-card-title"]')
        link_el = card.select_one('a[href*="/posao/"]')
        title = title_el.get_text(' ', strip=True) if title_el else ''
        href = (link_el.get('href') or '').strip() if link_el else ''
        if not title or not href:
            return None

        company_el = card.select_one(
            "p:has(svg[class*='tabler-icon-building-factory-2']) span"
        )
        location_el = card.select_one("p:has(svg[class*='tabler-icon-map-pin']) span")
        date_el = card.select_one("p:has(svg[class*='tabler-icon-clock-hour-3']) span")

        return JobListing(
            site=self.site_name,
            title=title,
            company=company_el.get_text(' ', strip=True) if company_el else 'Nepoznato',
            location=location_el.get_text(' ', strip=True) if location_el else 'Nepoznato',
            link=urljoin(self.base_url, href),
            date_posted=date_el.get_text(' ', strip=True) if date_el else datetime.utcnow().isoformat(),
        )


class HelloWorldScraper(BaseScraper):
    site_name = 'helloworld'
    base_url = 'https://www.helloworld.rs'
    search_url = 'https://www.helloworld.rs/oglasi-za-posao/'

    def scrape(self) -> list[JobListing]:
        jobs_by_link: dict[str, JobListing] = {}
        search_urls = self._search_urls()

        for index, search_url in enumerate(search_urls):
            try:
                soup = self._fetch_search_page(search_url)
                site_jobs = self._scrape_html(soup)
                if not site_jobs:
                    site_jobs = self._parse_json_ld(soup)
                for job in site_jobs:
                    jobs_by_link[job.link] = job
            except ScraperError as exc:
                logger.warning('HelloWorld search failed for %s: %s', search_url, exc)

            if index < len(search_urls) - 1:
                time.sleep(self.delay_seconds)

        if not jobs_by_link:
            logger.warning('HelloWorld returned no parseable job listings.')
        return list(jobs_by_link.values())

    def _search_urls(self) -> list[str]:
        if not self.keywords:
            return [self.search_url]
        return [self._build_search_url(keyword) for keyword in self.keywords]

    def _scrape_html(self, soup: BeautifulSoup) -> list[JobListing]:
        jobs: list[JobListing] = []
        seen_links: set[str] = set()

        for link_el in soup.select('a.__ga4_job_title[href*="/posao/"]'):
            parsed = self._parse_card(link_el)
            if not parsed or parsed.link in seen_links:
                continue
            seen_links.add(parsed.link)
            jobs.append(parsed)

        return jobs

    def _parse_card(self, title_link: Any) -> JobListing | None:
        title = title_link.get_text(' ', strip=True)
        href = (title_link.get('href') or '').strip()
        if not title or not href:
            return None

        card = title_link.find_parent(
            'div', class_=lambda value: value and 'shadow-md' in value and 'rounded-lg' in value
        )
        if card is None:
            card = title_link.parent

        company_el = card.select_one('h4 a') if card else None
        location_el = self._find_text_after_icon(card, 'i.la-map-marker') if card else None
        date_el = self._find_text_after_icon(card, 'i.la-clock') if card else None

        return JobListing(
            site=self.site_name,
            title=title,
            company=company_el.get_text(' ', strip=True) if company_el else 'Nepoznato',
            location=location_el or 'Nepoznato',
            link=urljoin(self.base_url, href),
            date_posted=date_el or datetime.utcnow().isoformat(),
        )

    def _find_text_after_icon(self, card: Any, icon_selector: str) -> str | None:
        icon = card.select_one(icon_selector) if card else None
        if icon is None:
            return None
        container = icon.find_parent(['div', 'p'])
        if container is None:
            return None
        text_el = container.find('p')
        if text_el is None:
            return None
        return text_el.get_text(' ', strip=True) or None


class JoobleScraper(BaseScraper):
    site_name = 'jooble'
    base_url = 'https://jooble.org'
    search_url = 'https://jooble.org/api'

    def scrape(self) -> list[JobListing]:
        if not self.api_key:
            logger.warning('Jooble API key missing. Skipping.')
            return []

        jobs_by_link: dict[str, JobListing] = {}
        keywords = self.keywords or ['']

        for index, keyword in enumerate(keywords):
            try:
                for job in self._fetch_keyword_jobs(keyword):
                    jobs_by_link[job.link] = job
            except ScraperError as exc:
                logger.warning('Jooble API request failed for %r: %s', keyword, exc)

            if index < len(keywords) - 1:
                time.sleep(1.0)

        return list(jobs_by_link.values())

    def _fetch_keyword_jobs(self, keyword: str) -> list[JobListing]:
        try:
            response = self.session.post(
                f'{self.search_url}/{self.api_key}',
                json={
                    'keywords': keyword,
                    'location': 'Belgrade, Serbia',
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException as exc:
            raise ScraperError(f'Jooble API request failed: {exc}') from exc
        except ValueError as exc:
            raise ScraperError(f'Jooble API returned invalid JSON: {exc}') from exc

        jobs: list[JobListing] = []
        for item in payload.get('jobs', []):
            if not isinstance(item, dict):
                continue
            title = str(item.get('title', '')).strip()
            link = str(item.get('link', '')).strip()
            if not title or not link:
                continue
            jobs.append(
                JobListing(
                    site=self.site_name,
                    title=title,
                    company=str(item.get('company', '')).strip() or 'Nepoznato',
                    location=str(item.get('location', '')).strip() or 'Nepoznato',
                    link=link,
                    date_posted=str(item.get('updated', '')).strip() or datetime.utcnow().isoformat(),
                )
            )
        return jobs


class JobicyScraper(BaseScraper):
    site_name = 'jobicy'
    base_url = 'https://jobicy.com'
    search_url = 'https://jobicy.com/api/v2/remote-jobs'

    def scrape(self) -> list[JobListing]:
        jobs_by_link: dict[str, JobListing] = {}
        keywords = self.keywords or ['']

        for index, keyword in enumerate(keywords):
            try:
                for job in self._fetch_keyword_jobs(keyword):
                    jobs_by_link[job.link] = job
            except ScraperError as exc:
                logger.warning('Jobicy API request failed for %r: %s', keyword, exc)

            if index < len(keywords) - 1:
                time.sleep(5.0)

        return list(jobs_by_link.values())

    def _fetch_keyword_jobs(self, keyword: str) -> list[JobListing]:
        try:
            response = self._request_keyword_jobs(keyword)
            payload = response.json()
        except requests.RequestException as exc:
            raise ScraperError(f'Jobicy API request failed: {exc}') from exc
        except ValueError as exc:
            raise ScraperError(f'Jobicy API returned invalid JSON: {exc}') from exc

        jobs: list[JobListing] = []
        for item in payload.get('jobs', []):
            if not isinstance(item, dict):
                continue
            title = str(item.get('jobTitle', '')).strip()
            link = str(item.get('url', '')).strip()
            if not title or not link:
                continue
            jobs.append(
                JobListing(
                    site=self.site_name,
                    title=title,
                    company=str(item.get('companyName', '')).strip() or 'Nepoznato',
                    location=str(item.get('jobGeo', '')).strip() or 'Remote',
                    link=link,
                    date_posted=str(item.get('pubDate', '')).strip() or datetime.utcnow().isoformat(),
                )
            )
        return jobs

    def _request_keyword_jobs(self, keyword: str) -> requests.Response:
        params = {
            'count': 50,
            'geo': 'serbia',
            'tag': keyword,
        }
        response = self.session.get(self.search_url, params=params, timeout=self.timeout)
        if response.status_code == 429:
            time.sleep(10.0)
            response = self.session.get(self.search_url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response


class JobertyScraper(BaseScraper):
    site_name = 'joberty'
    base_url = 'https://www.joberty.com'
    search_url = 'https://www.joberty.com/sr/it-company'

    def scrape(self) -> list[JobListing]:
        try:
            soup = self._fetch_search_page()
            jobs = self._parse_json_ld(soup)
            if not jobs:
                logger.warning('Joberty returned a client-rendered page with no parseable job listings.')
            return jobs
        except ScraperError as exc:
            logger.warning('Joberty scraping failed: %s', exc)
            return []
