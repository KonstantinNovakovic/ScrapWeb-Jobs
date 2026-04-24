from __future__ import annotations

import time
from typing import Iterable

import requests

from .scraper import JobListing

TELEGRAM_MAX_MESSAGE_LENGTH = 4096


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


def _split_telegram_message(text: str, max_length: int = TELEGRAM_MAX_MESSAGE_LENGTH) -> list[str]:
    if len(text) <= max_length:
        return [text]

    blocks = text.split('\n\n')
    if not blocks:
        return [text]

    header = blocks[0].strip()
    job_blocks = [block.strip() for block in blocks[1:] if block.strip()]
    chunks: list[str] = []
    current_parts: list[str] = [header]

    for job_block in job_blocks:
        candidate_parts = current_parts + [job_block]
        candidate_text = '\n\n'.join(part for part in candidate_parts if part).strip()

        if len(candidate_text) <= max_length:
            current_parts = candidate_parts
            continue

        current_text = '\n\n'.join(part for part in current_parts if part).strip()
        if current_text:
            chunks.append(current_text)

        if len(job_block) > max_length:
            raise ValueError('A single job listing exceeds Telegram message size limit.')

        current_parts = [job_block]

    final_text = '\n\n'.join(part for part in current_parts if part).strip()
    if final_text:
        chunks.append(final_text)

    return chunks


def send_telegram_message(
    token: str,
    chat_id: str,
    text: str,
    timeout: int = 20,
    delay_seconds: float = 1.0,
) -> None:
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    chunks = _split_telegram_message(text)

    for index, chunk in enumerate(chunks):
        r = requests.post(
            url,
            json={
                'chat_id': chat_id,
                'text': chunk,
                'disable_web_page_preview': True,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        if index < len(chunks) - 1:
            time.sleep(delay_seconds)
