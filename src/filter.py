from __future__ import annotations

from typing import Iterable

from .scraper import JobListing


def filter_jobs(jobs: Iterable[JobListing], keywords: list[str], location: str | None = None) -> list[JobListing]:
    normalized_keywords = [kw.strip().lower() for kw in keywords if kw.strip()]
    normalized_location = (location or '').strip().lower()

    matched: list[JobListing] = []
    for job in jobs:
        text = f'{job.title} {job.company} {job.location}'.lower()

        keyword_ok = True if not normalized_keywords else any(kw in text for kw in normalized_keywords)
        location_ok = True if not normalized_location else normalized_location in job.location.lower()

        if keyword_ok and location_ok:
            matched.append(job)

    return matched
