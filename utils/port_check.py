from __future__ import annotations

import subprocess


def _get_all_used_ports() -> set[int]:
    """Return set of all ports in use (Docker containers + system services)."""
    used_ports: set[int] = set()

    # Docker container ports
    try:
        result = subprocess.run(['docker', 'ps', '-a', '--format', '{{.Ports}}'],
                                capture_output=True, text=True, timeout=5)
        if result.stdout.strip():
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                for port_mapping in line.split(','):
                    port_mapping = port_mapping.strip()
                    if '->' in port_mapping:
                        try:
                            used_ports.add(int(port_mapping.split(':')[1].split('->')[0]))
                        except (ValueError, IndexError):
                            continue
                    elif ':' in port_mapping:
                        try:
                            used_ports.add(int(port_mapping.split(':')[1].split('/')[0]))
                        except (ValueError, IndexError):
                            continue
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # System ports (netstat or ss)
    for cmd in [['netstat', '-tuln'], ['ss', '-tuln']]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout:
                for line in result.stdout.split('\n'):
                    if 'LISTEN' in line:
                        parts = line.split()
                        if len(parts) >= 4:
                            addr = parts[3]
                            if ':' in addr:
                                try:
                                    used_ports.add(int(addr.split(':')[-1]))
                                except ValueError:
                                    continue
            break  # first working command wins
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

    return used_ports


def check_proxy_running(port: int) -> bool:
    """Check whether any process is listening on the given port."""
    try:
        result = subprocess.run(['lsof', '-i', f':{port}', '-t'], capture_output=True, text=True, timeout=1)
        return bool(result.stdout.strip())
    except (subprocess.CalledProcessError, OSError):
        return False
