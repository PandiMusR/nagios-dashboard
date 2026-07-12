from __future__ import annotations

import os
import json
import time

from services.config import GLOBAL_CONFIG_PATH
from services.encryption import decrypt_value


def get_uptime_kuma_config() -> dict | None:
    """Return Uptime Kuma connection config if fully configured, else None."""
    try:
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                url = config.get('uptime_kuma_url', '')
                username = config.get('uptime_kuma_username', '')
                password = decrypt_value(config.get('uptime_kuma_password', ''))
                enabled = config.get('uptime_kuma_enabled', False)

                if url and username and password and enabled:
                    return {
                        'url': url,
                        'username': username,
                        'password': password
                    }
    except (json.JSONDecodeError, OSError):
        pass
    return None


def add_host_to_uptime_kuma(hostname: str, ip: str, parent_server: str | None = None) -> tuple[int | None, str | None]:
    """Add a ping monitor to Uptime Kuma and return (monitor_id, error)."""
    try:
        try:
            import socketio
        except ImportError:
            return None, "Socket.IO library not installed"

        config = get_uptime_kuma_config()
        if not config:
            return None, "Uptime Kuma not configured"

        sio = socketio.Client(ssl_verify=False, reconnection=False)

        responses = {'login_ok': False, 'monitor_id': None}

        def on_connect() -> None:
            pass

        def on_disconnect() -> None:
            pass

        sio.on('connect', on_connect)
        sio.on('disconnect', on_disconnect)

        try:
            sio.connect(config['url'], transports=['websocket', 'polling'], wait_timeout=5)
        except Exception as e:
            return None, f"Failed to connect to Uptime Kuma: {str(e)}"

        time.sleep(1)

        login_result: dict = {}

        def on_login_response(res: dict | None) -> None:
            login_result.update(res or {})

        sio.emit('login', {
            'username': config['username'],
            'password': config['password']
        }, callback=on_login_response)

        time.sleep(2)

        if not login_result.get('ok'):
            try:
                sio.disconnect()
            except Exception:
                pass
            return None, f"Failed to login to Uptime Kuma: {login_result.get('msg', 'Invalid credentials')}"

        monitor_data = {
            'name': hostname,
            'type': 'ping',
            'hostname': ip,
            'interval': 60,
            'retryInterval': 60,
            'maxretries': 0,
            'active': True
        }

        add_result: dict = {}

        def on_add_response(res: dict | None) -> None:
            add_result.update(res or {})

        sio.emit('add', {'monitor': monitor_data}, callback=on_add_response)

        time.sleep(2)

        try:
            sio.disconnect()
        except Exception:
            pass

        if add_result.get('ok'):
            return add_result.get('monitorID'), None
        else:
            return None, f"Failed to add monitor: {add_result.get('msg', 'Unknown error')}"

    except Exception as e:
        return None, str(e)


def remove_host_from_uptime_kuma(monitor_id: int) -> tuple[bool, str]:
    """Remove a monitor from Uptime Kuma and return (success, message)."""
    try:
        try:
            import socketio
        except ImportError:
            return False, "Socket.IO library not installed"

        config = get_uptime_kuma_config()
        if not config:
            return False, "Uptime Kuma not configured"

        sio = socketio.Client(ssl_verify=False, reconnection=False)

        try:
            sio.connect(config['url'], transports=['websocket', 'polling'], wait_timeout=5)
        except Exception as e:
            return False, f"Failed to connect to Uptime Kuma: {str(e)}"

        time.sleep(1)

        login_result: dict = {}

        def on_login_response(res: dict | None) -> None:
            login_result.update(res or {})

        sio.emit('login', {
            'username': config['username'],
            'password': config['password']
        }, callback=on_login_response)

        time.sleep(2)

        if not login_result.get('ok'):
            try:
                sio.disconnect()
            except Exception:
                pass
            return False, "Failed to login to Uptime Kuma"

        delete_result: dict = {}

        def on_delete_response(res: dict | None) -> None:
            delete_result.update(res or {})

        sio.emit('deleteMonitor', {'monitorID': monitor_id}, callback=on_delete_response)

        time.sleep(2)

        try:
            sio.disconnect()
        except Exception:
            pass

        return delete_result.get('ok', False), delete_result.get('msg', '')

    except Exception as e:
        return False, str(e)
