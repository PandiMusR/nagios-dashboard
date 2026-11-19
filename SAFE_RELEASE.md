# Safe release publisher

This implementation is development-tested infrastructure, not an activated production deployment system. Nothing here installs a helper, changes sudo/OpenRC, connects to production, migrates data, or changes the running application. Production activation requires the operator approvals and Alpine rehearsal below.

## Build from immutable Git objects

Run from the repository using Python 3.12 and Git:

```sh
python3 -B -m release_tools.builder \
  --commit 8c4b2e2d8ee289d658935f998f12498ed83d51e0 \
  --output /tmp/nagios-pr2-release
```

The output directory must not exist. `release.tar` is deterministic USTAR with five regular files, sorted paths, commit timestamps, UID/GID zero, and mode 0644. `manifest.json` records commit, per-file SHA-256/size/metadata and artifact SHA-256/size. Working-tree changes, caches, configuration, databases and secrets cannot enter the fixed allowlist. A different exact 40-character commit can be selected for preparation; it still requires independent approval.

The cohort is `services/host_config.py` and `blueprints/{api,global_settings,host_manager,servers}.py`. Extending it requires a reviewed code change, not a CLI parameter. No dependency or schema update is part of this release.

## Independent approval

An uploaded artifact and its builder manifest do not authorize root publication. A root operator must independently verify the reviewed commit, test receipt, file hashes, expected current production hashes, and the artifact hash. Root approval of arbitrary Python is root code-execution authority.

The installed publisher reads only `/etc/nagios-release/approval.json`, a root-owned 0600 regular file in a root-only directory. JSON duplicate/unknown keys, invalid metadata and invalid execution windows are rejected. The schema is:

```json
{
  "schema": 1,
  "approval_id": "32 lowercase hexadecimal characters, unique per attempt",
  "commit": "40 lowercase hexadecimal characters",
  "not_before": 0,
  "expires_at": 0,
  "artifact_sha256": "independently approved SHA-256",
  "artifact_size": 0,
  "files": {
    "each of the five exact paths": {
      "sha256": "approved SHA-256",
      "size": 0,
      "uid": 0,
      "gid": 0,
      "mode": 420,
      "before": {"sha256": "expected production SHA-256", "size": 0}
    }
  },
  "validation": {
    "containers": ["operator-verified-active-container"],
    "health_timeout": 30,
    "freshness_timeout": 180
  }
}
```

This is a schema illustration, not a usable approval. Epoch timestamps are integer UTC seconds. Sizes must be positive. `before` may be null only for `services/host_config.py`; otherwise all existing code must match its hash, size, UID/GID zero and mode 0644. Approval ID is an attempt nonce, not a reusable release name. Only a root operator creates/replaces approval records. Never automatically promote the uploaded manifest to approval.

## Bootstrap prerequisites: separate operator change

No installation script is provided. An authorized root operator must first review and provision:

| Installed path | Requirement |
|---|---|
| `/usr/local/libexec/nagios-release/release_tools/` | Copy the package; root-owned, no group/other write |
| `/usr/local/libexec/nagios-release/entry.py` | Copy `release_tools/entry.py` |
| `/usr/local/libexec/nagios-release/guard_entry.py` | Copy `release_tools/guard_entry.py` |
| `/usr/local/sbin/nagios-release-approved` | Copy the matching `scripts/` wrapper, root-owned executable |
| `/usr/local/sbin/nagios-release-startup-guard` | Copy the matching `scripts/` wrapper, root-owned executable |
| `/etc/nagios-release/` | Root-owned 0700; approval and maintenance records 0600 |
| `/var/lib/nagios-release/state/` | Root-owned 0700; persistent journal, staging, backups, receipts and events |
| `/var/lib/nagios-release/incoming/rif/` | Root-owned, group `rif`, mode 0730; trusted ancestors |
| `/svr/dashboard-nagios/config/host_config_locks/` | Root-owned 0700, local writable filesystem |

The upload must be a single-link, regular 0600 file owned by UID 1001 named `<approval_id>.tar`. UID 1001 must be confirmed against the real `rif` account before activation; changing this is a reviewed implementation change. The root-owned inbox directory can accept uploads but cannot itself be replaced by `rif`.

The fixed wrappers reject arguments, clear the environment, and invoke isolated Python. A proposed delegation rule, not installed by this project, is:

```sudoers
rif ALL=(root) NOPASSWD: NOSETENV: /usr/local/sbin/nagios-release-approved ""
```

The operator must validate policy with the installed sudo tooling. Do not delegate Python, shells, copy tools, arbitrary service commands, approval editing or environment overrides. No root SSH grant is required.

Integrate the startup guard into the existing Dashboard OpenRC `start_pre` without discarding its other checks. Every Dashboard startup must invoke it. The publisher requires a root attestation but cannot prove that OpenRC actually runs the guard; test this integration before setting the attestation. The guard permits only a complete approved before/after cohort in appropriate journal states. Unknown/mixed states block startup. This bootstrap changes no Nagios/collector/proxy units.

The guard needs all configured directories to exist before installation. It does not activate or install itself. Do not enable it without a valid initial approval and a console recovery plan.

## Maintenance freeze

Root creates `/etc/nagios-release/maintenance.json` (0600):

```json
{
  "approval_id": "same 32-character attempt nonce",
  "expires_at": 0,
  "drained": true,
  "startup_guard_installed": true
}
```

This is an external operator attestation, not an automatic traffic drain. Freeze API/Host Manager/server mutations, other deployments and credential updates; hold new Dashboard ingress; confirm requests and background builds have completed. A returned HTTP response or empty connection list does not prove this. Builds can run for ten minutes. Do not issue the record if job state is uncertain. The ingress hold remains until NOC acceptance; lease expiration must not automatically reopen ingress.

The lease is checked before interruption and again after potentially slow preflight. Recovery of an interrupted attempt requires a renewed maintenance record for that attempt, even if the original approval window expired.

## Publication and validation

After upload, the proposed invocation is only:

```sh
sudo -n /usr/local/sbin/nagios-release-approved
```

The program has no caller-selected production paths, checksums or commands. Library injection points exist only for temporary-directory tests; the production entry point uses fixed paths and root ownership checks.

1. Acquire the persistent publisher lock and inspect any previous journal.
2. Validate root approval, lease and production baseline.
3. Read the bounded upload through a no-follow descriptor. Verify its bytes before parsing. Reject links, special/duplicate/unexpected members, missing files and invalid Python syntax. Stage private verified copies; never extract an archive into production.
4. Test cross-process nonblocking locking using `.publisher-probe.lock`. This reserved persistent file is retained; actual shared lock files are never removed.
5. Verify existing Dashboard/collector/proxy PID identities and private configuration metadata. Do not read key/password contents.
6. Observe a successful collector advance before interruption. Direct `mode=ro` SQLite queries use approved containers, no application imports or schema initialization. Require healthy records and bounded advancement; do not use DB modification time. Choose the 1–180 second deadline from observed cycle times, not an assumed 30-second cycle.
7. Back up code and captured UID/GID/mode/timestamps, mark the approval consumed, and durably journal each phase.
8. Stop only `dashboard-nagios`; verify it stopped, then publish the complete cohort with same-directory temporary files and atomic replacements.
9. Verify installed hashes/metadata, mark `INSTALLED`, then start Dashboard. The startup guard must permit this complete cohort.
10. Validate fixed loopback `/login` and `/static/css/login.css` reads, collector/proxy process continuity, credential metadata stability and successful snapshot advancement. Do not follow redirects or log response bodies. Do not call `/health`, import `app.py`, or run CGI/administrative mutations.
11. Commit, or perform one controlled rollback. Audit events contain identifiers, phases and reason codes, not secrets, request bodies or raw service output.

OpenRC operations have 30-second controller timeouts. An uncertain controller timeout requires operator intervention rather than racing a potentially still-running start/stop operation. HTTP validation also has a process alarm deadline, so a slowly trickling response cannot extend the socket timeout indefinitely. SQLite queries have bounded busy/progress limits; a freshness deadline can include the final bounded query. The existing service stop semantics must be reviewed: the publisher never adds a forced-kill escalation. Its safety depends on the prior drain attestation.

NOC separately checks normal authentication and an existing native read view. The `/nagios/<container>` launcher rewrites collector credentials and is not an automated read-only canary. Do not use X-Auth headers or command CGI for validation. Keep the maintenance freeze until acceptance.

## Recovery and idempotency

`READY → STOPPING → STOPPED → INSTALLING → INSTALLED → VERIFYING → COMMITTED` is persisted with fsync and separate audit records. Five files are not one filesystem transaction; the journal, stopped service and startup guard prevent a partial cohort from being accepted.

A repeated committed attempt verifies hashes and returns `already-current` without restarting. Consumed approvals cannot reinstall after abort/rollback, even if the current journal changed. A new independently approved nonce is required.

Interrupted attempts are inspected before accepting another release. If interruption occurred before any install and the original service is still running with the entire baseline, the attempt is aborted without a restart. Otherwise the helper verifies every backup and current file before restoring anything. It restores only states recognized as approved old/new bytes. An added module is removed only when its hash and journal prove provenance. Persistent application data and lock files are never restored/deleted.

Rollback restores code ownership, permissions and timestamps, starts only Dashboard, verifies availability and unrelated process identities, and records `ROLLED_BACK`. Snapshot/key/configuration values are never restored. Rollback does not repair an independent collector incident; investigate it separately.

Unknown code changes, bad backups, stop uncertainty or failed rollback record `MANUAL_INTERVENTION` and block subsequent automatic publication/startup. Preserve the journal, backups and audit events. An authorized root operator must reconcile the complete before cohort and metadata, verify hashes, record the manual resolution, and only then mark the journal `ABORTED` to let the guard verify the baseline. Never clear state/used receipts to replay an approval. Never start a mixed cohort or remove shared locks.

## Validation and activation limits

Run on Development:

```sh
python3 -B -m unittest discover -s tests -p 'test_release_publisher.py' -v
python3 -B -m unittest discover -s tests -p 'test*.py' -v
bash -n scripts/nagios-release-approved scripts/nagios-release-startup-guard
git diff --check
```

Tests use temporary code/data, fake service controls, synthetic snapshots and real local file locks. Release tests never import `app.py` or call production OpenRC, Docker or LDAP. Existing application route regressions remain unchanged and use their isolated dependency stubs.

Before production activation, separately rehearse on Alpine/OpenRC with the actual LXC UID mappings/filesystem: startup-hook enforcement, process/PID discovery, service timeouts, live-WAL reads, lock behavior, real ownership changes, power-loss recovery and console rollback. Nonempty ACLs/xattrs are deliberately rejected rather than silently discarded; metadata outside fixed UID/GID zero and 0644 code requires review. Linux/POSIX filesystem behavior is required.

Complete the secret-storage consumer audit and private permissions, network/IPv6/Docker containment review, NOC legacy decision, and shared-lock coordination with external source readers. The publisher does not perform these changes, install dependencies, provision sudo, rotate keys, stop legacy services, change firewall rules, run migrations or fix proxy authentication. Root compromise and uncoordinated root operators remain outside the helper's trust boundary.
