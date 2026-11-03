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
