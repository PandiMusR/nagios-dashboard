#!/usr/bin/env python3
import sys
import os

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_ROOT)
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from services.proxy_control import ensure_running_and_reload, restart

action = 'reload'
if len(sys.argv) > 1 and sys.argv[1] in ('start', 'reload', 'restart'):
    action = sys.argv[1]

if action == 'restart':
    ok, message = restart()
else:
    ok, message = ensure_running_and_reload()

print(message)
sys.exit(0 if ok else 1)
