# Network topology

Open **Nagios → [server] · Topology** to see the configured parent dependencies. The arrows point from parent to child. Read access follows the Dashboard's administrator role or its explicit `nagios_<server>` permission. The native Nagios link still opens the existing Nagios pages.

The graph uses the explicit `parents` directives in `/svr/<server>/etc/objects/localhost.cfg`. Each registered server has one graph. A host may have several parents, and independent roots start at the same level. The graph uses [vis-network 10.1.5](https://github.com/visjs/vis-network/releases/tag/v10.1.5), served from `static/vendor/`. The bundled file comes from the [pinned upstream package](https://registry.npmjs.org/vis-network/-/vis-network-10.1.5.tgz), SHA-256 `33178a58abef773d4f8e77425d7b74c0a250349102f4c75f4a9d170ca3f1f437`. Its source and license notices accompany it.

## View and edit

Use search to find a host by name, alias or address. Selecting it highlights related edges and lists its parents and children. Use zoom, fit, pan, fullscreen or the alternate layout direction to explore larger graphs. Dragged positions exist in page memory and survive status refresh. **Reset layout** or a page reload restores generated positions.

Administrators can enter **Edit connections** for servers explicitly enabled by the operator. Select the child, then add or remove parents using its connection panel. A replacement combines removing the old parent and adding the new one. Dashed green and red edges show pending additions and removals. Undo, redo and cancel operate on the browser draft. **Update topology** shows the proposed changes before sending a request.

The graph shows direct declarations from this file. Inherited relationships in other files and physical cabling are outside its scope. Unresolved parents or cycles show a warning and any proposed save must produce a valid direct graph. Ambiguous host definitions and unsupported additive parent directives require operator review. Nagios's full configuration verifier also checks the effective configuration before publication. Removing the last parent from a host with `use` writes `parents null` to cancel string inheritance under [Nagios object inheritance rules](https://assets.nagios.com/downloads/nagioscore/docs/nagioscore/4/en/objectinheritance.html).

## API

| Method and route | Result |
| --- | --- |
| `GET /topology/<server>` | Authenticated native graph page |
| `GET /api/topology/<server>` | Nodes, parent-to-child edges, layout levels, warnings, SHA-256 revision and initial snapshot |
| `GET /api/topology/<server>/status` | Status keyed by exact hostname, last successful poll and staleness |
| `POST /api/topology/<server>/parents` | Apply revised parent lists after authorization, CSRF and validation |

A mutation accepts only JSON with `revision` and `changes`. Send the session CSRF token in `X-CSRFToken`. An empty list clears the named host's parents.

```json
{
  "revision": "<64-character SHA-256 from the graph endpoint>",
  "changes": {
    "KELURAHAN": ["POP002"],
    "AP1": ["KELURAHAN", "POP001"]
  }
}
```

Limits are 128 KiB for the request, 4 MiB for the configuration, 5,000 hosts and 64 parents per edited host. The API rejects unknown hosts, self-references, duplicate identities or parents, and circular dependencies. A stale revision or busy lock returns HTTP 409. A no-op preserves the existing bytes and skips Nagios control. Account creation, editing and deletion require an administrator because they can change accounts trusted by this editor.

Status polling runs every 30 seconds while the page is visible. It uses one bounded, read-only SQLite transaction for that server. Status uses the existing snapshot codes for pending, up, down and unreachable. Missing or unrecognized status is unknown. A stale or failed poll leaves the previous snapshot identifiable as such. Polling updates colors in place.

## Publication and operator prerequisites

Writes are disabled until the process environment contains `NAGIOS_TOPOLOGY_WRITABLE_SERVERS` with an explicit comma-separated server allowlist. Administrator access and current server registration are checked on each mutation. The existing shared host-config lock coordinates with Dashboard writers and stays held through verification, backup, publication and restart.

The writer verifies a writable directory binding from the expected local `/svr/<server>/etc` to `/opt/nagios/etc`, and pins the local container ID. The supported configuration explicitly includes `localhost.cfg` using a single absolute `cfg_file` directive and declares a status file under `/opt/nagios/var`. Directory includes, alternate mounts, symlinks, hard-linked host config and extended metadata require separate validation before enabling edits.

Nagios `-v` runs in that container with a staged main config pointing to the candidate. A verified backup is stored in the existing Host Manager backup directory. Publication uses the shared atomic replacement helper and preserves UID, GID and mode. The selected container restarts through the existing Docker workflow. A bounded readiness check confirms that a fresh Nagios process reports its PID and primary configuration. A failed apply restores the original file when safe and validates the recovery restart. If a restart times out, the original file is restored and the runtime outcome is reported as uncertain for operator verification.

Before enabling any server, confirm all application writers use the shared lock. Schedule around external scripts, manual edits and direct service controls that do not use that lock. Verify the exact container mount, permissions and restart behavior. Include the new template and local vendor asset in any future deployment manifest.

## Isolated development

Use the feature worktree and an authorized Development Docker daemon. The repository's server discovery sees existing Development containers. Never point the write allowlist at those containers for testing.

1. Create a fresh directory with `mktemp -d /svr/nagios_topology_test_XXXXXX`. Use the basename as the dedicated Docker container name. Install the two synthetic configs in `tests/fixtures/topology/` under its `etc/` and `etc/objects/` directories.
2. Use the locally available `nagios-ldap:latest` image. Run Nagios Core directly with `--entrypoint /opt/nagios/bin/nagios` and argument `/opt/nagios/etc/nagios.cfg`. Bind only the fresh `etc` directory to `/opt/nagios/etc`. Use `--network none`, no port publications, and explicit memory, CPU and PID limits. The fixture has notifications and active checks disabled.
3. Use a loopback-only Flask fixture with the real topology blueprint and CSRF protection, synthetic session identity, a fresh SQLite snapshot and a separate `host_config.LOCK_DIR`. Enable edits for the fixture name only. The existing collector and LDAP startup are unnecessary for this rehearsal.
4. Verify an edit by reading the refreshed graph, the isolated `localhost.cfg` and the running container's `/opt/nagios/var/objects.cache`. Remove only the dedicated fixture container and its volumes at cleanup.

Run the regression suite with the project requirements installed:

```sh
python3 -B -m unittest discover -s tests -p 'test*.py' -v
```
