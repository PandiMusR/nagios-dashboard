from __future__ import annotations

import json
import os
import re
from calendar import monthrange
from datetime import datetime

_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_DIR = os.path.join(_APP_ROOT, 'config', 'stage_history')
_FILE_MONTH_RE = re.compile(r'stage_history_(\d{4})_(\d{2})\.jsonl$')


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


def _parse_date_bound(raw: str | None, *, end_of_day: bool = False) -> datetime | None:
    if not raw:
        return None
    value = raw.strip()
    try:
        if 'T' in value or ' ' in value:
            normalized = value.replace(' ', 'T', 1)
            if len(normalized) == 16:
                return datetime.strptime(normalized, '%Y-%m-%dT%H:%M')
            return datetime.fromisoformat(normalized)
        dt = datetime.strptime(value, '%Y-%m-%d')
        if end_of_day:
            return dt.replace(hour=23, minute=59, second=59, microsecond=999999)
        return dt
    except ValueError:
        return None


def _entry_datetime(entry: dict) -> datetime | None:
    ts = entry.get('ts')
    if not isinstance(ts, str) or not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _file_in_date_range(filepath: str, start_dt: datetime | None, end_dt: datetime | None) -> bool:
    if start_dt is None and end_dt is None:
        return True
    match = _FILE_MONTH_RE.search(os.path.basename(filepath))
    if not match:
        return True
    year, month = int(match.group(1)), int(match.group(2))
    month_start = datetime(year, month, 1)
    month_end = datetime(year, month, monthrange(year, month)[1], 23, 59, 59, 999999)
    if start_dt and month_end < start_dt:
        return False
    if end_dt and month_start > end_dt:
        return False
    return True


def read_stage_history(
    host: str | None = None,
    container: str | None = None,
    limit: int = 100,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict]:
    """Read stage history entries, newest first.

    Args:
        host: Filter by hostname (optional).
        container: Filter by container (optional).
        limit: Max entries to return.
        start_date: Inclusive start (`YYYY-MM-DD` or ISO datetime). Invalid values ignored.
        end_date: Inclusive end (`YYYY-MM-DD` means end of that day). Invalid values ignored.

    Returns:
        List of history dicts, newest first.
    """
    import glob as glob_mod

    start_dt = _parse_date_bound(start_date)
    end_dt = _parse_date_bound(end_date, end_of_day=True)

    pattern = f'{HISTORY_DIR}/stage_history_*.jsonl'
    files = sorted(glob_mod.glob(pattern), reverse=True)

    results: list[dict] = []
    for filepath in files:
        if not _file_in_date_range(filepath, start_dt, end_dt):
            continue
        try:
            with open(filepath, 'r') as f:
                file_lines = f.readlines()
                for line in reversed(file_lines):
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
                    if start_dt or end_dt:
                        entry_dt = _entry_datetime(entry)
                        if entry_dt is None:
                            continue
                        if start_dt and entry_dt < start_dt:
                            continue
                        if end_dt and entry_dt > end_dt:
                            continue
                    results.append(entry)
                    if len(results) >= limit:
                        return results
        except OSError:
            continue

    return results


def iter_stage_history(
    host: str,
    container: str,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """Yield stage history for one host, oldest first.

    Reads the monthly JSONL files only. Does not write or rewrite them.
    """
    import glob as glob_mod

    start_dt = _parse_date_bound(start_date)
    end_dt = _parse_date_bound(end_date, end_of_day=True)
    pattern = f'{HISTORY_DIR}/stage_history_*.jsonl'
    files = sorted(glob_mod.glob(pattern))

    for filepath in files:
        if not _file_in_date_range(filepath, start_dt, end_dt):
            continue
        try:
            with open(filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get('host') != host or entry.get('container') != container:
                        continue
                    if start_dt or end_dt:
                        entry_dt = _entry_datetime(entry)
                        if entry_dt is None:
                            continue
                        if start_dt and entry_dt < start_dt:
                            continue
                        if end_dt and entry_dt > end_dt:
                            continue
                    yield entry
        except OSError:
            continue
