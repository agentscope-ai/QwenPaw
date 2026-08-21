# Deploying and Managing QwenPaw Hub

QwenPaw Hub is a unified entry point for self-hosted, multi-user deployments. An administrator operates one Hub while every account receives a separate QwenPaw runtime with its own workspace, configuration, credentials, and conversations.

Hub does not replace or alter the single-user QwenPaw App. Personal devices can continue to run `qwenpaw app`; use `qwenpaw hub` only when multiple accounts need centralized management.

> **Important security boundary: Hub does not give every user a separate kernel.** Local runtimes use Bubblewrap namespaces on Linux, Seatbelt on macOS, and AppContainer plus a Job Object on Windows. All three are process sandboxes that share the host kernel. Docker runtimes share the Linux kernel used by their Docker Engine. On Docker Desktop this is normally the Docker Linux VM kernel, but it is still not one kernel per tenant. For mutually untrusted users or higher-risk multi-tenant deployments, add virtual machines, dedicated nodes, microVMs, or another stronger infrastructure boundary outside Hub.

![Hub sign-in page and Terms dialog](https://img.alicdn.com/imgextra/i2/O1CN01hhIGAbMm89B6lBsc_!!6000000006867-2-tps-3330-1772.png)

## Hub and the single-user App

| Capability | `qwenpaw app`                                | `qwenpaw hub`                                   |
| ---------- | -------------------------------------------- | ----------------------------------------------- |
| Use case   | Personal device, one user                    | Self-hosted, multiple users                     |
| Identity   | Local instance authentication                | Central Hub accounts                            |
| Runtime    | One local process                            | One managed runtime per account                 |
| Data       | `~/.qwenpaw` by default                      | Separate runtime directories under the Hub root |
| Operations | QwenPaw Console                              | Hub admin center and personal Console           |
| Backend    | Local process or manually operated container | Administrator-selected Local or Docker backend  |

After signing in, a regular user is proxied to their own QwenPaw Console. Administrators can also manage accounts, runtimes, access security, and Docker policy.

## Requirements

- Install the current QwenPaw release and a supported Python version.
- Include the built Console assets in the package, or build them in a source checkout.
- For Local, provide the native isolation mechanism listed below.
- For Docker, allow the Hub process to access a Docker Engine that runs Linux containers.
- For external access, use a trusted network or an HTTPS reverse proxy.

## Install and initialize

Install the Hub optional dependencies from PyPI:

```bash
pip install "qwenpaw[hub]"
```

The `hub` extra includes the Docker SDK required by the Docker backend. A normal `pip install qwenpaw` does not install it and does not change the existing QwenPaw App dependency path. Install the extra in a Hub environment even if you initially select Local, so the admin center can probe and report Docker backend availability.

For an existing QwenPaw environment, install the extra in place and verify that the Hub command is present:

```bash
pip install -U "qwenpaw[hub]"
qwenpaw hub --help
```

Hub initially listens on loopback and refuses public exposure before an administrator exists. Start it locally:

```bash
qwenpaw hub --host 127.0.0.1 --port 8000
```

For a remote server, create an SSH tunnel and open `http://127.0.0.1:8000/`:

```bash
ssh -L 8000:127.0.0.1:8000 user@example.com
```

The first registered account becomes an administrator. Use a unique, strong password and always retain at least one enabled administrator.

## Configuration

This example selects Local and enables registration after initialization:

```yaml
version: 1

control_plane:
  public_base_url: https://qwenpaw.example.com
  registration:
    enabled: true
    default_role: user
  security:
    ip_blacklist: []
    trusted_proxy_ips:
      - 127.0.0.1/32
    login_rate_limit:
      enabled: true
      max_attempts: 10
      window_seconds: 300
      block_seconds: 900
    registration_rate_limit:
      enabled: true
      max_attempts: 5
      window_seconds: 3600
      block_seconds: 3600
  proxy:
    max_request_size_mb: 1024
    request_idle_timeout_seconds: 60
    response_header_timeout_seconds: 300
    connect_timeout_seconds: 10
    websocket_max_message_size_mb: 16

runtime:
  provisioner: local

capacity:
  max_running_runtimes: 20
```

### YAML and admin-panel precedence

Configuration ownership is determined on every startup:

1. With `--config hub.yaml`, Hub validates the complete YAML configuration and writes it to the database on every startup.
2. Without `--config`, Hub uses the configuration stored by the admin panel.
3. Admin-panel changes are written to the database immediately.
4. A later startup with `--config` overwrites those database values with YAML again.

This supports either YAML-managed or panel-managed deployments. If YAML remains authoritative, keep it in secure configuration management and remember that panel changes are temporary until the next YAML-backed restart.

The `control_plane.proxy` limits bound traffic forwarded to personal runtimes. Request size and idle limits apply only while uploading a request body. The response-header timeout ends once the runtime starts its response, so SSE, agent streams, and streamed downloads remain open until either peer disconnects. All values can be overridden in YAML; sizes are measured in MiB and timeouts in seconds.

## Public startup and OAuth base URL

After creating an administrator and setting `public_base_url`, explicitly allow a public listener:

```bash
qwenpaw hub \
  --host 0.0.0.0 \
  --port 8000 \
  --force-public \
  --config hub.yaml
```

`--force-public` does not provide TLS. Put an HTTPS reverse proxy in front of Hub on untrusted networks. `public_base_url` must exactly match the browser-facing scheme, host, and port because OpenRouter, MCP, and other integrations use it to construct OAuth callbacks.

## User experience and runtime ownership

Users must read and accept the self-hosted Terms before signing in or registering. Hub then finds or creates the user's personal runtime and proxies requests to its Console.

Regular users can use their Console, manage their own model and integration credentials, change their password, and restart a failed or normally stopped runtime. They cannot select the backend, Docker image, or resource limits.

Each account maps to one tenant and one default runtime. The admin list displays the username first and the immutable user ID second. Search and owner filters accept both values; if an account is deleted, historical runtimes fall back to the user ID.

![Personal runtime status and restart action](https://img.alicdn.com/imgextra/i2/O1CN01q71ewupZntB6lRUM_!!6000000000685-2-tps-3332-1770.png)

### Switching backends

Changing the global backend does not interrupt a running runtime. Restarting a runtime stops its old backend and starts it with the current global policy. After switching from Local to Docker or back, restart the relevant runtimes and verify the backend in the list.

## Local backend: process isolation

Local starts QwenPaw on the host but never falls back to an ordinary unsandboxed process. It performs platform isolation probes first and refuses startup when the required boundary is unavailable.

| Platform | Isolation                 | Requirements                                                                                                            |
| -------- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| Linux    | Bubblewrap                | Executable `bwrap` and the required kernel namespaces                                                                   |
| macOS    | Seatbelt                  | A working system `sandbox-exec`                                                                                         |
| Windows  | AppContainer + Job Object | Windows 10 1507/build 10240 or newer; Hub runs as Administrator; `icacls.exe` and `CheckNetIsolation.exe` are available |

All platforms use a deny-by-default filesystem boundary and expose only required read-only runtime dependencies plus the current tenant's data. Windows uses a kill-on-close Job Object for the complete process tree.

AppContainer normally cannot connect directly to host loopback. While a runtime is active, Hub enables the Windows loopback exemption for its AppContainer SID. The AppContainer then opens an outbound reverse TCP tunnel to Hub, and Hub proxies QwenPaw through that tunnel. Stopping the runtime removes the rule and closes the tunnel. The same rule also lets Windows Local reach other host loopback services, so this is a filesystem and process boundary, not a separate network boundary. Missing privileges, ACL support, AppContainer APIs, Job Object support, rule configuration, reverse-tunnel connectivity, or the real runtime health check causes Local to fail closed.

This is process and filesystem access control, not kernel isolation. Local runtimes share the host kernel and must not be treated as virtual machines, microVMs, or a sufficient boundary for hostile tenants.

![Local/Docker backend selector in System Settings](https://img.alicdn.com/imgextra/i3/O1CN01IJbgQoGjpaL6lBso_!!6000000000707-2-tps-3330-1784.png)

## Docker backend: container isolation

Docker requires an Engine that runs Linux containers. Windows and macOS normally provide this through Docker Desktop, WSL2, or a Linux VM. Each account receives a separate container with these rules:

- publish the service port only on host `127.0.0.1`;
- prevent acquisition of new Linux privileges;
- use an internal boundary token that users cannot override;
- leave restart policy under Hub lifecycle control;
- mount persistent user data from stable host directories.

Containers share the Linux kernel used by the Engine. Container escape risks, Linux kernel vulnerabilities, and Docker daemon permissions remain deployment responsibilities.

### Images and pull policy

| Source                 | Repository                                                              |
| ---------------------- | ----------------------------------------------------------------------- |
| Docker Hub official    | `docker.io/agentscope/qwenpaw`                                          |
| Alibaba Cloud official | `agentscope-registry.ap-southeast-1.cr.aliyuncs.com/agentscope/qwenpaw` |
| Custom                 | A complete administrator-provided image reference                       |

Custom images may be remote or an existing local tag such as `qwenpaw-hub-custom:2026-08`. Select `never` for a local-only tag.

| Pull policy      | Behavior                                   |
| ---------------- | ------------------------------------------ |
| `always`         | Pull before use                            |
| `if_not_present` | Pull only when the image is absent locally |
| `never`          | Use only an existing local image           |

The settings page shows the effective image reference, repository, tag, local status, and digest or image ID. Administrators can pull from the image-detail card and follow task progress. A created runtime records its actual image ID/digest so a mutable tag cannot silently change during an ordinary restart. Rebuild clears the pin and applies the current image policy while preserving user data.

### Resource limits

| Field             | Default | Meaning                       |
| ----------------- | ------- | ----------------------------- |
| `cpu_limit`       | `2.0`   | CPU quota per container       |
| `memory_limit_mb` | `4096`  | Memory limit, minimum 256 MiB |
| `pids_limit`      | `1024`  | Process limit, minimum 64     |
| `shm_size_mb`     | `512`   | `/dev/shm`, minimum 64 MiB    |

Empty CPU, memory, or PID values mean no corresponding limit. `capacity.max_running_runtimes` limits concurrent runtimes across the Hub; it does not create multiple runtimes for one tenant.

![Docker image detail, pull action, and resource limits](https://img.alicdn.com/imgextra/i2/O1CN01M5zUCZUwvZG6nhyY_!!6000000002043-2-tps-3350-1784.png)

## Persistent data

The Hub root defaults to `<QWENPAW_WORKING_DIR>/hub/`, or `~/.qwenpaw/hub/` when `QWENPAW_WORKING_DIR` is unset:

```text
<QWENPAW_WORKING_DIR>/hub/
├── control.db
├── secrets/
└── runtimes/
    └── <runtime-id>/
        ├── working/
        ├── secret/
        ├── backups/
        └── logs/
```

Paths displayed by the admin center are real persistent host paths. Docker mounts `working/` at `/app/working`, `secret/` at `/app/working.secret`, and `backups/` at `/app/working.backups`.

Stopping, restarting, rebuilding, switching backends, or retiring a runtime registration does not proactively delete these directories. This protects against accidental administrative deletion, but it is not a backup.

## Lifecycle and start policy

Hub records observed state, desired state, and start permission separately.

| Action              | Result                                           | User can start it      |
| ------------------- | ------------------------------------------------ | ---------------------- |
| Stop                | Physically stops the process or container        | Yes                    |
| Disable start       | Stops it and reserves startup for administrators | No                     |
| User restart        | Starts with the current global policy            | Only when not disabled |
| Admin start/restart | Starts with the current global policy            | Yes                    |
| Docker rebuild      | Recreates it with current image policy           | Administrator only     |
| Delete              | Retires registration and preserves disk data     | Not applicable         |

Failed runtimes expose a restart action on the personal page. A user refresh cannot override an administrator's “Disable start” decision.

## Accounts and access protection

Administrators cannot change their own role or disable themselves, and Hub prevents any operation that would remove the last active administrator. Regular users cannot rename themselves or change roles; they can only change their password.

For internal teams, disable self-registration and create accounts administratively. If registration is public, enable registration rate limiting. Login and registration limits are tracked separately by client IP. The blacklist accepts IPv4, IPv6, and CIDR values.

Hub trusts `X-Forwarded-For` only when the direct peer is in `trusted_proxy_ips`. Never trust `0.0.0.0/0`, because clients could spoof their address and bypass limits.

## OAuth callbacks

Hub proxies runtime OAuth flows through a browser-reachable callback:

```text
https://qwenpaw.example.com/api/hub/oauth/callback/<runtime-id>/<route>
```

If authorization fails, verify the effective `public_base_url`, reverse-proxy Host/Scheme/WebSocket headers, provider callback policy, runtime ownership, and provider-side account errors. Some MCP servers do not publish OAuth Protected Resource Metadata; configure `auth_endpoint` and `token_endpoint` manually from the service operator's documentation.

## Operations, backup, and upgrades

The admin center provides user/runtime counts, status distribution, backend availability, paginated filters, and sanitized administrative audit events. Production deployments should additionally monitor reverse-proxy and Hub logs, host CPU/memory/disk, Docker health, HTTP latency and errors, WebSocket disconnects, and backup results.

Back up these paths as one consistent set:

```text
<QWENPAW_WORKING_DIR>/hub/control.db*
<QWENPAW_WORKING_DIR>/hub/secrets/
<QWENPAW_WORKING_DIR>/hub/runtimes/
```

The database stores accounts, configuration, runtime registration, and audit events. `secrets/.vault_key` is required to decrypt credentials and system secrets. Before an upgrade, stop Hub, take a consistent backup of the entire root, record the installed version, and then verify administrator login, pagination, runtime proxying, WebSockets, and OAuth callbacks.

## Troubleshooting

- **Public listening is refused:** create an enabled administrator over loopback, set `public_base_url`, and pass `--force-public`.
- **A page remains blank:** verify that `index.html` and every hashed JS/CSS asset return the same deployment version. Do not apply long-lived asset caching to the HTML entry point.
- **Docker is selected but a runtime still shows Local:** restart that runtime so the current global policy is applied.
- **A local image cannot be pulled:** select Custom, enter an existing Repository:Tag from `docker image ls`, and set pull policy to `never`.
- **Personal Console fails to load:** inspect owner, state, backend, and last error. A normal stop is user-restartable; disabled startup requires an administrator.
- **OAuth still uses `127.0.0.1`:** correct the active `public_base_url`. Restart with `--config` for YAML management, or save it in the panel for database management.

## Deployment boundary

QwenPaw Hub is self-hosted software. The operator controls the server, database, backups, and processes and may be able to access data stored by users. Users should sign in only to a Hub operated by themselves or a trusted organization.

QwenPaw runtimes have constrained file, process, device, and network capabilities compared with the full personal App. Local on Linux, macOS, and Windows shares the respective host kernel; Docker shares its Engine's Linux kernel. These controls reduce cross-account interference but do not replace VM-level tenant isolation, host hardening, network boundaries, HTTPS, backup, monitoring, or organizational security policy.
