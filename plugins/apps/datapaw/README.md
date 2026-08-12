# QwenPaw-Data PawApp

**Self-Evolving, Graph-Grounded Agentic BI at Enterprise Scale**

QwenPaw-Data is a native QwenPaw application. Its frontend is mounted at
`/apps/datapaw`, its backend is registered under `/api/datapaw`, and its
context service is private to the backend.

## Runtime shape

```text
QwenPaw-Data UI
  -> app-scoped PawApp SDK
  -> /api/datapaw/*
  -> QwenPaw-Data PawApp backend
  -> dependency status and typed lifecycle control
  -> managed QwenPaw-Data context service
```

The browser does not know the service port or bearer token. It does not call
the legacy plugin globals, a fixed port, or a second request client.
QwenPaw-Data explicitly enables the PawApp standard capabilities; existing PawApps
that do not opt in receive no additional chat, storage, toast, or notify routes.

## Local package setup

The source workspace defaults to `~/dev/QwenPaw-Data`. Its isolated
`.venv` contains editable installs of `datapaw-context`, `datapaw-host-core`,
`datapaw-cli`, and `datapaw-skills` so their dependency versions do not alter
QwenPaw's environment.

```bash
./scripts/setup-dev.sh
cd ui && npm install && npm run build
```

The UI is shipped as a browser-native ES module. Its Vite configuration
replaces `process.env.NODE_ENV` at build time so bundled dependencies do not
leak the Node-only `process` global into the QwenPaw Console.

`setup-dev.sh` runs the QwenPaw-Data workspace sync and creates ignored development
links under this app. Set `DATAPAW_SOURCE_DIR` to use another checkout. At
runtime, use `DATAPAW_CONTEXT_MODE=external` with `DATAPAW_CONTEXT_URL` and
`DATAPAW_CONTEXT_TOKEN` only when another process manager owns the service.

To build, stage, and install the app into a local QwenPaw instance in one
step, run `./scripts/dev.sh`. `QWENPAW_BIN` and `QWENPAW_WORKING_DIR` select
the target instance. The installer targets `127.0.0.1:8089` by default;
override it with `QWENPAW_HOST` and `QWENPAW_PORT` when needed.

## Runtime health and local services

- Configure and activate a language model in QwenPaw's **Settings → Models**
  before using the Analysis chat. A fresh `QWENPAW_WORKING_DIR` intentionally
  contains no provider credentials or active model.
- QwenPaw-Data declares the Context API, Graph Store, and discovered data
  sources through the PawApp dependency contract. The Data sources page shows
  readiness, capability impact, remediation, and the actions that are actually
  available.
- The app does not invoke Docker or provision Graph Store/data-source
  infrastructure. Those resources are external dependencies and receive
  read-only readiness checks. Local lifecycle and diagnostics belong to the
  `datapaw-cli` package; production lifecycle belongs to the deployment's
  service owner.

Missing host configuration is reported through the PawApp SDK as a structured
service-unavailable error. QwenPaw-Data turns `MODEL_NOT_CONFIGURED` into an
actionable UI message instead of displaying a generic HTTP 500.

The app also opts into the generic `datapaw_dependency_status` and
`datapaw_dependency_action` tools. The agent can inspect the same control plane
as the UI and request only pre-registered actions; the host remains responsible
for tool governance and audit.

### Local infrastructure quick reference

Service endpoints are environment-driven with local defaults; nothing is
hardcoded. `datapaw-context` resolves them at startup (see
`packages/datapaw-context/src/context_manager/config.py` and
`packages/datapaw-context/README.md` in the QwenPaw-Data workspace):

| Dependency | Configuration | Local default |
| --- | --- | --- |
| Graph Store (Neo4j) | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` in the workspace `.env` | `bolt://localhost:7687` |
| Data sources (PostgreSQL / MySQL / ODPS / ...) | registered through the DataBridge semantic-config layer (`/api/semantic-config/datasource`), not read from `.env` | none |
| LLM / Embedding | `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`, `EMBED_*` | — |

Local lifecycle, by owner:

- **Graph Store (Neo4j)** — owned by the QwenPaw-Data workspace tooling:
  `scripts/start_databridge.sh` reuses a Neo4j that is already reachable on
  the bolt port, otherwise it runs
  `packages/datapaw-context/docker-compose.yml`. This requires a running
  Docker daemon (for example `colima start`) and `NEO4J_PASSWORD` in the
  workspace `.env`.
- **Diagnostics** — `datapaw doctor --json` reports Docker, Neo4j, DataBridge
  API, and model-configuration readiness with remediation hints. It is
  read-only.
- **Data-source servers** — external infrastructure. DataPaw packages manage
  their registration and readiness, never their provisioning.

The standalone DataBridge API (`127.0.0.1:8765`) is only used when running
QwenPaw-Data outside QwenPaw. Inside QwenPaw, the PawApp lifecycle manages a
private context service on a dynamic loopback port, so a `doctor` failure on
8765 alone does not affect this app.

## Package responsibilities

- `datapaw-context`: context APIs, semantic configuration, and graph memory.
  It also owns the local Graph Store definition
  (`docker-compose.yml`) and the datasource registrations in the
  semantic-config layer.
- `datapaw-host-core`: shared analysis runtime and orchestration contracts.
  It does not touch infrastructure.
- `datapaw-skills`: app-provided data analysis skills.
- `datapaw-cli`: standalone lifecycle and diagnostic tooling (`doctor`,
  `datasource`, `semantic`); it is the only DataPaw package intended to own
  local infrastructure commands. Data-source servers themselves remain
  external infrastructure.

QwenPaw remains the only UI/backend process the user starts. In managed mode,
the PawApp lifecycle starts and stops the context service automatically.

The first migration slice uses QwenPaw's app-scoped chat with QwenPaw-Data context
tools. It does not start a second agent from `datapaw-host-core`. The host-core
task graph, artifacts, and tool-renderer adapter will be added after the
PawApp runtime-hook contract is reviewed, which prevents two agent runtimes
from owning the same chat turn.
