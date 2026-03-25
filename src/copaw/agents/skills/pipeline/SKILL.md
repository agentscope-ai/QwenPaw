---
name: pipeline-orchestration-specification
description: "Comprehensive guide for CoPaw pipeline JSON schema, step definitions, validation rules, and composition best practices. Use when creating, editing, or discussing workflow orchestration templates. Fill in the Quick Start context card on first turn to generate a pipeline JSON draft without multi-round clarification."
metadata:
  copaw:
    emoji: "⚙️"
    requires: {}
---

# Pipeline Specification & Orchestration

Authoritative reference for composing, validating, and debugging CoPaw pipeline templates and runtime configurations.

## Quick Start：一轮上下文填写卡

首次创建流程时，直接填写以下 4 项，Agent 将**不再追问**，直接输出 pipeline JSON 草稿：

| # | 项目 | 说明 | 示例 |
|---|------|------|------|
| 1 | **流程用途** | 处理什么数据、达成什么目标（1-2 句）| "对四本技术书做术语一致性对照，输出关系矩阵" |
| 2 | **输入来源** | 数据格式 + 数量范围 | "4 个 markdown 文件，每书约 300 章节" |
| 3 | **期望产物** | 终态结果类型 | "ui-payload.json + relation-matrix.md" |
| 4 | **步骤线索** | 有则填，没有可跳过 | "分类→提取→映射→评审→导出" |

> **收到以上 4 项后，Agent 直接输出 pipeline JSON 草稿，无需等待更多确认。**

---

## Purpose

Ensure pipeline definitions are well-formed, semantically consistent, and maintainable by standardizing JSON structure, field validation, and composition patterns.

## When to Use

- **Creating or editing pipeline templates** — guarantee correct JSON schema
- **Discussing workflow composition** — reference valid step kinds and transitions
- **Debugging pipeline runtime issues** — validate manifest structure against schema
- **Refactoring pipelines** — apply best practices for readability and reusability
- **Implementing pipeline features** — follow naming conventions and reserved patterns

---

## Pipeline Template Root Schema

### Minimal Valid Template

```json
{
  "id": "my-pipeline-id",
  "name": "My Pipeline",
  "steps": [
    {
      "id": "step1",
      "name": "Step One",
      "kind": "task"
    }
  ]
}
```

### Complete Template with All Optional Fields

```json
{
  "id": "sample-pipeline-v2",
  "name": "Sample Pipeline v2",
  "version": "0.2.0",
  "description": "Example pipeline demonstrating all fields and conventions.",
  "steps": [
    {
      "id": "input",
      "name": "Collect Input",
      "kind": "ingest",
      "description": "Load source data and validate inputs."
    },
    {
      "id": "process",
      "name": "Process",
      "kind": "transform",
      "description": "Apply transformations and enrich data."
    },
    {
      "id": "validate",
      "name": "Validate Output",
      "kind": "validation",
      "description": "Check quality metrics and compliance rules."
    },
    {
      "id": "export",
      "name": "Export Results",
      "kind": "publish",
      "description": "Serialize and deliver artifacts to downstream systems."
    }
  ]
}
```

---

## Field Reference

### Root Fields

| Field | Type | Required | Default | Rules & Notes |
|-------|------|----------|---------|---------------|
| `id` | string | ✅ | — | Pipeline identifier. Must be kebab-case, alphanumeric + hyphens. Used as filename stem. Max 64 chars. |
| `name` | string | ✅ | — | Human-readable title. Max 256 chars. Displayed in UI and logs. |
| `version` | string | ❌ | `""` | Semantic version (e.g., "1.0.0", "0.1.0-beta"). For docs and changelog only. |
| `description` | string | ❌ | `""` | Purpose and scope. Max 1024 chars. Markdown is allowed. |
| `steps` | array | ✅ | — | List of step definitions. Min 1 step, max 100 steps per pipeline. |

### Step Fields

| Field | Type | Required | Default | Rules & Notes |
|-------|------|----------|---------|---------------|
| `id` | string | ✅ | — | Unique within pipeline. Kebab-case. Max 64 chars. Used internally for addressing and artifact routing. |
| `name` | string | ✅ | — | Human-readable label. Max 128 chars. Shown in runtime UI and logs. |
| `kind` | string | ✅ | — | Step type/category. Must be one of the predefined kinds (see below). |
| `description` | string | ❌ | `""` | What this step does. Max 512 chars. Helps users understand pipeline intent. |

---

## Step Kinds (Categories)

Standard step kinds establish semantic meaning and hint at runtime behavior:

### Canonical Kinds

| Kind | Purpose | Expected Behavior | Example |
|------|---------|-------------------|---------|
| `ingest` | **Data input & collection.** Load files, fetch from APIs, stage materials. | Reads external sources; outputs materialized data. | Collect markdown files, fetch reference images. |
| `transform` | **Data mutation & enrichment.** Apply algorithms, format conversions, NLP operations. | Transforms input into new representation. | Normalize structure, segment text, align sentences. |
| `alignment` | **Specialized transform: bilingual/cross-version alignment.** | Pairs and synchronizes related content blocks. | Align chapters, sentences between source and translation. |
| `validation` | **Quality checks & compliance gates.** Measure metrics, assert rules, flag issues. | Evaluates data against criteria; emits reports. | Check consistency, verify coverage, measure metrics. |
| `publish` | **Output & artifact finalization.** Serialize, package, emit manifests. | Produces final deliverables and metadata. | Export JSON reports, create release packages. |
| `task` | **Generic/composite step.** Default for unclassified work. | Implementation-defined behavior. | Custom agent task, orchestration step. |

### Extended Kinds (Domain-Specific)

- `analysis` — Inspect and report without mutation (e.g., diff analysis, trend extraction).
- `review` — Manual or semi-automatic approval step (e.g., QA gate, human sign-off).
- `parallel` — Marker for parallelizable steps (informational; actual parallelism depends on runner).

---

## Validation Rules

### Schema Compliance

1. **Root object must have `id`, `name`, `steps`.**
   - Missing fields cause parse failures.
   - Extra root fields are silently ignored.

2. **Each step must have `id`, `name`, `kind`.**
   - ID and name cannot be empty after trimming.
   - Kind must match one of the canonical or known extended kinds.

3. **No duplicate step IDs within a pipeline.**
   - Violates internal referencing and artifact routing.
   - Parser will reject or log a warning.

4. **ID format rules (both root and step):**
   - Allowed: `a-z`, `0-9`, hyphen (`-`).
   - Start with lowercase letter or digit.
   - Max 64 characters.
   - **✅ Valid:** `my-pipeline`, `step-1`, `collect-inputs`
   - **❌ Invalid:** `My-Pipeline`, `step_1`, `collect inputs`, `_step1`

### Semantic Consistency

1. **Pipeline purpose should be clear from name + description + step sequence.**
   - Steps should logically flow (ingest → transform → validation → publish).
   - Avoid backward jumps or unclear transitions.

2. **Step names should be action-oriented (verb-noun pattern).**
   - **✅ Good:** "Collect Inputs", "Normalize Structure", "Validate Metrics"
   - **❌ Bad:** "Input", "Normalizer", "Validation" (ambiguous or noun-only)

3. **Descriptions should explain the "why" and "what" without implementation details.**
   - Avoid code snippets or internal config in descriptions.
   - Be concise but informative.

---

## Common Patterns & Templates

### Pattern 1: Simple Linear Pipeline

```json
{
  "id": "simple-process-v1",
  "name": "Simple Linear Process",
  "description": "Minimal pipeline: ingest → transform → publish.",
  "steps": [
    { "id": "ingest", "name": "Load Data", "kind": "ingest" },
    { "id": "transform", "name": "Process Data", "kind": "transform" },
    { "id": "output", "name": "Save Results", "kind": "publish" }
  ]
}
```

### Pattern 2: Quality-Gated Pipeline (+ Validation)

```json
{
  "id": "quality-gate-process-v1",
  "name": "Quality-Gated Workflow",
  "description": "Standard pattern: ingest → transform → validation → publish.",
  "steps": [
    { "id": "collect", "name": "Collect Input", "kind": "ingest" },
    { "id": "process", "name": "Transform Content", "kind": "transform" },
    { "id": "quality", "name": "Quality Gate", "kind": "validation" },
    { "id": "package", "name": "Package Artifacts", "kind": "publish" }
  ]
}
```

### Pattern 3: Bilingual Alignment Pipeline

```json
{
  "id": "bilingual-align-v1",
  "name": "Bilingual Alignment Pipeline",
  "version": "1.0.0",
  "description": "Specialized pipeline for source-translation alignment with quality checks.",
  "steps": [
    { "id": "ingest-source", "name": "Ingest Source", "kind": "ingest", "description": "Load source language content." },
    { "id": "ingest-translation", "name": "Ingest Translation", "kind": "ingest", "description": "Load target language content." },
    { "id": "normalize", "name": "Normalize Structure", "kind": "transform", "description": "Standardize formatting and structure." },
    { "id": "align-sentences", "name": "Align Sentences", "kind": "alignment", "description": "Pair source and translation at sentence level." },
    { "id": "check-consistency", "name": "Check Consistency", "kind": "validation", "description": "Verify terminology and meaning alignment." },
    { "id": "export", "name": "Export Aligned Pairs", "kind": "publish", "description": "Produce bilingual alignment manifest." }
  ]
}
```

### Pattern 4: Multi-Stage Analysis Pipeline

```json
{
  "id": "analysis-report-v1",
  "name": "Analysis & Reporting Pipeline",
  "description": "Inspect, analyze, and generate comprehensive reports.",
  "steps": [
    { "id": "collect", "name": "Collect Data", "kind": "ingest" },
    { "id": "analyze-metrics", "name": "Analyze Metrics", "kind": "analysis" },
    { "id": "analyze-coverage", "name": "Analyze Coverage", "kind": "analysis" },
    { "id": "validate-thresholds", "name": "Validate Against Thresholds", "kind": "validation" },
    { "id": "generate-report", "name": "Generate Report", "kind": "publish" }
  ]
}
```

---

## Best Practices for Composition

### 1. Naming Conventions

- **Pipeline ID:** descriptive, domain-aware, versioned.
  - ✅ `books-alignment-v1`, `bilingual-consistency-check-v2`, `quality-gate-process`
  - ❌ `pipeline1`, `my-thing`, `unnamed`
- **Step ID:** short, action-oriented, unique within pipeline.
  - ✅ `collect-inputs`, `normalize-structure`, `check-quality`
  - ❌ `step-1`, `s1`, `do-stuff`
- **Step Name:** readable, capitalized, verb-noun pattern.
  - ✅ "Collect Inputs", "Check Consistency", "Package Artifacts"
  - ❌ "input collection", "Inputs", "Collection"

### 2. Step Ordering

Prefer logical flow:

```
ingest → (transform | alignment) → validation → publish
```

- **Ingest first:** Establish data boundaries.
- **Transform in the middle:** Apply business logic.
- **Validation before publish:** Catch issues early.
- **Publish last:** Finalize and emit artifacts.

### 3. Clear Descriptions

- Explain **what** the step accomplishes in end-user terms.
- Explain **why** it's necessary in the pipeline.
- **Avoid** implementation details, config syntax, code snippets.

### 4. Reusability

- Keep step counts reasonable (6–15 steps is typical).
- Use generic step kinds if the specific behavior is delegated to runtime agents.
- Document any assumptions about input/output formats in pipeline description.

### 5. Versioning

- Use semantic versioning in `version` field (optional but recommended for stable pipelines).
- Increment minor for non-breaking step additions.
- Increment major for step removal or kind restructuring.
- Include breaking changes in description.

---

## Runtime Manifest & Execution

### Pipeline Run Manifest Structure

When a pipeline executes, a runtime manifest is created:

```json
{
  "id": "run-abc123",
  "template_id": "my-pipeline-v1",
  "project_id": "project-xyz",
  "status": "succeeded",
  "created_at": "2026-03-20T10:15:00Z",
  "updated_at": "2026-03-20T10:45:30Z",
  "parameters": {
    "source_path": "/data/source.md",
    "output_format": "json"
  },
  "steps": [
    {
      "id": "ingest",
      "name": "Collect Input",
      "kind": "ingest",
      "status": "succeeded",
      "started_at": "2026-03-20T10:15:05Z",
      "ended_at": "2026-03-20T10:16:00Z",
      "metrics": { "files_loaded": 42 },
      "evidence": ["artifact://run-abc123/steps/ingest/input_summary.json"]
    },
    {
      "id": "process",
      "name": "Transform",
      "kind": "transform",
      "status": "succeeded",
      "started_at": "2026-03-20T10:16:01Z",
      "ended_at": "2026-03-20T10:30:00Z",
      "metrics": { "records_processed": 1200, "errors": 0 },
      "evidence": ["artifact://run-abc123/steps/process/output.json"]
    }
  ],
  "artifacts": ["artifact://run-abc123/final_report.json"]
}
```

### Step Statuses

- `pending` — Waiting to start.
- `running` — Currently executing.
- `succeeded` — Completed without errors.
- `failed` — Encountered an error.
- `skipped` — Was not executed (conditional or parallel).
- `blocked` — Waiting for a dependency or gate.

### Pipeline Statuses

- `pending` — Just created, not yet started.
- `running` — At least one step is active.
- `succeeded` — All steps succeeded.
- `failed` — One or more steps failed.
- `cancelled` — User or system aborted execution.

---

## Error Handling & Debugging

### Common Validation Failures

| Error | Cause | Fix |
|-------|-------|-----|
| `Missing required field: id` | Root or step missing `id` | Add unique, kebab-case ID. |
| `Invalid ID format: "My-ID"` | Contains uppercase or spaces | Use lowercase and hyphens only. |
| `Duplicate step ID: "process"` | Step ID not unique within pipeline | Rename one of the conflicting steps. |
| `Unknown step kind: "custom"` | Kind not in canonical/extended list | Use valid kind or contact platform team. |
| `Empty steps array` | Pipeline has no steps | Add at least one step. |

### Debugging Tips

1. **Validate JSON syntax first:**  Use a JSON linter to catch syntax errors before schema validation.

2. **Check ID uniqueness:** Pipeline MUST NOT have duplicate step IDs.

3. **Review step kinds:** Ensure all `kind` values are recognized (canonical + known extended).

4. **Confirm field values are non-empty:** After trimming, `id`, `name`, `kind` must be present.

5. **Inspect runtime manifests:** If a pipeline fails at runtime, check the manifest for step statuses and error messages in evidence/metrics.

---

## Integration with Editor/CLI

### Creating a Pipeline Template

**Via JSON file (programmatic):**
1. Compose JSON following this spec.
2. Save to `{project_dir}/pipelines/templates/{id}.json`.
3. Verify with schema validator.
4. Test by running the pipeline via the API or CLI.

**Via API (interactive):**
```
PUT /agents/{agentId}/projects/{projectId}/pipelines/templates/{templateId}
Content-Type: application/json

{
  "id": "my-pipeline",
  "name": "My Pipeline",
  "steps": [ ... ]
}
```

**Via CLI (if supported):**
```bash
copaw pipeline create --id my-pipeline --name "My Pipeline" --steps-file steps.json
```

### Listing Available Templates

```
GET /agents/{agentId}/pipelines/templates
GET /agents/{agentId}/projects/{projectId}/pipelines/templates
```

### Creating a Pipeline Run

```
POST /agents/{agentId}/projects/{projectId}/pipelines/runs
Content-Type: application/json

{
  "template_id": "my-pipeline",
  "parameters": { "input_path": "/path/to/data" }
}
```

---

## Workflow: "From Idea to Execution"

### Step 1: Design

- **Sketch the flow:** What are the main stages (ingest, transform, validate, publish)?
- **Name stages:** Assign meaningful IDs and names.
- **Assign kinds:** Choose appropriate kind for each stage.

### Step 2: Compose JSON

- Use the **Complete Template** example as a starting point.
- Fill in `id`, `name`, `steps`.
- Add `version` and `description` for clarity.
- Validate against this spec.

### Step 3: Validate & Test

- **Schema validation:** Ensure JSON is well-formed.
- **Semantic check:** Do step kinds and names make sense?
- **Runtime test:** Execute the pipeline with sample data; inspect manifest.

### Step 4: Iterate

- Review runtime manifest for step statuses and metrics.
- Adjust step order, names, or kinds if needed.
- Add or remove steps based on discovered requirements.

### Step 5: Version & Archive

- Commit template to version control.
- Tag version in `version` field.
- Document changes in project changelog.

---

## Examples Index

| Use Case | Template | Example File |
|----------|----------|--------------|
| Simple linear workflow | Pattern 1 | `example-simple-process-v1.json` |
| Quality-gated process | Pattern 2 | `example-quality-gate-process-v1.json` |
| Bilingual alignment | Pattern 3 | `example-bilingual-align-v1.json` |
| Multi-stage analysis | Pattern 4 | `example-analysis-report-v1.json` |

See the examples in this skill directory for full JSON templates.

---

## Related Skills & References

- **Agents Skills Directory** — View other available agent skills at `src/copaw/agents/skills/`
- **Pipeline Runtime Debugging** — For troubleshooting failures in running pipelines.
- **Agent Task Definition** — To define step implementations in agent code.

---

## Quick Checklist: "Is My Pipeline Valid?"

- [ ] Root has `id`, `name`, `steps` (required fields).
- [ ] `id` is kebab-case, alphanumeric + hyphens, max 64 chars.
- [ ] Pipeline name is descriptive and <= 256 chars.
- [ ] Each step has `id`, `name`, `kind`.
- [ ] No duplicate step IDs.
- [ ] All step `kind` values are recognized (canonical or extended).
- [ ] Step names follow verb-noun pattern.
- [ ] Descriptions explain purpose, not implementation.
- [ ] Step sequence is logical (ingest → transform → validation → publish).
- [ ] JSON is syntactically valid.
