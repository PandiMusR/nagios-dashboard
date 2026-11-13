from __future__ import annotations

from utils.permissions import get_default_permissions

_ADMIN_FLAGS = (
    'dashboard',
    'servers',
    'users',
    'host_manager',
    'monitoring_settings',
    'global_settings',
    'user_permissions',
)


def is_admin(uid: str, stored_perms: dict | None, groups: list[str]) -> bool:
    if not stored_perms or stored_perms == get_default_permissions():
        return f'uid={uid},ou=users,dc=bnet,dc=id' in groups
    return all(stored_perms.get(flag) for flag in _ADMIN_FLAGS)
