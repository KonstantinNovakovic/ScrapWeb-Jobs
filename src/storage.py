from __future__ import annotations

import json
from pathlib import Path

DEFAULT_SEEN_FILE = Path('seen_jobs.json')


def load_seen(path: Path = DEFAULT_SEEN_FILE) -> set[str]:
    if not path.exists():
        return set()

    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError:
        return set()

    if not isinstance(data, list):
        return set()

    return {str(item) for item in data}


def save_seen(seen_ids: set[str], path: Path = DEFAULT_SEEN_FILE) -> None:
    path.write_text(json.dumps(sorted(seen_ids), ensure_ascii=False, indent=2), encoding='utf-8')
