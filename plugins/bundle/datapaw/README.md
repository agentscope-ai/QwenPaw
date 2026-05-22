<p align="center">
  <img src="logo.png" alt="DataPaw" width="320">
</p>

<p align="center">
  <strong>Data Analysis Plugin for QwenPaw</strong>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/version-0.1.0-green.svg" alt="Version" /></a>
</p>

<p align="center">
  <b>English</b> | <a href="README_zh.md">中文</a> | <a href="README_ja.md">日本語</a> | <a href="README_ru.md">Русский</a>
</p>

---

DataPaw is a data-analysis plugin for QwenPaw. It ships **12 BI-flavoured agent skills** — anomaly detection, dimension drilldown, attribution analysis, time-impact attribution, adaptive thresholding, HTML report generation, and the planning / routing skills that glue them together — so an agent can walk a BI question end to end on your local files: load → clean → analyze → drill down → write a report.

Best for:

- **Multi-step BI analysis** — the agent picks the right skills for each step and produces a structured report at the end.
- **Anomaly attribution** — when a metric moves, adaptive thresholding → anomaly detection → time-impact decomposition → dimension drilldown all run as bundled skills, ending in an HTML report.
- **Local-file workflows** — feed the agent CSV / Excel / Parquet by uploading in chat, pasting absolute paths, or dropping into the agent workspace. Analysis runs through `execute_shell_command` end to end.

Under the hood, every multi-step run is structured as a **DAG task graph**: each step is a named node, the agent advances one at a time, and progress is persisted to the session so you can pause and resume. The DAG state is observable via SSE and editable via a REST API. A **task-panel frontend** (DAG visualization + node editing UI) is in development as part of this same plugin — see [Frontend roadmap](#frontend-roadmap) below.

DataPaw runs entirely in your own environment; data stays where you put it.

## Quick Start

### Prerequisites

| Item | Requirement |
|---|---|
| **QwenPaw version** | **≥ v1.1.7** |
| **Python** | 3.10 ~ 3.13 |
| **LLM provider** | Configured in QwenPaw (DataPaw inherits the active model) |

> If your QwenPaw version is below v1.1.7, upgrade first: `pip install --upgrade "qwenpaw>=1.1.7"`.

### 1. Install DataPaw Plugin

**Via Console (recommended):**

1. Launch QwenPaw (`qwenpaw app`), open http://127.0.0.1:8088/.
2. Click "Plugin Manager" in the left sidebar (under Settings), then click "Install Plugin".
3. Drag the `datapaw/` folder into the install dialog, or select a ZIP file (DataPaw is bundled with QwenPaw at `plugins/bundle/datapaw/`).
4. Wait for installation to complete.

**Via CLI:**

```bash
qwenpaw plugin install /path/to/datapaw
```

> After installing, refresh the browser (`Cmd+Shift+R` / `Ctrl+Shift+R`) so the agent dropdown picks up the new "DataPaw" entry.

### 2. Configure

#### LLM Model

Configure an LLM provider and API key in console **Settings → Models**. DataPaw inherits whichever model you have active — no separate config. See the [QwenPaw Models docs](https://qwenpaw.agentscope.io/docs/models).

#### Feeding data in

DataPaw does not bundle any data-fetch tools. To get data into an analysis you have three options, in order of convenience:

- **Upload in the chat** — the console's file upload puts the file under the agent workspace (`media/` / `file_store/`), and the agent picks it up from there.
- **Paste an absolute path** — write the path in your message (e.g. `/Users/me/Downloads/data.csv`) and the agent reads it via `read_file` / `execute_shell_command`.
- **Drop a file into the workspace** — copy CSV / Excel / Parquet directly into `~/.qwenpaw/workspaces/datapaw/` and reference it by relative path.

Analysis outputs (intermediate datasets, charts, reports) all land under `~/.qwenpaw/workspaces/datapaw/artifacts/<session_id>/<graph_id>/<node_id>/` — see [Artifact layout](#artifact-layout) below.

### 3. Start using

Pick **DataPaw** from the agent dropdown on the chat page. Try a request like:

```
Analyze the daily access trend for product X in December 2025; output an HTML report.
```

You should see:

- The agent calls `analysis-plan-builder` to draft a plan.
- The agent walks the plan one node at a time; each node transitions `pending → ready → in_progress → done`.
- The final node calls `bi-report-generation` and produces an HTML file under the artifacts root.

## Bundled Skills

DataPaw's value is in the skills it ships. All 12 are auto-installed into the agent's workspace and enabled at startup:

### Flow skills (the glue)

| Skill | When the agent uses it |
|---|---|
| `data-intent-router` | First thing every user turn — classifies the request and routes to the right pipeline. |
| `analysis-plan-builder` | Turns an open-ended analytical ask into a structured, confirmable plan. |
| `runtime-guide` | Execution-time conventions: reuse, error handling, mid-plan revision, self-check. |

### Analysis skills

| Skill | What it does |
|---|---|
| `bi-metric-analysis` | End-to-end pipeline for a single metric / scope: observation + anomaly detection + dimension drilldown. |
| `bi-anomaly-detection` | Threshold-based anomaly point detection in a time series. |
| `bi-adaptive-threshold` | Derive an anomaly / impact threshold from the data's own natural variation, instead of hard-coding. |
| `bi-attribution-analysis` | Per-dimension contribution to a metric move; supports additive and weighted-average metrics. |
| `bi-dimension-drilldown` | Layer-by-layer drilldown to localize the dimensions driving the move. |
| `bi-time-impact-attribution` | Decompose a period-over-period change into structural / trend / event effects. |
| `bi-new-dimension-analysis` | Spot newly-emerged dimension values (new channel / SKU / feature) and assess their impact. |
| `bi-semantic-layer-guide` | Conventions for talking to a metric / dimension semantic layer when one is configured. |

### Reporting

| Skill | What it does |
|---|---|
| `bi-report-generation` | Compose the analysis findings + artifacts into a reader-friendly HTML report. |

Each skill ships with its `SKILL.md` (the model card) plus, where relevant, helper scripts and reference docs under `skills/<name>/`. The agent reads the SKILL.md on demand — you don't need to.

## Usage examples

**Daily-trend analysis with an HTML report**

> Analyze the daily access trend for product X in December 2025. Detect anomalies, attribute drops, and produce an HTML report.

DataPaw will plan the DAG via `analysis-plan-builder`, drive `bi-anomaly-detection` → `bi-attribution-analysis` → `bi-report-generation` along the dependency order, and end with a `report.html` under the artifacts root.

**Ad-hoc one-shot question**

> What's the median session length in `sessions.csv`?

Simple enough that DataPaw skips `create_plan` and answers directly via `execute_shell_command`.

## Frontend roadmap

This release ships the **backend** of the DataPaw plugin: agent, skills, DAG task graph, REST API, SSE events.

The **DataPaw frontend** — DAG visualization, click-to-edit nodes, in-panel file preview, fetch_data result rendering — is in active development as part of this same plugin. It will ship in `plugins/bundle/datapaw/` in a follow-up release.

Until then, you can drive DataPaw entirely from the chat agent; DAG state and artifacts are observable via the SSE event stream and the REST endpoints below.

## Task graph & APIs

Each multi-step analysis is structured as a DAG, persisted to the session, and observable via REST + SSE.

### REST endpoints (mounted at `/api/tasks/...`)

| Method | Path | Purpose |
|---|---|---|
| `GET`  | `/{session_id}` | Current DAG + history summary + artifacts summary |
| `GET`  | `/{session_id}/dag` | Full DAG of the active graph |
| `GET`  | `/{session_id}/sop` | Current graph as YAML |
| `PUT`  | `/{session_id}/sop` | Upload a new SOP YAML (queues a `[sop_replaced]` notice for the agent) |
| `PUT`  | `/{session_id}/dag` | Patch the DAG (queues a `[dag_merged]` notice) |
| `GET`  | `/{session_id}/history/{plan_id}` | Inspect an archived graph |
| `GET`  | `/{session_id}/files{,/preview,/download}` | List / preview / download artifacts |

Write endpoints are gated by `_check_not_running` to block races with the live agent loop. See `core/routers/tasks.py` for the schemas.

## Architecture

DataPaw integrates via the QwenPaw plugin system. No host source is modified; everything plugs in at startup.

```
plugins/bundle/datapaw/
├── plugin.json                # manifest
├── plugin.py                  # backend entry: register startup/shutdown hooks
├── constants.py               # shared constants + sys.path bootstrap
├── agents_setup.py            # write builtin agent profile + workspace + skills
├── hooks.py                   # runtime patches: smart agent factory, channel SSE, unload cleanup
├── prompts/MASTER.md          # runtime mechanism prompt (DAG / plan tools / artifact rules)
├── agents/datapaw/{zh,en}/    # per-language SOUL.md + PROFILE.md
├── skills/                    # 12 bundled BI skills
└── core/                      # core implementation
    ├── agents/base.py         # DataPawAgent (extends QwenPawAgent)
    ├── orchestration/         # TaskGraph / RuntimeStateManager / hint / events
    ├── routers/tasks.py       # /api/tasks/* router
    └── path_context.py        # sandbox-view ↔ host path translator
```

The system prompt is assembled in three layers:

1. Host-standard `AGENTS.md` / `SOUL.md` / `PROFILE.md` (the host's per-agent prompt convention).
2. Plugin's `MASTER.md` — DAG runtime rules and plan tool guide, appended after the host stack.
3. A live `<datapaw-analysis-environment>` hint that names the workspace path, artifacts root, and execution conventions for the current request.

## Artifact layout

All analysis outputs land under the agent workspace, partitioned by session / graph / node:

```
~/.qwenpaw/workspaces/datapaw/artifacts/
└── <session_id>/
    └── <graph_id>/
        └── <node_id>/
            ├── data.csv
            ├── chart.png
            └── report.html
```

`finish_subtask(files=...)` records relative paths (without the `artifacts/` prefix) and the runtime resolves them back to host absolute paths through `PathContext.resolve_artifact_path`.

## Acknowledgements

- Built on [QwenPaw](https://github.com/agentscope-ai/QwenPaw) and [agentscope](https://github.com/modelscope/agentscope).
