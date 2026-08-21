#!/bin/bash
cd "$(dirname "$0")"
exec python3 start_proxy_daemon.py "$@"
