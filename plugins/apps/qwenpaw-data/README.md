# QwenPaw-Data

**Self-Evolving, Graph-Grounded Agentic BI at Enterprise Scale**

Source: https://github.com/agentscope-ai/QwenPaw-Data

[中文 README](./README_ZH.md)

QwenPaw-Data is a native QwenPaw application. Its frontend is mounted at
`/apps/qwenpaw-data`, its backend is registered under `/api/qwenpaw-data`, and its
context service is private to the backend.

## What is QwenPaw-Data?

[QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data) brings autonomous,
graph-grounded data analysis into the QwenPaw workspace so
users can ask business questions in natural language and get traceable,
artifact-rich answers backed by real enterprise data.

## Screenshots

<p align="center">
  <img src="https://raw.githubusercontent.com/agentscope-ai/QwenPaw/main/plugins/apps/qwenpaw-data/assets/screenshots/cm-graph.png" alt="Metadata graph visualization" width="900" />
  <br/>
  <em>Metadata Graph: semantic model, dimensions, metrics, and lineage</em>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/agentscope-ai/QwenPaw/main/plugins/apps/qwenpaw-data/assets/screenshots/analysis-result.png" alt="End-to-end analysis result" width="900" />
  <br/>
  <em>End-to-end analysis: natural language question → governed SQL → traceable answer</em>
</p>

## Core idea

Enterprise data analysis is open-ended, ambiguous, and constantly evolving. A
useful data agent must answer three questions on every task:

- **What facts to use**: business concepts, metrics, dimensions, tables, lineage,
  and historical context.
- **How to analyze**: reusable analytical methodology instead of ad-hoc reasoning
  for every request.
- **How to run**: a controllable runtime for long-horizon, artifact-centric
  workflows.

QwenPaw-Data implements this through three collaborative layers:

| Layer | Role | What it manages |
| --- | --- | --- |
| **DataBridge** | Evidence grounding | Metadata graph, knowledge graph, semantic config, data sources, and task traces. |
| **Skill-Hub** | Method orchestration | Reusable analytical skills from coarse routing down to atomic SQL, visualization, and report generation. |
| **Host** | Execution control | DAG planning, tool invocation, artifact registry, and recovery. |

## End-to-end walkthrough

A typical request such as *"check out MAU of product X"* flows through the
following stages:

1. **Plan.** Host consults Skill-Hub to route the request and decompose it into a
   DAG: identify the metric, fetch data, compute MAU, and summarize findings.
2. **Ground.** DataBridge resolves "MAU" and "product X" through the semantic
   layer, mapping them to the `dws_gaap_di` table and the right filters.
3. **Execute.** Host runs governed SQL against the registered datasource and
   registers the result as an artifact.
4. **Report.** A final answer is assembled with methodology, source links, and
   coverage notes — everything in the chat pane.
5. **Evolve.** Traces, feedback, and confirmed definitions feed back into
   DataBridge and Skill-Hub for the next similar question.

## Runtime shape

```text
Embedded QwenPaw-Data Console
  -> /api/qwenpaw-data/engine/* -> analysis engine
  -> /api/qwenpaw-data/config  -> DataBridge model and Neo4j settings
  -> linked Context console
     -> /api/qwenpaw-data/context/* -> DataBridge context service
```

The PawApp backend proxies service requests and supplies service tokens.
Managed services use dynamic loopback ports; external services use their
configured endpoints.
QwenPaw-Data explicitly enables the PawApp standard capabilities; existing PawApps
that do not opt in receive no additional chat, storage, toast, or notify routes.

## Quick start (recommended: PyPI)

The fastest way to run the QwenPaw-Data app without a `QwenPaw-Data` source
workspace is to install the runtime packages from PyPI into the same Python
environment as QwenPaw.

```bash
pip install "qwenpaw[qwenpaw-data]"
```

Or use the convenience script if you want to pin compatible versions:

```bash
./plugins/apps/qwenpaw-data/scripts/setup-pypi.sh
```

Then start QwenPaw and enable the QwenPaw-Data app. The PawApp lifecycle will
auto-detect the PyPI packages and start managed Context and analysis engine
services on dynamic loopback ports.

```bash
qwenpaw app
```

> This path is recommended for users who only need the QwenPaw-Data app and already
> have their own Neo4j / PostgreSQL infrastructure, or who want to try the app
> without demo data.

### PyPI + docker-compose demo data

If you also want the bundled GAAP demo data (Neo4j graph + PostgreSQL
 datasource), start the infrastructure containers and run QwenPaw in external
context mode:

```bash
cd plugins/apps/qwenpaw-data
cp .env.example .env
docker compose up -d neo4j postgres context seed

# in another terminal
QWENPAW_DATA_CONTEXT_MODE=external \
QWENPAW_DATA_CONTEXT_URL=http://127.0.0.1:8765 \
QWENPAW_DATA_CONTEXT_TOKEN=qwenpaw-data-demo-token \
qwenpaw app
```

This is the **recommended one-shot demo** path: you get a fully seeded graph
and datasource without compiling QwenPaw inside Docker.

## Local package setup

The source workspace defaults to `~/dev/QwenPaw-Data`. Its isolated
`.venv` contains editable installs of `qwenpaw-data-context`, `qwenpaw-data-host-core`,
`qwenpaw-data-cli`, and `qwenpaw-data-skills` so their dependency versions do not alter
QwenPaw's environment.

```bash
./scripts/setup-dev.sh
cd ui && npm install && npm run build
```

The UI is shipped as a browser-native ES module. Its Vite configuration
replaces `process.env.NODE_ENV` at build time so bundled dependencies do not
leak the Node-only `process` global into the QwenPaw Console.

The full Data console is a reviewed vendor snapshot tracked under
`ui/public/data-console/`; normal builds, CI, and users do not need access to
QwenPaw-Data-Cloud. Authorized maintainers or coding agents refresh that snapshot
with `scripts/update-data-console.sh`, then review and publish the resulting diff.
The Context console is built separately from the public QwenPaw-Data source by
`scripts/sync-context-ui.sh`.

`setup-dev.sh` runs the QwenPaw-Data workspace sync and creates ignored development
links under this app. Set `QWENPAW_DATA_SOURCE_DIR` to use another checkout. At
runtime, use `QWENPAW_DATA_CONTEXT_MODE=external` with `QWENPAW_DATA_CONTEXT_URL` and
`QWENPAW_DATA_CONTEXT_TOKEN` only when another process manager owns the service.

To build, stage, and install the app into a local QwenPaw instance in one
step, run `./scripts/dev.sh`. `QWENPAW_BIN` and `QWENPAW_WORKING_DIR` select
the target instance. The installer targets `127.0.0.1:8089` by default;
override it with `QWENPAW_HOST` and `QWENPAW_PORT` when needed.

## Docker compose demo

A one-shot demo stack is available for users who want Neo4j + PostgreSQL +
seeded GAAP data without a local `QwenPaw-Data` source workspace. The stack
uses the `qwenpaw-data-context` and `qwenpaw-data-cli` packages from PyPI.

```bash
cd plugins/apps/qwenpaw-data
cp .env.example .env
docker compose up -d
```

This starts:

- `neo4j` — graph store (port 7687 / 7474)
- `postgres` — GAAP demo datasource (port 55432)
- `context` — external context service (port 8765)
- `seed` — injects the bundled demo SQL, imports the semantic workbook, and weaves it into Neo4j
- `qwenpaw` *(optional)* — builds the full QwenPaw image from the repo root

If the `qwenpaw` service is too heavy or fails to build (e.g. ACR base images
unavailable), start only the infrastructure and run QwenPaw locally:

```bash
docker compose up -d neo4j postgres context seed
# in another terminal, from the QwenPaw repo root
QWENPAW_DATA_CONTEXT_MODE=external QWENPAW_DATA_CONTEXT_URL=http://127.0.0.1:8765 QWENPAW_DATA_CONTEXT_TOKEN=qwenpaw-data-demo-token qwenpaw app
```

To re-run the seed container manually (for example after wiping Postgres
volumes):

```bash
./scripts/init-demo.sh
```

## Configuration

The 0.3 runtime integration opens the embedded **Data Console**. Its settings
menu has two configuration pages; the separate **Data Bridge** shortcut opens
the Context console's data-source page. These replace the old PawApp
**Configure** instructions.

| What to configure | Where to configure it |
| --- | --- |
| Analysis agent providers, credentials, and active models | **Settings → Agent Configuration** in the Data Console |
| DataBridge semantic-service LLM, embedding model, and Neo4j graph store | **Settings → DataBridge Configuration** in the Data Console |
| SQL datasources such as PostgreSQL and MySQL | **Data Bridge → Data Sources** in the linked Context console |

DataBridge Configuration includes **Test connection**, **Save**, and
**Save & restart Context service**. Its LLM is used for semantic weaving and
document ingestion. Configure the analysis chat model separately in
Agent Configuration.

Register SQL connection details in Data Sources, test the connection, and
select the registered datasource when starting an analysis. DataBridge stores
these credentials in its semantic-config registry (`semantic_config.db`),
managed through `/api/semantic-config/datasource`. Saving Neo4j or model
settings does not create a SQL datasource or write SQL credentials to `.env`.

### Saved configuration and runtime files

Saving **DataBridge Configuration** persists the following files under the
QwenPaw working directory (default: `~/.qwenpaw/apps/qwenpaw-data/`):

- `config.json` — the PawApp's DataBridge model and Neo4j settings, host-model
  reuse flags, and the Context service's selected datasource ID. SQL
  credentials remain in DataBridge's registry.
- `.env` — generated Neo4j and model variables (`NEO4J_*`, `OPENAI_*`,
  `LLM_MODEL`, and `EMBED_*`) for the managed Context service.
- `models.json` — the Context service's LLM and embedding settings.

These files do not contain all Data Console settings: Agent Configuration
saves the analysis engine's own model preferences through its API.
On each managed Context service start, the PawApp regenerates `.env` and
`models.json` from `config.json`. Model changes are also sent to a running
Context service; use **Save & restart Context service** to apply Neo4j changes
in managed mode. External service restarts are handled by their operator.

When **Reuse the model configured in QwenPaw** is enabled for DataBridge,
saving or starting the managed Context service refreshes the snapshot from
the host's usable active model. Embedding reuse shares the host provider's
endpoint and credentials while keeping the selected embedding model and
dimension. This is separate from selecting analysis models in
Agent Configuration.

### Environment defaults and overrides

On first initialization, the PawApp seeds empty DataBridge fields from the
environment and can obtain a compatible model default from QwenPaw. After
configuration is saved, the generated app `.env` is authoritative for its
managed keys: inherited shell or QwenPaw environment values do not override
saved values, and clearing a managed field removes its previous environment
override. Unrelated environment keys remain unchanged.

Edit saved values through **DataBridge Configuration**; manual edits to the
generated app `.env` are replaced on the next save or managed service start.
For an external Context service, manage its startup environment in that
deployment. SQL datasource credentials use the datasource registry in either
mode.

### Configuration verification (TC-DATA-04)

Use the current configuration contract when validating the 0.3 integration:

1. Save DataBridge model and Neo4j settings. Verify `config.json`, the populated
   Neo4j/model variables in `.env`, and LLM/embedding settings in `models.json`.
   SQL datasource variables are not expected in `.env`.
2. Enable host-model reuse, switch to another compatible active host model,
   and save or restart the managed Context service. Verify the model snapshot
   refreshes and saved settings survive the restart.
3. Register and test a SQL datasource through Data Sources. Verify the
   registration persists after a Context service restart, then select it in
   the Data Console and run a read-only query against a test database.
4. Verify analysis model selection separately in Agent Configuration.

The older expectation that saving Neo4j/LLM settings also generates SQL
datasource variables in `.env` does not apply to this configuration contract.

## Runtime health and local services

- Activate a language model in QwenPaw's **Settings → Models** so that
  QwenPaw-Data can bootstrap a first-run default. You can override the model
  later in **DataBridge Configuration**. Select the analysis agent's active
  models in **Agent Configuration**.
- QwenPaw-Data declares the Context API, Graph Store, and discovered data
  sources through the PawApp dependency contract. The Data sources page shows
  readiness, capability impact, remediation, and the actions that are actually
  available.
- The app does not invoke Docker or provision Graph Store/data-source
  infrastructure. Those resources are external dependencies and receive
  read-only readiness checks. Local lifecycle and diagnostics belong to the
  `qwenpaw-data-cli` package; production lifecycle belongs to the deployment's
  service owner.

Missing host configuration is reported through the PawApp SDK as a structured
service-unavailable error. QwenPaw-Data turns `MODEL_NOT_CONFIGURED` into an
actionable UI message instead of displaying a generic HTTP 500.

The app also opts into the generic `qwenpaw_data_dependency_status` and
`qwenpaw_data_dependency_action` tools. The agent can inspect the same control plane
as the UI and request only pre-registered actions; the host remains responsible
for tool governance and audit.

### Local infrastructure quick reference

Service endpoints are environment-driven with local defaults; nothing is
hardcoded. `qwenpaw-data-context` resolves them at startup (see
`packages/qwenpaw-data-context/src/context_manager/config.py` and
`packages/qwenpaw-data-context/README.md` in the QwenPaw-Data workspace):

| Dependency | Configuration | Local default |
| --- | --- | --- |
| Graph Store (Neo4j) | **DataBridge Configuration**; an external deployment manages `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | `bolt://localhost:7687` |
| Data sources (PostgreSQL / MySQL / ODPS / ...) | registered through the DataBridge semantic-config layer (`/api/semantic-config/datasource`), not read from `.env` | none |
| DataBridge LLM / Embedding | **DataBridge Configuration**; environment defaults use `OPENAI_API_KEY`, `OPENAI_BASE_URL`, `LLM_MODEL`, `EMBED_*` | — |
| Analysis agent models | **Agent Configuration** in the Data Console | — |

Local lifecycle, by owner:

- **Graph Store (Neo4j)** — owned by the QwenPaw-Data workspace tooling:
  `scripts/start_databridge.sh` reuses a Neo4j that is already reachable on
  the bolt port, otherwise it runs
  `packages/qwenpaw-data-context/docker-compose.yml`. This requires a running
  Docker daemon (for example `colima start`) and `NEO4J_PASSWORD` in the
  workspace `.env`.
- **Diagnostics** — `qwenpaw-data doctor --json` reports Docker, Neo4j, DataBridge
  API, and model-configuration readiness with remediation hints. It is
  read-only.
- **Data-source servers** — external infrastructure. QwenPaw Data packages manage
  their registration and readiness, never their provisioning.

The standalone DataBridge API (`127.0.0.1:8765`) is only used when running
QwenPaw-Data outside QwenPaw. Inside QwenPaw, the PawApp lifecycle manages a
private context service on a dynamic loopback port, so a `doctor` failure on
8765 alone does not affect this app.

## Package responsibilities

- `qwenpaw-data-context`: context APIs, semantic configuration, and graph memory.
  It also owns the local Graph Store definition
  (`docker-compose.yml`) and the datasource registrations in the
  semantic-config layer.
- `qwenpaw-data-host-core`: shared analysis runtime and orchestration contracts.
  It does not touch infrastructure.
- `qwenpaw-data-skills`: app-provided data analysis skills.
- `qwenpaw-data-cli`: standalone lifecycle and diagnostic tooling (`doctor`,
  `datasource`, `semantic`); it is the only QwenPaw Data package intended to own
  local infrastructure commands. Data-source servers themselves remain
  external infrastructure.

QwenPaw remains the only UI/backend process the user starts in managed mode.
The PawApp lifecycle starts and stops both the Context service and the
`qwenpaw-data-host-core` analysis engine. The embedded Data Console talks to
that engine through the PawApp gateway; `/data` routes QwenPaw channel
conversations to the same engine through the channel bridge.
