#!/bin/bash

if [ $# -ne 3 ]; then
    echo "Usage: $0 <container_name> <nagios_port> <proxy_port>"
    exit 1
fi

CONTAINER=$1
NAGIOS_PORT=$2
PROXY_PORT=$3

cd /svr/dashboard-nagios
setsid python3 proxy.py $CONTAINER $NAGIOS_PORT $PROXY_PORT > /tmp/proxy_${CONTAINER}.log 2>&1 < /dev/null &

echo "Proxy started for $CONTAINER on port $PROXY_PORT"
echo "Log: /tmp/proxy_${CONTAINER}.log"
