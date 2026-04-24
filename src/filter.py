from __future__ import annotations

import logging
import unicodedata
from typing import Iterable

from .scraper import JobListing

logger = logging.getLogger(__name__)


def _normalize_location_text(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', value.lower())
    ascii_only = ''.join(ch for ch in normalized if not unicodedata.combining(ch))
    return ascii_only.replace('rad od kuce', 'remote')


def filter_jobs(
    jobs: Iterable[JobListing],
    keywords: list[str],
    locations: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
) -> list[JobListing]:
    normalized_keywords = [kw.strip().lower() for kw in keywords if kw.strip()]
    normalized_exclude_keywords = [
        kw.strip().lower() for kw in (exclude_keywords or []) if kw.strip()
    ]
    normalized_locations = [
        _normalize_location_text(location.strip()) for location in (locations or []) if location.strip()
    ]

    matched: list[JobListing] = []
    for job in jobs:
        text = f'{job.title} {job.company} {job.location}'.lower()
        normalized_job_location = _normalize_location_text(job.location)
        exclude_match = next((kw for kw in normalized_exclude_keywords if kw in text), None)

        if exclude_match is not None:
            logger.info(
                "Skipping job '%s' at '%s' because exclude keyword matched: %s",
                job.title,
                job.company,
                exclude_match,
            )
            continue

        keyword_ok = True if not normalized_keywords else any(kw in text for kw in normalized_keywords)
        location_ok = (
            True
            if not normalized_locations
            else any(location in normalized_job_location for location in normalized_locations)
        )

        if keyword_ok and location_ok:
            matched.append(job)

    return matched
