from flask import Flask, request, Response
import requests
import base64
import sys
import os
import json
import logging
import threading
from cryptography.fernet import Fernet
import hashlib

app = Flask(__name__)

if len(sys.argv) != 4:
    print('Usage: python3 proxy.py <container_name> <nagios_port> <proxy_port>')
    sys.exit(1)

CONTAINER_NAME = sys.argv[1]
NAGIOS_PORT = sys.argv[2]
PROXY_PORT = int(sys.argv[3])

BASE_URL = f'http://localhost:{NAGIOS_PORT}'
CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config')
CREDS_FILE = f'{CONFIG_DIR}/nagios_creds_{CONTAINER_NAME}.json'
SECRET_KEY_PATH = os.path.join(CONFIG_DIR, 'secret_key')
ENCRYPTED_MARKER = '__ENC__'

logging.basicConfig(
    filename=f'/tmp/proxy_{CONTAINER_NAME}.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

session = requests.Session()
_thread_local = threading.local()


def _get_fernet():
    if not os.path.exists(SECRET_KEY_PATH):
        return None
    with open(SECRET_KEY_PATH, 'r') as f:
        secret_key = f.read().strip()
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


_fernet = _get_fernet()


def _decrypt_value(value):
    if isinstance(value, str) and value.startswith(ENCRYPTED_MARKER) and _fernet:
        try:
            return _fernet.decrypt(value[len(ENCRYPTED_MARKER):].encode()).decode()
        except Exception:
            return value
    return value


def get_stored_creds():
    try:
        if os.path.exists(CREDS_FILE):
            with open(CREDS_FILE, 'r') as f:
                data = json.load(f)
            return {k: _decrypt_value(v) for k, v in data.items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {'username': 'nagiosadmin', 'password': 'nagiosadmin'}


def store_creds(username, password):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        data = {'username': username, 'password': password}
        if _fernet:
            data = {k: ENCRYPTED_MARKER + _fernet.encrypt(v.encode()).decode() if isinstance(v, str) else v for k, v in data.items()}
        with open(CREDS_FILE, 'w') as f:
            json.dump(data, f)
    except (OSError, ValueError):
        pass


def get_auth_header():
    username = request.headers.get('X-Auth-User')
    password = request.headers.get('X-Auth-Pass')

    if username and password:
        store_creds(username, password)
    else:
        creds = get_stored_creds()
        username = creds['username']
        password = creds['password']

    token = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return f"Basic {token}"


# ===============================
# URL Builder
# ===============================

def build_target_url(path):
    clean_path = path.lstrip('/')

    # Remove duplicate nagios prefix
    if clean_path.startswith('nagios/'):
        clean_path = clean_path[len('nagios/'):]

    # Handle CGI
    if clean_path.startswith('cgi-bin/'):
        target = f'{BASE_URL}/{clean_path}'
    else:
        target = f'{BASE_URL}/nagios/{clean_path}'

    if request.query_string:
        target += '?' + request.query_string.decode()

    return target


# ===============================
# Core Proxy Logic
# ===============================

def forward_request(path):
    try:
        method = request.method
        target_url = build_target_url(path)

        logging.info(f'{method} ? {target_url}')

        headers = {
            key: value
            for key, value in request.headers
            if key.lower() not in [
                'host',
                'content-length',
                'accept-encoding',
                'x-auth-user',
                'x-auth-pass'
            ]
        }

        headers['Authorization'] = get_auth_header()

        resp = session.request(
            method=method,
            url=target_url,
            headers=headers,
            data=request.get_data(),
            timeout=30
        )

        excluded_headers = [
            'content-encoding',
            'content-length',
            'transfer-encoding',
            'connection',
            'keep-alive',
            'proxy-authenticate',
            'proxy-authorization',
            'te',
            'trailers',
            'upgrade'
        ]

        response_headers = [
            (k, v) for k, v in resp.headers.items()
            if k.lower() not in excluded_headers
        ]

        return Response(
            resp.content,
            status=resp.status_code,
            headers=response_headers
        )

    except Exception as e:
        logging.error(str(e), exc_info=True)
        return Response("Proxy Error", status=500)


# ===============================
# Routes
# ===============================

@app.route('/', defaults={'path': ''}, methods=['GET','POST','PUT','DELETE','PATCH'])
@app.route('/<path:path>', methods=['GET','POST','PUT','DELETE','PATCH'])
def proxy(path):
    return forward_request(path)


# ===============================
# Start Server
# ===============================

if __name__ == '__main__':
    print(f'Proxy for {CONTAINER_NAME}')
    print(f'Forwarding to Nagios port {NAGIOS_PORT}')
    print(f'Listening on port {PROXY_PORT}')

    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=PROXY_PORT, threads=8)
    except ImportError:
        app.run(host='0.0.0.0', port=PROXY_PORT, threaded=True)
