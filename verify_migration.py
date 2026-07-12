#!/usr/bin/env python3
"""Verify all password fields in global_config.json are encrypted."""
import json
import sys
import os

PROD_CONFIG = '/svr/dashboard-nagios/config/global_config.json'

PASSWORD_FIELDS = ['nextcloud_password', 'uptime_kuma_password', 'password']


def main():
    config_path = PROD_CONFIG if os.path.exists(PROD_CONFIG) else 'config/global_config.json'
    if not os.path.exists(config_path):
        print(f'FAIL: {config_path} not found')
        sys.exit(1)

    with open(config_path, 'r') as f:
        config = json.load(f)

    failures = []
    found = 0
    for field in PASSWORD_FIELDS:
        value = config.get(field)
        if not value:
            continue
        found += 1
        if not isinstance(value, str):
            failures.append(f'{field}: not a string ({type(value).__name__})')
        elif not value.startswith('__ENC__'):
            failures.append(f'{field}: NOT encrypted')

    if not found:
        print('PASS: no password fields found (nothing to verify)')
        return

    if failures:
        print('FAIL:')
        for f in failures:
            print(f'  {f}')
        sys.exit(1)

    print(f'PASS: all {found} password field(s) encrypted')


if __name__ == '__main__':
    main()
