<p align="center">
  <strong>Data Analysis Plugin for QwenPaw</strong>
</p>

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="License" /></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/Python-3.10%2B-blue.svg" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/version-0.1.0-green.svg" alt="Version" /></a>
</p>

<p align="center">
  <b>English</b> | <a href="README_zh.md">中文</a>
</p>

---

DataPaw is a data-analysis plugin for QwenPaw. It turns ad-hoc analytical questions into a structured, observable, resumable execution: a DAG task graph the agent drives step by step, a side panel where you can edit nodes mid-run, and SSE streaming so node state updates land in the UI in real time.

DataPaw is good at the kinds of investigations where "just ask the LLM" stops being enough:

- **Multi-step BI analysis** — load → clean → analyze → drill down → write a report — broken into named DAG nodes you can pause, edit, and resume.
- **Anomaly attribution** — when a metric moves, the agent runs adaptive thresholding, time-decomposition, and dimension drilldown via bundled skills, then writes a structured HTML report.
- **Local-file workflows** — feed the agent CSV / Excel / Parquet files by uploading them in the chat, pasting absolute paths into the message, or dropping them into the agent workspace. The agent loads, transforms, visualizes, and reports via Python under `execute_shell_command`.

DataPaw runs entirely in your own environment; data stays where you put it.

## Quick Start

### Prerequisites

| Item | Requirement |
|---|---|
| **QwenPaw version** | **≥ v1.1.7** |
| **Python** | 3.10 ~ 3.13 |
| **LLM provider** | Configured in QwenPaw (DataPaw inherits the active model) |

> If your QwenPaw version is below v1.1.7, upgrade first: `pip install --upgrade qwenpaw>=1.1.7`.

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

DataPaw does not bundle any data-fetch tools. To get data into an analysis you have three options, in order of convenience:

- **Upload in the chat** — the console's file upload puts the file under the agent workspace (`media/` / `file_store/`), and the agent picks it up from there.
- **Paste an absolute path** — write the path in your message (e.g. `/Users/me/Downloads/data.csv`) and the agent reads it via `read_file` / `execute_shell_command`.
- **Drop a file into the workspace** — copy CSV / Excel / Parquet directly into `~/.qwenpaw/workspaces/datapaw/` and reference it by relative path.

Analysis outputs (intermediate datasets, charts, reports) all land under `~/.qwenpaw/workspaces/datapaw/artifacts/<session_id>/<graph_id>/<node_id>/` — see [Artifact Layout](#artifact-layout) below.

### 3. Start Using

Pick **DataPaw** from the agent dropdown on the chat page. Try a request like:

```
Analyze the daily access trend for product X in December 2025; output an HTML report.
```

You should see:

- The agent calls `analysis-plan-builder` to draft a plan.
- A DAG task graph appears in the task panel.
- Each node transitions `pending → ready → in_progress → done` with status streaming live to the panel.
- The final node calls `bi-report-generation` and produces an HTML file under the artifacts root.

## Architecture

DataPaw integrates via the QwenPaw plugin system. No host source is modified; everything plugs in at startup.

```
plugins/bundle/datapaw/
├── plugin.json                # manifest
├── plugin.py                  # backend entry: register startup/shutdown hooks
├── constants.py               # shared constants + sys.path bootstrap
├── agents_setup.py            # write builtin agent profile + workspace + skills
├── routers_setup.py           # mount tasks_router on host FastAPI app
├── hooks.py                   # monkey-patches: smart agent factory, channel SSE, unload cleanup
├── prompts/MASTER.md          # runtime mechanism prompt (DAG / plan tools / artifact rules)
├── agents/datapaw/{zh,en}/    # per-language SOUL.md + PROFILE.md
├── skills/                    # 12 bundled BI skills
└── core/                      # core implementation (DataPawAgent, RuntimeStateManager, tasks router)
    ├── agents/base.py
    ├── orchestration/
    ├── routers/tasks.py
    └── path_context.py
```

The system prompt is assembled in three layers:

1. Host-standard `AGENTS.md` / `SOUL.md` / `PROFILE.md` (the host's per-agent prompt convention).
2. Plugin's `MASTER.md` — DAG runtime rules and plan tool guide, appended after the host stack.
3. A live `<datapaw-analysis-environment>` hint that names the workspace path, artifacts root, and execution conventions for the current request.

## Features

- **DAG task graph** — every multi-step analysis becomes a structured, persisted plan you can inspect, edit, and resume.
- **Task panel with SSE streaming** — node state changes (`pending` → `ready` → `in_progress` → `done` / `failed` / `stale`) land in the UI in real time, mixed into the regular SSE message stream.
- **Mid-run editing** — change a node's prompt or dependencies in the panel; the agent picks up the diff via a `[外部变更通知]` system message on the next reply.
- **12 bundled BI skills** — see below.
- **Single-agent simplicity** — no orchestration / sub-agent / delegation machinery. The whole analysis runs in one ReAct loop driven by the DAG.
- **Local-file workflows** — accept input as chat uploads, pasted absolute paths, or files in the workspace; analysis runs through `execute_shell_command` end to end.

## Bundled Skills

DataPaw ships with 12 BI-flavoured skills, auto-installed into the agent's workspace and enabled at startup:

| Category | Skill |
|---|---|
| Planning | `analysis-plan-builder` — turn a raw analytical request into a structured plan; `runtime-guide` — execution-time strategy guide; `data-intent-router` — route data requests to the right pipeline |
| Threshold & detection | `bi-adaptive-threshold`, `bi-anomaly-detection` |
| Attribution | `bi-attribution-analysis`, `bi-dimension-drilldown`, `bi-time-impact-attribution`, `bi-new-dimension-analysis` |
| End-to-end | `bi-metric-analysis` — observation + anomaly detection + drilldown for a single metric/scope |
| Semantic layer | `bi-semantic-layer-guide` — instructions for talking to a metric/dimension semantic layer when one is available |
| Reporting | `bi-report-generation` — assemble analysis results into an HTML report |

## Artifact Layout

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

## Usage Examples

**Daily-trend analysis with HTML report**

> Analyze the daily access trend for product X in December 2025. Detect anomalies, attribute drops, and produce an HTML report.

DataPaw will plan the DAG via `analysis-plan-builder`, drive `bi-anomaly-detection` → `bi-attribution-analysis` → `bi-report-generation` along the dependency order, and end with a `report.html` under the artifacts root.

**Ad-hoc one-shot question**

> What's the median session length in `sessions.csv`?

Simple enough that DataPaw skips `create_plan` and answers directly via `execute_shell_command`.

## Acknowledgements

- Built on [QwenPaw](https://github.com/agentscope-ai/QwenPaw) and [agentscope](https://github.com/modelscope/agentscope).
- The DAG task graph extends agentscope's `Plan` / `PlanNotebook` / `SubTask` primitives.
