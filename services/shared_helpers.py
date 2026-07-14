from __future__ import annotations

import json
import threading
import time

from services.config import MONITORING_CATEGORIES_PATH, MONITORING_SERVER_MAPPINGS_PATH, MONITORING_CONFIG_PATH
from services.docker_cache import docker_cache

_config_cache: dict[str, tuple[float, dict | list]] = {}
_cache_lock = threading.Lock()


def _cached_json(path: str, ttl: int = 30) -> dict | list | None:
    with _cache_lock:
        now = time.time()
        if path in _config_cache and now < _config_cache[path][0]:
            return _config_cache[path][1]
    try:
        with open(path) as f:
            data = json.load(f)
        with _cache_lock:
            _config_cache[path] = (time.time() + ttl, data)
        return data
    except (json.JSONDecodeError, OSError):
        return None


def get_nagios_servers() -> list[str]:
    output = docker_cache.get_or_run(
        'nagios_containers_names',
        ['docker', 'ps', '--filter', 'ancestor=nagios-ldap:latest', '--format', '{{.Names}}']
    )
    return [c for c in output.strip().split('\n') if c]


def get_monitoring_categories() -> list[str]:
    categories: list[str] = []
    seen: set[str] = set()
    for default_category in ['prioritas', 'bhome', 'diskominfo']:
        seen.add(default_category)
        categories.append(default_category)

    for path in [MONITORING_CATEGORIES_PATH, MONITORING_SERVER_MAPPINGS_PATH]:
        data = _cached_json(path)
        if data is None:
            continue
        items = data if isinstance(data, list) else data.keys()
        for key in items:
            if not isinstance(key, str):
                continue
            normalized = key.strip().lower()
            if normalized and normalized not in seen:
                seen.add(normalized)
                categories.append(normalized)

    config = _cached_json(MONITORING_CONFIG_PATH)
    if config and isinstance(config, dict):
        for sub_key in ['category_settings', 'alarm_settings']:
            sub_dict = config.get(sub_key, {})
            if isinstance(sub_dict, dict):
                for key in sub_dict:
                    if not isinstance(key, str):
                        continue
                    normalized = key.strip().lower()
                    if normalized and normalized not in seen:
                        seen.add(normalized)
                        categories.append(normalized)

    return categories
