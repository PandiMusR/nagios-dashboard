from __future__ import annotations

import json
import os
from datetime import datetime

from services.config import CONFIG_DIR

HISTORY_DIR = f'{CONFIG_DIR}/stage_history'


def append_stage_history(host: str, container: str, from_stage: str, to_stage: str, user: str, note: str = '') -> None:
    """Append a stage change entry to the monthly JSONL file.

    Args:
        host: Hostname.
        container: Nagios container name.
        from_stage: Previous stage (e.g., 'new').
        to_stage: New stage (e.g., 'cs').
        user: Username who made the change (or 'system (auto-reset)').
        note: Optional note/comment.
    """
    try:
        os.makedirs(HISTORY_DIR, exist_ok=True)
        now = datetime.now()
        entry = {
            'ts': now.isoformat(),
            'host': host,
            'container': container,
            'from': from_stage,
            'to': to_stage,
            'user': user,
            'note': note,
        }
        filepath = f'{HISTORY_DIR}/stage_history_{now.strftime("%Y_%m")}.jsonl'
        with open(filepath, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except (OSError, ValueError) as e:
        print(f'[StageHistory] Failed to write: {e}')


def read_stage_history(host: str | None = None, container: str | None = None, limit: int = 100) -> list[dict]:
    """Read stage history entries, newest first.

    Args:
        host: Filter by hostname (optional).
        container: Filter by container (optional).
        limit: Max entries to return.

    Returns:
        List of history dicts, newest first.
    """
    import glob as glob_mod

    pattern = f'{HISTORY_DIR}/stage_history_*.jsonl'
    files = sorted(glob_mod.glob(pattern), reverse=True)

    results: list[dict] = []
    for filepath in files:
        try:
            with open(filepath, 'r') as f:
                file_lines = f.readlines()
                start = max(0, len(file_lines) - limit)
                for line in reversed(file_lines[start:]):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if host and entry.get('host') != host:
                        continue
                    if container and entry.get('container') != container:
                        continue
                    results.append(entry)
                    if len(results) >= limit:
                        return results
        except OSError:
            continue

    return results
