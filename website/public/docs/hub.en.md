# QwenPaw Hub

QwenPaw Hub lets a team use QwenPaw on a shared server. Team members sign in at one address, but each person gets their own QwenPaw with separate workspaces, settings, credentials, and conversations.

If you only use QwenPaw on your own computer, keep using the desktop App. Deploy Hub only when you need to manage multiple users on a server.

> QwenPaw Hub is available in non-desktop installations starting with QwenPaw 2.2.0. The desktop edition is the single-user App and does not include Hub. Earlier versions do not have the `qwenpaw hub` command.

> Hub 2.2.0 is an early release intended only for internal teams whose members trust one another. Even with HTTPS and remote access configured, do not operate the current version as a public multi-tenant service for unknown users.

![Hub sign-in page and Terms dialog](https://img.alicdn.com/imgextra/i2/O1CN01hhIGAbMm89B6lBsc_!!6000000006867-2-tps-3330-1772.png)

## When to use Hub

Hub is designed for companies, labs, and small teams that want to run QwenPaw for trusted members on their own server. Administrators can:

- create and manage accounts;
- choose Local or Docker for all user runtimes;
- inspect, stop, and restart runtimes;
- set Docker images, resource limits, and access rules;
- preserve user data and manage backups and upgrades centrally.

Hub is self-hosted software, not a cloud service operated by the QwenPaw team. The server administrator can access the server, database, and backups, so users should only join a Hub run by themselves or an organization they trust.

## Install

Hub requires a non-desktop installation of QwenPaw 2.2.0 or later. We recommend installing the complete Hub dependencies for both Local and Docker runtimes:

```bash
pip install -U "qwenpaw[hub]"
```

If you only use the Local runtime, the base `qwenpaw` package is sufficient and the Docker SDK is not required. Without the complete Hub dependencies, the Docker runtime is shown as unavailable in the administration page.

Confirm that the command is available:

```bash
qwenpaw hub --help
```

## First start

Initialize the first administrator directly in the server terminal:

```bash
qwenpaw hub --init-admin admin
```

The command prompts for the password twice without displaying it, then exits. It only works while Hub has no users, so it cannot add administrators to an existing Hub.

After setting `public_base_url`, you can start the remote Hub directly without placing the browser and Hub on the same network. See **Give a trusted team remote access** below for a complete startup example.

Browser initialization remains available. First, start Hub on the loopback interface:

```bash
qwenpaw hub --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` and register an account. The first registered account becomes the administrator.

If Hub is running on a remote server, reach this page through an SSH tunnel:

```bash
ssh -L 8000:127.0.0.1:8000 user@example.com
```

Then open `http://127.0.0.1:8000/` on your own computer.

> Use a strong password for the first administrator. After adding other administrators, always keep at least one administrator account that can sign in.

## Choose a runtime backend

Open **System Settings → Runtime** and select Local or Docker. The administrator manages this choice for the whole Hub; regular users do not need to work with ports, containers, or host paths.

|                   | Local                                    | Docker                                      |
| ----------------- | ---------------------------------------- | ------------------------------------------- |
| Best for          | Internal teams and quick deployments     | Long-running deployments with resource caps |
| Runtime           | One host process per user                | One container per user                      |
| Requirements      | Native OS process isolation is available | Docker can run Linux containers             |
| Resource limits   | Depend on the host                       | CPU, memory, and process limits             |
| User data storage | Hub data directory                       | Hub data directory, mounted into containers |

### Local

Local uses the QwenPaw and Python environment installed on the host:

- Linux requires an installed and working Bubblewrap (`bwrap`);
- macOS requires a working system `sandbox-exec`;
- Windows requires Windows 10 1507 or later and Hub must run as Administrator.

Hub checks the required isolation before starting a user runtime. If the check fails, it does not fall back to an ordinary unsandboxed process.

### Docker

Docker requires Hub to access a Docker Engine that runs Linux containers. Windows and macOS normally provide this through Docker Desktop.

Administrators can use an official image or provide a custom image reference. For an image that exists only on the host, set the pull policy to `never`. The default resource limits are:

| Resource   | Default  |
| ---------- | -------- |
| CPU        | 2 cores  |
| Memory     | 4096 MiB |
| Processes  | 1024     |
| `/dev/shm` | 512 MiB  |

Changing the backend, image, or limits does not interrupt a running runtime. Restart the runtime to apply new settings; use **Rebuild** when moving to a different image version.

The current Docker limits are one administrator-defined policy applied to all containers. Hub does not yet support different quotas per user, resource-usage accounting, multi-node capacity scheduling, or autoscaling. Local also does not provide the same resource controls as containers.

![Local/Docker backend selector in System Settings](https://img.alicdn.com/imgextra/i3/O1CN01IJbgQoGjpaL6lBso_!!6000000000707-2-tps-3330-1784.png)

## Give a trusted team remote access

When internal members need to connect from other devices or networks, place Hub behind an HTTPS reverse proxy and set `public_base_url` to the address they open in their browsers.

Create `hub.yaml`:

```yaml
version: 1

control_plane:
  public_base_url: https://qwenpaw.example.com
  registration:
    mode: closed
    default_role: user

runtime:
  provisioner: local

capacity:
  max_running_runtimes: 20
```

Then start Hub:

```bash
qwenpaw hub \
  --host 0.0.0.0 \
  --port 8000 \
  --force-public \
  --config hub.yaml
```

`--force-public` allows Hub to listen on an external address; it does not configure TLS. Do not expose unencrypted HTTP directly to an untrusted network.

An external listener only enables remote access for trusted members. It does not mean Hub is ready for open registration or operation as a public service. HTTPS, login rate limits, and IP blocking protect the entry point, but they do not strengthen kernel isolation between user runtimes.

When you pass `--config`, the YAML file is the configuration source for that start and overwrites corresponding settings saved through the admin panel. To manage settings only through the panel later, start Hub without `--config`.

### Reverse-proxy requirements

The reverse proxy must:

- forward requests to the Hub listener;
- preserve the correct host and scheme;
- support WebSocket Upgrade;
- use appropriate caching for the HTML entry point and hashed static assets.

`public_base_url` also determines callback URLs for OpenRouter, MCP, and other OAuth integrations, so it must match the address users open in their browsers.

## Manage users

Registration uses `control_plane.registration.mode`: `open`, `invite`, or `closed`. On the first startup after upgrading, Hub automatically migrates legacy database settings while preserving registration policy, users, runtimes, and credentials. YAML files using `registration.enabled` remain readable with a deprecation warning; Hub does not rewrite the file. If both fields appear in the same configuration, `mode` takes precedence.

For an internal team, disable self-registration and create accounts in **User Management**. If trusted members need to register themselves, restrict access to the entry point and enable registration rate limiting. Do not open registration to unknown users.

After signing in, regular users go directly to their own QwenPaw Console. They can manage their conversations, files, model settings, and integration credentials. They cannot choose the runtime backend, Docker image, or resource limits.

Administrators can see each user's runtime and perform these actions:

| Action         | Result                                                   |
| -------------- | -------------------------------------------------------- |
| Stop           | Stops the process or container; the user can start later |
| Disable start  | Stops the runtime and prevents user-initiated startup    |
| Restart        | Starts the runtime with the current global settings      |
| Docker rebuild | Recreates the container with the current image policy    |
| Delete         | Removes the runtime record but preserves data on disk    |

Users can restart a failed or normally stopped runtime from their personal page. After an administrator disables startup, only an administrator can restore it.

![Personal runtime status and restart action](https://img.alicdn.com/imgextra/i2/O1CN01q71ewupZntB6lRUM_!!6000000000685-2-tps-3332-1770.png)

## Where Hub stores data

Hub stores data in `~/.qwenpaw/hub/` by default. If `QWENPAW_WORKING_DIR` is set, it uses `<QWENPAW_WORKING_DIR>/hub/` instead.

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

Stopping, restarting, rebuilding a Docker container, or switching between Local and Docker does not delete user data. Deleting a runtime record also preserves its directories; remove them manually only after confirming that the data is no longer needed.

## Backup and upgrades

Treat the entire `hub/` directory as one backup set. It must include at least:

```text
control.db*
secrets/
runtimes/
```

The database stores accounts, settings, and runtime records. `secrets/` contains keys required to decrypt credentials. `runtimes/` contains user workspaces and private configuration. Backing up only part of this set may not produce a complete recovery.

Before an upgrade:

1. Stop Hub.
2. Back up the complete `hub/` directory.
3. Record the installed QwenPaw version.
4. Upgrade and restart Hub.
5. Verify administrator login, user runtimes, streaming chat, and OAuth integrations.

## Troubleshooting

### Hub refuses to listen on an external address

Run `qwenpaw hub --init-admin USERNAME` on the server, set `public_base_url`, and add `--force-public` when starting Hub. Alternatively, use an SSH tunnel to reach `127.0.0.1` and register the first administrator in a browser.

### Existing runtimes still show Local after selecting Docker

Changing the global setting does not interrupt running runtimes. Restart the relevant runtime and check its backend again.

### A local Docker image fails to pull

Enter the complete `Repository:Tag` shown by `docker image ls` and set the pull policy to `never`.

### Sign-in succeeds, but the personal QwenPaw does not open

Open **Runtimes** and inspect the user's state and latest error. Confirm that the selected Local or Docker backend is available, then try restarting the runtime.

### The page opens, but chat does not keep streaming

Check that the reverse proxy supports WebSocket Upgrade and does not apply an overly short timeout to long-lived connections.

### OAuth callbacks still use `127.0.0.1`

Check the effective `public_base_url`. If Hub starts from YAML, update `hub.yaml` and restart. Otherwise, save the address in the admin panel.

## Security boundary

Hub separates user workspaces, credentials, and processes or containers, but it does not give every user a separate kernel. Local runtimes share the host kernel; Docker runtimes share the Linux kernel used by the Docker Engine.

Local currently uses Linux Bubblewrap, macOS Seatbelt, or Windows AppContainer plus a Job Object. Docker creates one container per user. These mechanisms reduce interference within a trusted team, but they are not a strong multi-tenant boundary for unknown users.

Do not expose the current version to mutually untrusted users, high-risk code, or workloads with strict compliance requirements. Those scenarios require virtual machines, microVMs, dedicated nodes, or another stronger infrastructure boundary.

For long-running use within a trusted team, also configure HTTPS, host and network access controls, monitoring, and regular backups.

Future releases are planned to add resource-usage accounting, Kubernetes support, multi-node scheduling, autoscaling, and stronger tenant isolation. Stay tuned, or read the [contribution guide](/docs/contributing) and help build these capabilities directly.

## Organization models, invitations, and token budgets

Administrators save upstream connections and API keys in **Models**, then configure model display names, access grants, and the organization default. The gateway currently supports the OpenAI Chat Completions protocol. Members select authorized models through the **Hub** provider on the existing model settings page without configuring a key. Upstream addresses, connections, and keys remain private to Hub. Personal providers can coexist with organization models; their requests do not consume Hub budgets or appear in Hub usage reports.

API keys can only be written or replaced; even administrator APIs never return their original values. Refresh before updating connections or models to avoid overwriting another administrator's changes. Key rotation, unpublishing, and access revocation apply to new requests; requests already admitted still settle normally.

Hub supplies organization models without a separate managed-model toggle. Catalog and grant changes take effect on the next access without restarting runtimes. Each runtime receives a dedicated model endpoint and a runtime-specific credential. The endpoint exposes only the catalog and inference, not the management UI or administrator APIs. These model routes are not exposed on the control-plane port, and ordinary Hub login tokens cannot authenticate to the model endpoint.

The model listener never binds to all interfaces. Local runtimes use `127.0.0.1`. Docker Desktop and macOS/Windows container VMs use `host.docker.internal` to reach the host's loopback listener. Native Linux Docker Engine adds a listener on the default Docker bridge's detected private IPv4 gateway, and containers use that exact address. Hub prepares the interfaces required by available runtime backends at startup and persists one shared port. If discovery or binding fails, Hub reports an error instead of falling back to `0.0.0.0`. Runtime startup verifies authenticated connectivity from inside the runtime. After changing Docker networking, restart Hub; configure host networking to allow the container-to-bridge connection without exposing the port externally. Colima deployments must ensure that container DNS resolves `host.docker.internal` through Colima's internal resolver.

An existing runtime without a model credential can continue using personal providers and ordinary runtime APIs. Restart it through Hub to provision organization-model access. Upgrade runtime programs or container images through the normal deployment process; Hub does not retrofit credentials into a running process.

In **Users → Invitation codes**, administrators can generate batches of up to 100 single-use codes, valid for seven days by default. First select invitation registration in **System settings → Access and registration**. Members then redeem a code to choose their username and password; each code creates one ordinary member. Models granted to everyone are inherited automatically, and invitations may add specific model grants and a personal budget. Codes are displayed only once: download them immediately and distribute them yourself. Revoking a batch affects only unredeemed codes.

Administrators can reset ordinary members' passwords in **Users**. The old password and login credentials become invalid immediately; conversations, files, user identity, and the runtime are preserved. Resetting a password does not re-enable a disabled member.

Use **System settings → Organization budget** to set the organization limit, default member limit, and settlement timezone. A member's details can inherit the default, use a custom limit, allow unlimited usage, or pause calls. The overview shows monthly usage, daily trends, and usage by member and model. Organization and member limits both apply to chat, multi-turn tool use, and background calls through the managed gateway. The monthly settlement timezone becomes fixed after the first call.

Admission reserves the model's maximum input window plus its capped output tokens. On completion, Hub settles against upstream usage and returns the difference. A request is rejected when the remaining budget cannot cover the reservation, even if the budget is not exhausted. Before publishing a model with finite budgets, verify its actual input boundary and output-limit parameter. Stream cancellation, missing usage, or a Hub restart can result in conservative charging of the full reservation. Reports distinguish confirmed usage, conservative charges, and in-flight reservations. These statistics cover only Hub-managed calls and are not a provider invoice.
