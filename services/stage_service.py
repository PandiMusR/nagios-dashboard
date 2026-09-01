from __future__ import annotations

import sqlite3

from services.config import (
    STAGE_NEW, STAGE_CS, STAGE_ESCALATED, STAGE_WATCHLIST, STAGE_RESOLVED,
    STAGE_LABELS, STAGE_RETAIN_MINUTES
)
from services.stage_db import (
    append_comment as db_append_comment,
    clear_host_up_since as db_clear_host_up_since,
    delete_stage as db_delete_stage,
    insert_stage_if_absent,
    list_comments as db_list_comments,
    list_stage_rows,
    relocate_comments as db_relocate_comments,
    select_stage,
    set_host_up_since_if_unset as db_set_host_up_since_if_unset,
    upsert_stage as db_upsert_stage,
)


def get_stage_key(container: str, hostname: str) -> str:
    """Return the composite key for a host within a container."""
    return f'{container}__{hostname}'


def get_host_stage(container: str, hostname: str) -> dict | None:
    try:
        return select_stage(container, hostname)
    except (OSError, ValueError, sqlite3.Error):
        return None


def list_host_stages(stage: str | None = None) -> list[dict]:
    try:
        return list_stage_rows(stage=stage)
    except (OSError, ValueError, sqlite3.Error):
        return []


def upsert_host_stage(
    container: str,
    hostname: str,
    stage: str,
    updated_at: str | None = None,
    updated_by: str | None = None,
    note: str | None = None,
    host_up_since: str | None = None,
) -> None:
    db_upsert_stage(
        container,
        hostname,
        stage,
        updated_at=updated_at,
        updated_by=updated_by,
        note=note,
        host_up_since=host_up_since,
    )


def delete_host_stage(container: str, hostname: str) -> None:
    db_delete_stage(container, hostname)


def insert_host_stage_if_absent(
    container: str,
    hostname: str,
    stage: str,
    updated_at: str | None = None,
    updated_by: str | None = None,
    note: str | None = None,
    host_up_since: str | None = None,
) -> bool:
    return insert_stage_if_absent(
        container,
        hostname,
        stage,
        updated_at=updated_at,
        updated_by=updated_by,
        note=note,
        host_up_since=host_up_since,
    )


def set_host_up_since_if_unset(container: str, hostname: str, host_up_since: str) -> bool:
    return db_set_host_up_since_if_unset(container, hostname, host_up_since)


def clear_host_up_since(container: str, hostname: str) -> None:
    db_clear_host_up_since(container, hostname)


def list_host_comments(container: str, hostname: str) -> list[dict]:
    try:
        return db_list_comments(container, hostname)
    except (OSError, ValueError, sqlite3.Error):
        return []


def append_host_comment(
    container: str,
    hostname: str,
    user: str,
    timestamp: str,
    stage: str,
    text: str,
) -> None:
    db_append_comment(container, hostname, user, timestamp, stage, text)


def relocate_host_comments(
    old_container: str,
    old_hostname: str,
    new_container: str,
    new_hostname: str,
) -> None:
    db_relocate_comments(old_container, old_hostname, new_container, new_hostname)
