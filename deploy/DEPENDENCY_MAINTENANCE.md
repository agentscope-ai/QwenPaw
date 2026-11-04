# Shared dependency maintenance under Supervisor

When a plugin needs to replace shared dependencies, review and explicitly apply
the retained upgrade plan. A Supervisor-managed backend leaves the approved
operation in `waiting_restart` and returns offline instructions. The backend
continues running until you stop it through Supervisor; it does not start a
worker or replace Supervisor's process. Standalone `qwenpaw app` without reload
retains its automatic handoff. Reload and externally launched ASGI servers use
manual maintenance.

The official Docker image and Creator image use the same `app` program and
`/etc/supervisor/conf.d/supervisord.conf`. Their root-owned control socket is
`/run/qwenpaw-supervisor.sock` with mode `0600`; no network control port is
needed. Images built before this socket configuration was added need to be
rebuilt before using this procedure.

1. Save the worker command returned in the operation's `instructions` before
   stopping the backend. It contains the absolute Python and retained worker
   paths for this operation. Use those exact paths inside the container.
2. From the Docker host, stop the backend through Supervisor (replace
   `qwenpaw` with your container name):

   ```sh
   docker exec --user 0 qwenpaw supervisorctl -c /etc/supervisor/conf.d/supervisord.conf stop app
   ```

   Continue only after this succeeds. Keep the container and Supervisor running.
   Stop any separately managed consumers of the same dependency environment too.
3. Run the saved worker command inside the container. Replace both placeholders
   below with the exact absolute paths from `instructions`:

   ```sh
   docker exec --user 0 qwenpaw /absolute/python -I -S /absolute/operation/worker/dependency_worker.py
   ```

   The retained worker applies the approved plan and resumes plugin installation.
   It does not start a backend for this managed operation.
4. After the worker exits successfully, restart through Supervisor:

   ```sh
   docker exec --user 0 qwenpaw supervisorctl -c /etc/supervisor/conf.d/supervisord.conf start app
   ```

If maintenance fails, keep `app` stopped while inspecting the retained
`operation.json` error and transaction journal. A confirmed safe rollback
preserves or restores the old environment; restarting through Supervisor is
then safe, although the requested upgrade has not completed. For
`DEPENDENCY_REPAIR_REQUIRED`, keep every consumer stopped and recover using
the same retained worker; resolve any reported recovery problem before starting
the backend. Preserve the operation directory, including its plan, backups,
source, and worker. Never edit `operation.json`, remove repair markers, or run
`pip` behind the transaction.

For other Supervisor deployments, use their actual configuration path and
program name in the same stop/worker/start sequence. Other service managers
must likewise keep the backend stopped until maintenance or recovery safely
completes. Use the original service manager to start it afterward.

## Explicit managed dependency generations

Source/PyPI/venv installations keep their existing defaults. Desktop continues
to use its runtime manifest; this opt-in policy cannot override it. An
administrator can provide an absolute candidate JSON file:

```json
{
  "base_id": "sha256:immutable-image-or-environment-build-digest",
  "base_sites": ["/opt/runtime/lib/python3.13/site-packages"],
  "overlay_root": "/srv/qwenpaw-dependencies",
  "legacy_sites": ["/srv/previous-python-packages"]
}
```

Change `base_id` when the base changes. Use a private control directory outside
program resources and plugin sources; its files and parent must not be writable
by other users (protect Windows ACLs as well). Policies in one control directory
share a low-frequency lock, including before the policy file exists. Each
application should use its own control directory. Keep the service's real Python,
working/secret directories and `QWENPAW_DEPENDENCY_STATE_DIR` during maintenance.

```sh
qwenpaw plugin dependency-environment prepare /srv/control/candidate.json \
  --active-policy /srv/control/active.json \
  --plugin-dir /srv/qwenpaw/plugins \
  --requirements /srv/control/additional-requirements.txt
```

`--plugin-dir` is repeatable; disabled plugins are included. Missing declarations,
unsupported syntax, unavailable sources and incompatible base versions fail
explicitly. Existing direct plugin URL/extras limits remain; host metadata keeps
its existing transitive extras/marker handling. Approved `--index-url` directives
are retained; conflicting indexes are refused. Do not derive the additional
requirements by choosing one copy from an ambiguous `pip freeze`. Supply a full
administrator-approved list, or an explicit empty file acknowledging that extra
legacy packages stay in a separate notebook/script environment.

Prepare returns a review report under a new generation without changing active
policy or deleting old files. It uses existing wheel validation/publication and
clean plugin probes. Even a repair with the same base gets a new generation.
The base must contain installed host distribution metadata.

If package import is already blocked, use the trusted absolute script directly:

```sh
/opt/runtime/bin/python -I -B -S /opt/runtime/lib/python3.13/site-packages/qwenpaw/plugins/dependency_environment.py \
  prepare /srv/control/candidate.json --active-policy /srv/control/active.json \
  --plugin-dir /srv/qwenpaw/plugins --requirements /srv/control/additional-requirements.txt
```

Stop the host, all its workers and every external consumer of the old private
directories through their original service managers. Framework leases cannot
prove arbitrary notebook/script shutdown. Shared read-only base readers from
independent applications need not stop. The CLI `activate` command prints an
independent command and exits so its own host lease cannot block maintenance:

```sh
/opt/runtime/bin/python -I -B -S /opt/runtime/lib/python3.13/site-packages/qwenpaw/plugins/dependency_environment.py \
  activate /absolute/generation/prepared.json \
  --active-policy /srv/control/active.json --consumers-stopped
```

`--consumers-stopped` records the administrator's shutdown declaration; actual
readers still block activation. The report is revalidated, then policy is
atomically published with a `.previous` backup. Set startup-only
`QWENPAW_DEPENDENCY_ENVIRONMENT=/srv/control/active.json` and restart through the
original service manager. Startup never installs missing dependencies; preloaded
legacy modules require a clean interpreter. Normal later installs/upgrades and
restarts use current admission rather than an initial file whitelist.

Keep consumers stopped after interruption. Run the same trusted script with
`recover --active-policy /srv/control/active.json` to abort an unpublished switch
or revalidate and complete a published one. It refuses unrelated changes or real
repair markers. For a committed switch, `restore-previous --active-policy
/srv/control/active.json --consumers-stopped` reuses activation validation and
stopped-reader checks for the retained, previously verified generation. Changed
or polluted prior files/sources are refused; restoring a configuration never
proves an originally polluted environment usable. Do not hand-edit policy,
journals or markers. Old directories are retained; automatic reclamation is
outside this workflow. Native launchers, ACLs and service behavior still need
validation on the actual Windows/macOS/Linux deployment.
