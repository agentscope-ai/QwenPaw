# QwenPaw-Data

**Self-Evolving, Graph-Grounded Agentic BI at Enterprise Scale**

Source: [QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data)

[中文 README](./README_ZH.md)

QwenPaw-Data is a native QwenPaw application. Its frontend is mounted at
`/apps/qwenpaw-data`, its backend is registered under `/api/qwenpaw-data`, and its
context service is private to the backend.

## What is QwenPaw-Data?

[QwenPaw-Data](https://github.com/agentscope-ai/QwenPaw-Data) brings autonomous,
graph-grounded data analysis into the QwenPaw workspace so
users can ask business questions in natural language and get traceable,
artifact-rich answers backed by real enterprise data.

## Session workspace

<p align="center">
  <img src="https://raw.githubusercontent.com/agentscope-ai/QwenPaw-Data/main/assets/qwenpaw-app/session-workspace.png" alt="QwenPaw-Data session workspace showing an analysis result, a CSV artifact, and chat turns" width="900" />
  <br/>
  <em>Session workspace: data analysis, traceable results, and downloadable artifacts alongside chat turns.</em>
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

## From a question to a result

For a seeded GAAP demo, ask **"Show daily GAAP values for product X in March
2026"**. The demo uses `dws_gaap_di`.

1. **Connect and select.** Register and test the datasource in DataBridge,
   then select it in the Data Console. Reload the dataset list and optionally
   select datasets to include with the question. Starting a database alone
   does not register it or import its semantic definitions.
2. **Ground the question.** The agent uses the selected source and DataBridge
   context to identify the metric, date range, and relevant tables. It can
   ask for clarification when the request is ambiguous.
3. **Run the analysis.** The agent uses data-access and analysis tools. Simple
   questions can execute directly; larger analyses can create a task plan and
   use analytical skills. A DAG is not required for every question.
4. **Review and continue.** Inspect the response, business trajectory, and
   available outputs and traces in the session workspace. Download generated
   artifacts or ask a follow-up in the same session.

The exact plan and outputs depend on the question, available data, configured
models, and tools. A completed analysis does not by itself guarantee automatic
updates to business definitions or skills.

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

## Quick start: installed app and Python runtime

App **1.0.3** targets QwenPaw **2.2.2** and was validated with QwenPaw-Data
runtime **0.3.3**. The app ZIP and the Python runtime are separate installations.

1. Install or update the QwenPaw-Data app in QwenPaw's app manager.
2. Install the runtime into the Python environment used by QwenPaw. For the
   validated runtime versions:

   ```bash
   python -m pip install "qwenpaw-data-context==0.3.3" "qwenpaw-data-host-core[service]==0.3.3" "qwenpaw-data-cli==0.3.3" "qwenpaw-data-skills==0.3.3"
   ```

   Alternatively, from a QwenPaw source checkout run
   `./plugins/apps/qwenpaw-data/scripts/setup-pypi.sh`. This installs the
   compatible range `>=0.3.3,<0.4`, rather than pinning exactly 0.3.3.
   If using a separate runtime environment, set
   `QWENPAW_DATA_CONTEXT_PYTHON` to its Python executable before starting
   QwenPaw. The interpreter must be available to the QwenPaw process.
3. Start or restart QwenPaw and enable the app. For a Python installation:

   ```bash
   qwenpaw app
   ```

4. Configure a provider and workspace default model in Main Chat. Data
   analysis inherits that model; summaries and DataBridge follow the analysis
   model. Overrides are optional.
5. Configure DataBridge's Neo4j connection and embedding service, then register
   and test your SQL datasource. Open `/apps/qwenpaw-data`, select the source,
   reload datasets, and send a question.

In managed mode, the app starts the Context service and analysis engine on
private loopback ports. Neo4j and your database server must be available
separately. A running server, a registered datasource, and imported semantic
metadata are separate setup steps.

## Local infrastructure with Docker Compose

From a QwenPaw source checkout, the bundled Compose file can start just Neo4j
and PostgreSQL while the app manages the **0.3.3** Context and Engine services:

```bash
cd plugins/apps/qwenpaw-data
# First setup only; preserve an existing .env.
cp -n .env.example .env
docker compose up -d neo4j postgres
```

With the example defaults, configure Neo4j at `bolt://127.0.0.1:7687` with
user `neo4j` and password `qwenpaw-data-demo`. Register PostgreSQL at
`127.0.0.1:55432`, database `qwenpaw_data_demo`, user `qwenpaw_data`, password
`qwenpaw-data-demo`. Use your `.env` values if you changed them. These addresses
apply when QwenPaw runs on the same host as the published Docker ports.

This starts infrastructure only; it does **not** seed GAAP rows or import
semantic definitions. Existing databases can be registered directly. For
sample assets and semantic import/weave instructions, see the
[QwenPaw-Data examples](https://github.com/agentscope-ai/QwenPaw-Data/tree/v0.3.3/examples)
and [CLI guide](https://github.com/agentscope-ai/QwenPaw-Data/blob/v0.3.3/packages/qwenpaw-data-cli/README.md).

The bundled `context` and `seed` Dockerfiles still pin **0.3.0**. They are a
legacy demo, not the supported 1.0.3 runtime setup. An unqualified
`docker compose up -d` also builds the `qwenpaw` service; it is not optional
unless you explicitly select services. Updating and validating the full demo
stack is separate from this README and packaging change.

For an externally managed Context service compatible with runtime 0.3.3,
set `QWENPAW_DATA_CONTEXT_MODE=external`, `QWENPAW_DATA_CONTEXT_URL`, and
`QWENPAW_DATA_CONTEXT_TOKEN` before starting QwenPaw. The service must expose
runtime model bindings; the app reports an error for incompatible services.
The analysis engine still needs its own runtime unless separately configured
as an external service.

## Development from source

Run these commands from the QwenPaw repository root, with a compatible
QwenPaw-Data checkout available. For release reproduction, use its `v0.3.3`
tag. The scripts require Bash, Python, uv, Node.js, and npm.

```bash
export QWENPAW_DATA_SOURCE_DIR="$HOME/dev/QwenPaw-Data"
cd plugins/apps/qwenpaw-data
./scripts/setup-dev.sh
./scripts/sync-context-ui.sh
(cd ui && npm ci && npm run build)
```

`setup-dev.sh` runs `uv sync --all-packages` in that checkout and creates
ignored links to its isolated `.venv`, source, and skills. It does not build
or install the app UI. `sync-context-ui.sh` builds the public Context console
before the app UI build copies it into `ui/dist/`.

The Data console is a reviewed snapshot tracked under `ui/public/data-console/`.
Normal builds use this snapshot and require no QwenPaw-Data-Cloud checkout.
Maintainers refresh it with `scripts/update-data-console.sh` and review the
resulting diff.

After building the Context console, `./scripts/dev.sh` builds, stages, and
hot-installs the app into an **already running** local QwenPaw instance. Set
`QWENPAW_HOST` and `QWENPAW_PORT` for that instance (defaults:
`127.0.0.1:8089`), and set `QWENPAW_WORKING_DIR` when it uses a custom data
directory. Run the script from the app directory.

## Configuration

The app opens the embedded **Data Console**. **Settings → Agent Configuration**
opens Data settings with **Models** and **Agent behavior** tabs. The separate
**DataBridge Configuration** page configures the shared Context service;
**Data Bridge** opens the linked Context console.

| What to configure | Where to configure it |
| --- | --- |
| Provider credentials and workspace default model | Main Chat model settings |
| Data analysis, summaries, and DataBridge model overrides | **Settings → Agent Configuration → Models** |
| DataBridge semantic-service LLM, embedding model, and Neo4j graph store | **Settings → DataBridge Configuration** in the Data Console |
| Agent iteration and model-retry settings | **Settings → Agent Configuration → Agent behavior** |
| SQL datasources such as PostgreSQL and MySQL | **Data Bridge → Data Sources** in the linked Context console |

DataBridge Configuration includes **Test connection**, **Save**, and
**Save & restart Context service**. Its LLM is used for semantic weaving and
document ingestion. Data analysis inherits the workspace model by default;
summaries and DataBridge inherit the analysis model. Choose an override only
when needed. Embeddings remain a separate shared data-service setting, also
available under **Models → Embedding & data index**.

Register SQL connection details in Data Sources, test the connection, and
select the registered datasource when starting an analysis. DataBridge stores
these credentials in its semantic-config registry (`semantic_config.db`),
managed through `/api/semantic-config/datasource`. Saving Neo4j or model
settings does not create a SQL datasource or write SQL credentials to `.env`.

### Saved configuration and runtime files

Saving **DataBridge Configuration** persists the following files under the
QwenPaw working directory (`<QWENPAW_WORKING_DIR>/apps/qwenpaw-data/`).
Without an override, QwenPaw uses an existing `~/.copaw` directory or
otherwise `~/.qwenpaw`:

- `config.json` — the PawApp's DataBridge model and Neo4j settings, host-model
  reuse flags, and the Context service's selected datasource ID. SQL
  credentials remain in DataBridge's registry.
- `.env` — generated Neo4j and model variables (`NEO4J_*`, `OPENAI_*`,
  `LLM_MODEL`, and `EMBED_*`) for the managed Context service.
- `models.json` — the Context service's LLM and embedding settings.

Model choices are stored as references under `model-bindings/`, scoped to
the authenticated user and workspace. Main Chat provider credentials are
resolved for each new turn and never copied into those references. Advanced
app-specific connections use the Engine preferences API.
On each managed Context service start, the PawApp regenerates `.env` and
`models.json` from `config.json`. Model changes are also sent to a running
Context service; use **Save & restart Context service** to apply Neo4j changes
in managed mode. External service restarts are handled by their operator.

When **Reuse the model configured in QwenPaw** is enabled for DataBridge,
saving or starting the managed Context service refreshes the snapshot from
the host's usable active model. Embedding reuse shares the host provider's
endpoint and credentials while keeping the selected embedding model and
dimension. These advanced shared-service defaults are separate from the
per-turn model choices in **Agent Configuration → Models**.

### Environment defaults and overrides

On first initialization, the PawApp seeds empty DataBridge fields from the
environment. Workspace models are resolved per turn. After
configuration is saved, `config.json` is authoritative for the generated
runtime files and each managed child's environment. Inherited shell or
QwenPaw values do not override saved settings, and clearing a managed field
removes its previous environment override on the next start. Saving settings,
reusing a host model, and starting either sidecar do not modify the QwenPaw
process environment. Environment defaults are imported only on first setup;
they cannot restore a credential cleared from saved settings.

Managed children inherit OS basics plus the exact runtime variable names
declared by each service in [`backend/main.py`](backend/main.py). Network
proxy/certificate settings are declared for both; Context-specific storage,
pipeline and embedding settings belong to Context, while Engine runtime and
Docker settings belong to Engine. Other global variables are not passed
through automatically. Additional integrations must declare the variables
they need; the global QwenPaw environment store itself is unchanged.

Edit saved values through **DataBridge Configuration**; manual edits to the
generated app `.env` are replaced on the next save or managed service start.
For an external Context service, manage its startup environment in that
deployment. SQL datasource credentials use the datasource registry in either
mode.

### Configuration checks

Check the following after configuration:

1. Save DataBridge model and Neo4j settings. Verify `config.json`, the populated
   Neo4j/model variables in `.env`, and LLM/embedding settings in `models.json`.
   SQL datasource variables are not expected in `.env`.
2. Enable host-model reuse, switch to another compatible active host model,
   and save or restart the managed Context service. Verify the model snapshot
   refreshes and saved settings survive the restart.
3. Register and test a SQL datasource through Data Sources. Verify the
   registration persists after a Context service restart, then select it in
   the Data Console and run a read-only query against a test database.
4. In **Agent Configuration → Models**, verify that Analysis uses the Main
   Chat model and Summaries/DataBridge use the analysis model. Change the
   workspace default and verify a new turn uses it; a running turn keeps its
   existing model.

The older expectation that saving Neo4j/LLM settings also generates SQL
datasource variables in `.env` does not apply to this configuration contract.

## Runtime health and local services

- Configure credentials and a workspace default in Main Chat. Check the
  effective model in **Agent Configuration → Models**. The separate
  **DataBridge Configuration** page manages shared-service defaults.
- QwenPaw-Data declares the Context API, Graph Store, and discovered data
  sources through the PawApp dependency contract. The Data sources page shows
  readiness, capability impact, remediation, and the actions that are actually
  available.
- The app does not invoke Docker or provision Graph Store/data-source
  infrastructure. Those resources are external dependencies and receive
  read-only readiness checks. Local lifecycle and diagnostics belong to the
  `qwenpaw-data-cli` package; production lifecycle belongs to the deployment's
  service owner.

Missing or unsupported analysis model choices return HTTP 409 before a turn
is submitted. An unavailable Context service or one without runtime model
bindings returns HTTP 503. Check the model settings and service status rather
than treating these failures as missing database data.

The app also opts into App-private dependency status and lifecycle tools. They
let the QwenPaw-Data agent inspect the same control plane as the UI and request
only pre-registered actions; they are not exported to Main Chat. The Host
remains responsible for capability governance and audit.

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
| Analysis agent models | **Agent Configuration → Models** in the Data Console | Main Chat workspace model |

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

The standalone CLI checks DataBridge at `127.0.0.1:8765` by default. The
managed app uses a dynamic private port instead; an external app deployment
can also use 8765. A CLI failure at its default address alone does not prove
the app's Context service is unavailable. Check the app service status at
`/api/qwenpaw-data/status`.

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

## Standalone app 1.0.3 release

This release targets stable QwenPaw 2.2.2 and QwenPaw-Data runtime 0.3.3.
See [the release boundary and validation guide](RELEASE.md). The app uses
the Engine native console API and inherits Main Chat models on the stable
platform. Its declared compatibility range is `>=2.2.2,<2.2.3`.
