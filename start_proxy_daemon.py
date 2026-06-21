#!/usr/bin/env python3
import sys
import os
import subprocess

if len(sys.argv) != 4:
    print('Usage: python3 start_proxy_daemon.py <container_name> <nagios_port> <proxy_port>')
    sys.exit(1)

container = sys.argv[1]
nagios_port = sys.argv[2]
proxy_port = sys.argv[3]

# Auto-detect project root from this file's location
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(APP_ROOT)

# Open log file in append mode (preserve previous logs)
log_file = open(f'/tmp/proxy_{container}.log', 'a')

# Start proxy as daemon
proc = subprocess.Popen(
    ['python3', 'proxy.py', container, nagios_port, proxy_port],
    stdout=log_file,
    stderr=subprocess.STDOUT,
    stdin=subprocess.DEVNULL,
    start_new_session=True,
    cwd=APP_ROOT
)

log_file.close()

print(f'Proxy started for {container} on port {proxy_port} (PID: {proc.pid})')
print(f'Log: /tmp/proxy_{container}.log')
