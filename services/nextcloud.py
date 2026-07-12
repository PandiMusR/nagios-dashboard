from __future__ import annotations

import os
import json
import re
import requests
from requests.auth import HTTPBasicAuth

from services.config import GLOBAL_CONFIG_PATH
from services.encryption import decrypt_value


def get_nextcloud_config() -> dict | None:
    """Return Nextcloud WebDAV config parsed from the global config, or None."""
    try:
        if os.path.exists(GLOBAL_CONFIG_PATH):
            with open(GLOBAL_CONFIG_PATH, 'r') as f:
                config = json.load(f)
                share_link = config.get('nextcloud_share', '')
                password = decrypt_value(config.get('nextcloud_password', ''))

                if share_link and password:
                    match = re.search(r'/s/([^/]+)', share_link)
                    if match:
                        share_id = match.group(1)
                        base_url = share_link.split('/index.php')[0]
                        return {
                            'url': f'{base_url}/public.php/webdav',
                            'user': share_id,
                            'password': password
                        }
    except (json.JSONDecodeError, OSError):
        pass
    return None


def upload_to_nextcloud(server: str, backup_path: str, backup_name: str) -> bool:
    """Upload a backup file to a Nextcloud share under the given server folder."""
    try:
        nc_config = get_nextcloud_config()
        if not nc_config:
            return False

        folder_url = f"{nc_config['url']}/{server}"
        requests.request('MKCOL', folder_url, auth=HTTPBasicAuth(nc_config['user'], nc_config['password']))

        file_url = f"{nc_config['url']}/{server}/{backup_name}.cfg"
        with open(backup_path, 'rb') as f:
            response = requests.put(file_url, data=f, auth=HTTPBasicAuth(nc_config['user'], nc_config['password']), timeout=30)

        return response.status_code in [200, 201, 204]
    except Exception as e:
        print(f"Nextcloud upload error: {e}")
        return False
