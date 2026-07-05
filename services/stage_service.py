from __future__ import annotations

import os
import json
import threading
from contextlib import contextmanager
from collections.abc import Generator

from services.config import (
    HOST_STAGES_PATH,
    STAGE_NEW, STAGE_CS, STAGE_ESCALATED, STAGE_WATCHLIST, STAGE_RESOLVED,
    STAGE_LABELS, STAGE_RETAIN_MINUTES
)

_stages_lock = threading.Lock()


def load_host_stages() -> dict:
    """Load host stage data from the JSON file."""
    try:
        if os.path.exists(HOST_STAGES_PATH):
            with open(HOST_STAGES_PATH, 'r') as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_host_stages(stages: dict) -> None:
    """Persist host stage data to the JSON file."""
    try:
        with _stages_lock:
            with open(HOST_STAGES_PATH, 'w') as f:
                json.dump(stages, f, indent=2)
    except Exception as e:
        print(f'Failed to save host stages: {e}')


@contextmanager
def host_stages_transaction() -> Generator[dict]:
    """Context manager that loads stages, yields them for mutation, then saves."""
    with _stages_lock:
        stages = load_host_stages()
        yield stages
        try:
            with open(HOST_STAGES_PATH, 'w') as f:
                json.dump(stages, f, indent=2)
        except Exception as e:
            print(f'Failed to save host stages: {e}')


def get_stage_key(container: str, hostname: str) -> str:
    """Return the composite key for a host within a container."""
    return f'{container}__{hostname}'
