from __future__ import annotations

from typing import Iterable

import requests

from .scraper import JobListing


def format_jobs_message(jobs: Iterable[JobListing]) -> str:
    jobs_list = list(jobs)
    lines = [f'🆕 {len(jobs_list)} nova oglasa', '']

    for job in jobs_list:
        lines.extend(
            [
                f'📌 {job.title} — {job.company}',
                f'📍 {job.location}',
                f'🔗 {job.link}',
                '',
            ]
        )

    return '\n'.join(lines).strip()


def send_telegram_message(token: str, chat_id: str, text: str, timeout: int = 20) -> None:
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    r = requests.post(
        url,
        json={
            'chat_id': chat_id,
            'text': text,
            'disable_web_page_preview': True,
        },
        timeout=timeout,
    )
    r.raise_for_status()
