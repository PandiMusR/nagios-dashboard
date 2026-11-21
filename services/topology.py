from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
import hashlib
import os
import re
import stat

MAX_CONFIG = 4 * 1024 * 1024
MAX_HOSTS = 5000
MAX_PARENTS = 64
HOST_NAME = re.compile(r'[\w][\w .:@/-]{0,127}')
OBJECT = re.compile(r'define\s+(\w+)\s*\{')
DIRECTIVE = re.compile(r'([\w-]+)\s+(.+)')
PARENT_LINE = re.compile(r'(\s*parents[ \t]+)(.*?)([ \t]*(?:;[^\r\n]*)?)(\r?\n)?\Z')


class TopologyError(ValueError):
    pass


class TopologyConflict(TopologyError):
    pass


def valid_host(value):
    return isinstance(value, str) and value == value.strip() and HOST_NAME.fullmatch(value) is not None


def read_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    with os.fdopen(fd, 'rb') as handle:
        info = os.fstat(handle.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_CONFIG:
            raise TopologyError('Host configuration is not a supported regular file.')
        raw = handle.read(MAX_CONFIG + 1)
        after = os.fstat(handle.fileno())
        if len(raw) > MAX_CONFIG or (info.st_size, info.st_ctime_ns) != (len(raw), after.st_ctime_ns):
            raise TopologyConflict('Host configuration changed while reading it. Try again.')
        return raw.decode('utf-8'), hashlib.sha256(raw).hexdigest(), info


@dataclass
class Host:
    name: str
    parents: list[str]
    label: str
    address: str
    parent_line: int | None
    end: int
    indent: str
    uses_template: bool


def parse_hosts(lines):
    hosts = {}
    kind = None
    values = {}
    opened = False
    for index, line in enumerate(lines):
        code = line.split(';', 1)[0].strip()
        if not code or code.startswith('#'):
            continue
        if code == '{' and kind is not None and not opened:
            opened = True
            continue
        opening = OBJECT.fullmatch(code)
        if opening or re.fullmatch(r'define\s+\w+', code):
            if kind is not None:
                raise TopologyError('Nested or unclosed Nagios object definition.')
            opened = bool(opening)
            kind = code.split()[1].rstrip('{')
            values = {}
        elif code == '}' and kind is not None and opened:
            if kind == 'host' and values.get('register', ('1', 0))[0] != '0':
                name, name_line = values.get('host_name', ('', 0))
                if not valid_host(name) or name in hosts:
                    raise TopologyError('Invalid or duplicate host identity in localhost.cfg.')
                value, parent_line = values.get('parents', ('null', None))
                parents = [] if value == 'null' else [p.strip() for p in value.split(',')]
                if len(parents) > MAX_PARENTS or any(not valid_host(p) for p in parents):
                    raise TopologyError('Unsupported parents directive in localhost.cfg.')
                indent = re.match(r'[ \t]*', lines[name_line])[0]
                hosts[name] = Host(name, parents, values.get('alias', (name, 0))[0][:256],
                                   values.get('address', ('', 0))[0][:256], parent_line,
                                   index, indent, 'use' in values)
                if len(hosts) > MAX_HOSTS:
                    raise TopologyError('This configuration exceeds the topology host limit.')
            kind = None
        elif kind == 'host' and opened:
            match = DIRECTIVE.fullmatch(code)
            if not match:
                raise TopologyError('Malformed host definition in localhost.cfg.')
            key, value = match.groups()
            if key in ('host_name', 'parents', 'alias', 'address', 'register', 'use'):
                if key in values or (key == 'register' and value not in ('0', '1')):
                    raise TopologyError('Ambiguous host directive in localhost.cfg.')
                values[key] = (value.strip(), index)
        elif kind is None or not opened:
            raise TopologyError('Malformed Nagios object definition in localhost.cfg.')
    if kind is not None:
        raise TopologyError('Unclosed Nagios object definition.')
    return hosts


def dependencies(parents):
    children = defaultdict(list)
    degree = dict.fromkeys(parents, 0)
    levels = dict.fromkeys(parents, 0)
    issues = set()
    edges = []
    for child, ancestors in sorted(parents.items()):
        if len(ancestors) != len(set(ancestors)):
            issues.add('Duplicate parents in localhost.cfg.')
        for parent in sorted(set(ancestors)):
            if parent == child:
                issues.add('A host cannot be its own parent.')
            if parent not in parents:
                issues.add('Some parents are outside this localhost.cfg.')
                continue
            children[parent].append(child)
            degree[child] += 1
            edges.append({'parent': parent, 'child': child})
    ready = deque(sorted(name for name in parents if not degree[name]))
    while ready:
        parent = ready.popleft()
        for child in children[parent]:
            levels[child] = max(levels[child], levels[parent] + 1)
            degree[child] -= 1
            if not degree[child]:
                ready.append(child)
    if any(degree.values()):
        issues.add('The graph contains a circular dependency.')
        fallback = max(levels.values(), default=0) + 1
        for name, remaining in degree.items():
            if remaining:
                levels[name] = fallback
    return levels, edges, sorted(issues)


@dataclass
class Topology:
    source: str
    lines: list[str] = field(init=False)
    hosts: dict[str, Host] = field(init=False)

    def __post_init__(self):
        self.lines = self.source.splitlines(keepends=True)
        self.hosts = parse_hosts(self.lines)

    def graph(self):
        levels, edges, issues = dependencies({name: host.parents for name, host in self.hosts.items()})
        nodes = [{'id': name, 'label': host.label, 'address': host.address,
                  'parents': host.parents, 'level': levels[name]} for name, host in sorted(self.hosts.items())]
        return nodes, edges, issues

    def updated(self, changes):
        parents = {name: host.parents for name, host in self.hosts.items()}
        for name, selected in changes.items():
            if name not in parents:
                raise TopologyError('A changed host is outside this server.')
            if any(not valid_host(parent) or parent == 'null' for parent in selected):
                raise TopologyError('Invalid parent host name.')
        parents.update(changes)
        _, _, issues = dependencies(parents)
        if issues:
            raise TopologyError(' '.join(issues))
        lines = self.lines.copy()
        inserts = {}
        for name, selected in changes.items():
            host = self.hosts[name]
            if set(selected) == set(host.parents) and len(selected) == len(host.parents):
                continue
            value = ','.join(selected) or ('null' if host.uses_template else '')
            if host.parent_line is None:
                eol = '\r\n' if lines[host.end - 1].endswith('\r\n') else '\n'
                inserts[host.end] = host.indent + 'parents ' + value + eol
                continue
            match = PARENT_LINE.fullmatch(lines[host.parent_line])
            if not match:
                raise TopologyError('Cannot safely update this parents directive.')
            prefix, _, suffix, eol = match.groups()
            if value:
                lines[host.parent_line] = prefix + value + suffix + (eol or '')
            elif ';' in suffix:
                lines[host.parent_line] = host.indent + suffix.lstrip() + (eol or '')
            else:
                lines[host.parent_line] = ''
        updated = ''.join(inserts.get(i, '') + line for i, line in enumerate(lines))
        if {name: set(host.parents) for name, host in Topology(updated).hosts.items()} != {
                name: set(selected) for name, selected in parents.items()}:
            raise TopologyError('Cannot safely serialize the proposed parent changes.')
        return updated
