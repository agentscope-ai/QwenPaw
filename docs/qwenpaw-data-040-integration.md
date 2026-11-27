# PawApp: QwenPaw-Data package and official Console upgrade

Updated 2026-11-24 on `feat/data-040-integration`.

The Data App uses the coordinated **0.4.1** release from PyPI. The root `uv.lock` pins Host Core, Context, CLI, Skills, Auth and Tracing. The plugin serves the chat embed from the [published Console wheel](https://pypi.org/project/qwenpaw-data-console/0.4.1/) under the QwenPaw origin.

## Prepare and build

```sh
uv sync --frozen --extra qwenpaw-data
QWENPAW_DATA_CONSOLE_VERSION=0.4.1 bash plugins/apps/qwenpaw-data/scripts/update-data-console.sh
npm ci --prefix plugins/apps/qwenpaw-data/ui
npm run build --prefix plugins/apps/qwenpaw-data/ui
```

For a separate managed runtime, set `QWENPAW_DATA_CONTEXT_PYTHON` to the desired virtual environment’s Python and run `plugins/apps/qwenpaw-data/scripts/setup-pypi.sh`. The setup command checks the service entry points before Neo4j and model settings are configured.

The updater extracts `static/chat-embed` and injects the host bridge before the module bundle. `BUILD_INFO` records the source wheel and bridge hashes. `SHA256SUMS` covers the packaged files, including the versioned JavaScript and CSS assets.

## Identity, models and workspace setup

The backend derives a stable Data user and private Data workspace from the authenticated QwenPaw principal and active workspace. Managed Engine and Context share a control-plane database, signing material and a credential encryption key. Context initializes the Auth and Host schema on first boot. The Engine starts after Context receives a loopback port.

For each scoped gateway request, the backend exchanges the derived identity for a short-lived workspace token at Data Auth. First use provisions the private workspace in managed mode. Data Auth checks current membership on subsequent exchanges. A disabled account or revoked membership stays denied. The iframe uses QwenPaw authorization on the same origin and reloads when host credentials or workspace change.

For external deployments, set both `QWENPAW_DATA_ENGINE_MODE` and `QWENPAW_DATA_CONTEXT_MODE` to `external`. Set their respective `*_URL` values, `QWENPAW_DATA_AUTH_URL` and the server-side `QWENPAW_DATA_SERVICE_SECRET`. Engine, Context and Auth must use the same identity plane and compatible credential encryption. Provision the derived user, workspace and membership in that plane. A mixed managed/external installation returns HTTP 503 for scoped requests.

The official embed serves analysis and DataBridge. The old `context-console/index.html` entry preserves the query and hash and defaults to `#/data-source`. The app ZIP ships one copy of the Console.

| Setting | Behavior in 0.4.1 |
| --- | --- |
| Analysis and summaries | Analysis inherits the selected Main Chat workspace model. Summaries normally follow analysis. Explicit supported PawApp choices are resolved when a turn starts. |
| DataBridge LLM and embedding | Configure a provider in the Data Console and select it for DataBridge. The released Context API accepts the workspace token for this operation. Its per-request model override requires a separate service credential. |
| Saved pre-release DataBridge override | Explicit `inherit` or `host` blocks chat with HTTP 409. Read `GET /api/qwenpaw-data/model-settings`, preserve the returned `settings` object and revision, change only `databridge` to `{"source":"local"}`, then PUT the settings object to the same URL with the same workspace selected. |
| Graph routing | Provision the workspace's graph connection before using graph-backed APIs, including SQL execution. The managed service's configured Neo4j connection is bound to the reserved legacy service workspace. A newly created private workspace starts with graph provisioning pending. |
| Legacy operator configuration | Saved settings generate startup files for managed services. Changes to a workspace model are made in Data Console. The operator form can test explicit provider credentials from the QwenPaw host. |

## Tool compatibility

Domain listing uses the Context metadata API. `qwenpaw_data_search_context` returns metric and dimension evidence labeled `metadata_context`. `qwenpaw_data_explore_entity` exposes the same lookup and labels its limitations. Deep relationship traversal remains a gap. SQL execution uses `/api/v1/rdb/execute_sql` and requires a registered datasource and a result limit between 1 and 1000.

Server-side IM and internal tools use the reserved service identity in managed mode. Multi-user IM isolation requires separate migration and verification.

## Verification and rollout

The local acceptance test used an installed PawApp ZIP, QwenPaw authentication, clean PyPI environments, the official embed in Chrome, and a loopback Neo4j instance. It covered these paths.

- Sign in and open analysis or an old DataBridge bookmark. An expired host bearer received HTTP 401 and a valid login restored access.
- Create a session and datasource in workspace A. Reads in A succeeded, reads in B returned HTTP 404, and switching back restored access. A scoped DataBridge model selection was also isolated across A → B → A.
- Register a test graph for A and execute SQL on its registered SQLite datasource. The sum returned the expected value of 42.
- Complete an analysis turn with a local OpenAI-compatible provider selected in Main Chat. Read the live event stream and reconnect with a saved sequence number to replay subsequent persisted events.

Before a production rollout, verify the deployment's model provider and workspace backend, generated artifact download, representative semantic metadata, and graph provisioning for its workspaces. The acceptance run used the local workspace backend. External services need their own end-to-end check. The upstream Auth service has a development provisioning queue for tenant administrators. The standalone managed PawApp exposes only its private token exchange. [Upstream workspace provisioning](https://github.com/agentscope-ai/QwenPaw-Data/blob/v0.4.1/packages/qwenpaw-data-auth/README.md)

This branch was exercised on QwenPaw 2.3.0b1 and merged onto subsequent `main` (latest merge covers `origin/main` at `2b4e13e3a`). The plugin carries the published marketplace app's 1.0.4 version and historical host range; assign a new app version and validate the intended host range before marketplace publication.

Existing installations also need an ownership migration or archive plan. Stable hashed Data user IDs are retained, but sessions and sources in the old default workspace are not automatically moved into new private workspaces. Rehearse the migration with a database copy and keep the previous plugin, lockfile, Console snapshot and compatible database backup together for rollback.
