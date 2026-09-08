from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, date

from services.config import GLOBAL_CONFIG_PATH, MONITORING_CONFIG_PATH, MONITORING_SERVER_MAPPINGS_PATH
from services.stage_service import (
    get_host_stage, list_host_stages, upsert_host_stage, append_host_comment,
    STAGE_CS, STAGE_NEW,
)
from services.stage_history import append_stage_history

_config_lock = threading.Lock()


def _load_monitoring_config() -> dict:
    """Load monitoring_config.json."""
    try:
        if os.path.exists(MONITORING_CONFIG_PATH):
            with open(MONITORING_CONFIG_PATH, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _load_server_mappings() -> dict:
    """Load monitoring_server_mappings.json. Returns {category: [server_names]}."""
    try:
        if os.path.exists(MONITORING_SERVER_MAPPINGS_PATH):
            with open(MONITORING_SERVER_MAPPINGS_PATH, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _load_last_reset() -> dict[str, str]:
    """Load cr_last_reset from global_config.json. Returns {category: 'YYYY-MM-DD'}."""
    try:
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                return config.get('cr_last_reset', {})
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_last_reset(last_reset: dict[str, str]) -> None:
    """Save cr_last_reset to global_config.json (thread-safe)."""
    with _config_lock:
        try:
            config = {}
            if os.path.exists(GLOBAL_CONFIG_PATH):
                with open(GLOBAL_CONFIG_PATH, 'r') as f:
                    config = json.load(f)
            config['cr_last_reset'] = last_reset
            with open(GLOBAL_CONFIG_PATH, 'w') as f:
                json.dump(config, f, indent=2)
        except (OSError, ValueError) as e:
            print(f'[Auto-Reset] Failed to save last_reset: {e}')


def _get_category_servers(category: str, server_mappings: dict) -> list[str]:
    """Return list of server container names for a category."""
    return server_mappings.get(category, [])


def _should_reset(hours_str: str, interval_days: int, last_reset_date: str | None, now: datetime) -> bool:
    """Check if a category should be reset now.

    Args:
        hours_str: Comma-separated hours (e.g., "15" or "03,15")
        interval_days: Days between resets (1 = daily, 4 = every 4 days)
        last_reset_date: Last reset date string "YYYY-MM-DD" or None
        now: Current datetime

    Returns:
        True if reset should happen now.
    """
    # Parse hours
    try:
        hours = [int(h.strip()) for h in hours_str.split(',') if h.strip().isdigit()]
        hours = [h for h in hours if 0 <= h <= 23]
    except (ValueError, AttributeError):
        return False

    if not hours or now.hour not in hours:
        return False

    # Check interval
    if last_reset_date:
        try:
            last = datetime.strptime(last_reset_date, '%Y-%m-%d').date()
            days_since = (now.date() - last).days
            if days_since < interval_days:
                return False
        except ValueError:
            pass
    # else: never reset before — allow first reset regardless of interval

    return True


def _reset_category_hosts(category: str, server_names: list[str], grace_hours: int) -> int:
    """Reset all CR Verification hosts in a category to New. Returns count.

    Only resets hosts whose container (server) is in server_names.
    A system comment is appended to the host thread; stage history is written after each row update.

    Args:
        category: Monitoring category name.
        server_names: List of server container names for this category.
        grace_hours: Skip hosts set to CR Verification within this many hours.
                     0 = no grace period, reset all CR Verification hosts.
    """
    now = datetime.now()
    count = 0
    skipped = 0
    history_entries: list[tuple[str, str, str, str, str, str]] = []
    server_set = set(server_names)

    for row in list_host_stages(STAGE_CS):
        container = row.get('container') or ''
        host_name = row.get('hostname') or ''
        if container not in server_set:
            continue

        current = get_host_stage(container, host_name)
        if not current or current.get('stage') != STAGE_CS:
            continue

        if grace_hours > 0:
            updated_at = current.get('updated_at', '')
            if not updated_at:
                skipped += 1
                continue
            try:
                updated_time = datetime.fromisoformat(updated_at)
                hours_since = (now - updated_time).total_seconds() / 3600
                if hours_since < grace_hours:
                    skipped += 1
                    continue
            except (ValueError, TypeError):
                skipped += 1
                continue

        upsert_host_stage(
            container,
            host_name,
            STAGE_NEW,
            updated_at=now.isoformat(),
            updated_by='system (auto-reset)',
            note=current.get('note', ''),
            host_up_since=current.get('host_up_since'),
        )
        try:
            append_host_comment(
                container,
                host_name,
                'system (auto-reset)',
                now.isoformat(),
                STAGE_NEW,
                'Auto-reset from CR Verification due to timeout',
            )
        except Exception as e:
            print(f'[Auto-Reset] Failed to write comment for {host_name}: {e}')
        history_entries.append((host_name, container, STAGE_CS, STAGE_NEW, 'system (auto-reset)', f'Auto-reset ({category})'))
        count += 1

    # Write history entries after row updates (non-blocking)
    for entry in history_entries:
        try:
            append_stage_history(*entry)
        except Exception as e:
            print(f'[Auto-Reset] Failed to write history for {entry[0]}: {e}')

    if skipped > 0:
        print(f'[Auto-Reset] "{category}": {skipped} host(s) skipped (within {grace_hours}h grace period)')
    return count


def _scheduler_loop() -> None:
    """Background thread: check every 30 seconds if any category needs reset."""
    last_reset = _load_last_reset()

    while True:
        time.sleep(30)
        now = datetime.now()

        # Reload config each loop (allows changes without restart)
        monitoring_config = _load_monitoring_config()
        server_mappings = _load_server_mappings()
        category_settings = monitoring_config.get('category_settings', {})

        for category, settings in category_settings.items():
            hours_str = settings.get('cr_reset_hours', '')
            interval_days = settings.get('cr_reset_interval_days', 0)
            grace_hours = settings.get('cr_reset_grace_hours', 0)

            if not hours_str or not interval_days:
                continue

            try:
                interval_days = int(interval_days)
            except (ValueError, TypeError):
                continue

            try:
                grace_hours = int(grace_hours) if grace_hours else 0
            except (ValueError, TypeError):
                grace_hours = 0

            if interval_days < 1:
                continue

            last_reset_date = last_reset.get(category)
            if not _should_reset(hours_str, interval_days, last_reset_date, now):
                continue

            # Get servers for this category
            server_names = _get_category_servers(category, server_mappings)
            if not server_names:
                continue

            try:
                count = _reset_category_hosts(category, server_names, grace_hours)
                last_reset[category] = now.strftime('%Y-%m-%d')
                _save_last_reset(last_reset)
                if count > 0:
                    print(f'[Auto-Reset] {count} host(s) in "{category}" reset from CR Verification to New at {now.strftime("%Y-%m-%d %H:%M")}')
            except Exception as e:
                print(f'[Auto-Reset] Error resetting "{category}": {e}')


def start_cr_reset_scheduler() -> None:
    """Start the background scheduler for per-category CR Auto-Reset."""
    thread = threading.Thread(target=_scheduler_loop, daemon=True)
    thread.start()
    print('[Auto-Reset] Scheduler started (per-category mode)')
