from __future__ import annotations

from datetime import datetime, timedelta

from services.stage_history import iter_stage_history

AUTO_USER = 'system (auto-detect)'
NOTE_WENT_DOWN = 'Host went DOWN'
NOTE_RECOVERED = 'Host recovered'
DEFAULT_WINDOW_DAYS = 30
MAX_WINDOW_DAYS = 92
MAX_EPISODES = 50
MAX_TRAIL = 80


def _is_down_open(entry: dict) -> bool:
    return (
        entry.get('from') == 'up'
        and entry.get('to') == 'new'
        and entry.get('user') == AUTO_USER
        and entry.get('note') == NOTE_WENT_DOWN
    )


def _is_recovery(entry: dict) -> bool:
    note = entry.get('note') or ''
    return (
        entry.get('to') == 'up'
        and entry.get('user') == AUTO_USER
        and isinstance(note, str)
        and note.startswith(NOTE_RECOVERED)
    )


def _parse_ts(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _slim(entry: dict) -> dict:
    return {
        'ts': entry.get('ts') or '',
        'from': entry.get('from') or '',
        'to': entry.get('to') or '',
        'user': entry.get('user') or '',
        'note': entry.get('note') or '',
    }


def resolve_window(
    start_date: str | None,
    end_date: str | None,
    now: datetime | None = None,
) -> tuple[datetime, datetime, bool]:
    """Return an inclusive window, default 30 days, capped at about 3 months."""
    from services.stage_history import _parse_date_bound

    now = now or datetime.now()
    end_dt = _parse_date_bound(end_date, end_of_day=True) if end_date else None
    start_dt = _parse_date_bound(start_date) if start_date else None
    if end_dt is None:
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    if start_dt is None:
        start_day = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        start_dt = start_day - timedelta(days=DEFAULT_WINDOW_DAYS - 1)
    clamped = False
    if start_dt > end_dt:
        start_dt = end_dt.replace(hour=0, minute=0, second=0, microsecond=0)
        clamped = True
    earliest = (end_dt - timedelta(days=MAX_WINDOW_DAYS)).replace(
        hour=0, minute=0, second=0, microsecond=0,
    )
    if start_dt < earliest:
        start_dt = earliest
        clamped = True
    return start_dt, end_dt, clamped


def _duration_seconds(down_at: str, up_at: str | None, now: datetime, still_down: bool) -> int | None:
    start = _parse_ts(down_at)
    if start is None:
        return None
    if still_down:
        end = now
    else:
        end = _parse_ts(up_at)
        if end is None:
            return None
    seconds = int((end - start).total_seconds())
    return max(seconds, 0)


def build_down_episodes(
    host: str,
    container: str,
    start_date: str | None = None,
    end_date: str | None = None,
    now: datetime | None = None,
) -> dict:
    """Pair automatic up→new with the next automatic Host recovered.

    Manual stage changes stay in the trail and do not open or close an episode.
    """
    now = now or datetime.now()
    start_dt, end_dt, clamped = resolve_window(start_date, end_date, now)
    start_key = start_dt.strftime('%Y-%m-%d')
    end_key = end_dt.strftime('%Y-%m-%d')

    episodes: list[dict] = []
    current: dict | None = None
    for entry in iter_stage_history(host, container, start_key, end_key):
        if _is_down_open(entry):
            if current is not None:
                current['missing_recovery'] = True
                current['still_down'] = False
                episodes.append(current)
            current = {
                'down_at': entry.get('ts') or '',
                'up_at': None,
                'still_down': True,
                'missing_recovery': False,
                'trail': [_slim(entry)],
            }
            continue
        if current is None:
            continue
        slim = _slim(entry)
        if len(current['trail']) < MAX_TRAIL:
            current['trail'].append(slim)
        else:
            current['trail_truncated'] = True
            if _is_recovery(entry):
                current['trail'].append(slim)
        if _is_recovery(entry):
            current['up_at'] = entry.get('ts') or ''
            current['still_down'] = False
            episodes.append(current)
            current = None
    if current is not None:
        episodes.append(current)

    for episode in episodes:
        episode['duration_seconds'] = _duration_seconds(
            episode['down_at'],
            episode['up_at'],
            now,
            episode['still_down'],
        )
        episode.setdefault('trail_truncated', False)

    total = len(episodes)
    truncated = total > MAX_EPISODES
    shown = episodes[-MAX_EPISODES:]
    shown.reverse()
    downtime = sum(
        ep['duration_seconds'] for ep in episodes if ep['duration_seconds'] is not None
    )
    last_down = shown[0]['down_at'] if shown else None
    still_down = bool(shown and shown[0]['still_down'])
    as_of = now if now < end_dt else end_dt
    spans = [
        {
            'down_at': ep['down_at'],
            'up_at': ep['up_at'],
            'still_down': ep['still_down'],
            'missing_recovery': ep['missing_recovery'],
        }
        for ep in episodes
    ]

    return {
        'host': host,
        'container': container,
        'start_date': start_key,
        'end_date': end_key,
        'window_start': start_dt.isoformat(),
        'as_of': as_of.isoformat(),
        'clamped': clamped,
        'truncated': truncated,
        'summary': {
            'episodes': total,
            'shown': len(shown),
            'total_downtime_seconds': downtime,
            'last_down_at': last_down,
            'still_down': still_down,
        },
        'episodes': shown,
        'spans': spans,
    }
