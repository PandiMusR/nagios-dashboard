#!/bin/sh
# preflight_check.sh — verify required environment variables before deploy
# Run on production:  bash preflight_check.sh
# Exit 0 = all OK,   Exit 1 = missing vars

REQUIRED_VARS="LDAP_ADMIN_PASSWORD"
MISSING=""
CONF_FILE="/etc/conf.d/dashboard-nagios"

for VAR in $REQUIRED_VARS; do
    VALUE=""
    if eval "test -n \"\${$VAR:-}\"" 2>/dev/null; then
        eval "VALUE=\"\${$VAR}\""
    fi
    if [ -z "$VALUE" ] && [ -f "$CONF_FILE" ]; then
        VALUE="$(grep "^export $VAR=" "$CONF_FILE" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")"
    fi
    if [ -z "$VALUE" ]; then
        MISSING="$MISSING $VAR"
    fi
done

if [ -n "$MISSING" ]; then
    echo "ERROR: Required environment variables not set:$MISSING" >&2
    echo "" >&2
    echo "Add them to $CONF_FILE:" >&2
    for VAR in $MISSING; do
        echo "  export $VAR=\"your-value-here\"" >&2
    done
    echo "" >&2
    echo "Then restart the service:" >&2
    echo "  rc-service dashboard-nagios restart" >&2
    exit 1
fi

echo "Pre-flight check PASSED — all required environment variables are set."
exit 0
