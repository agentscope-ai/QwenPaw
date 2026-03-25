# Agent Skills - Pipeline Orchestration

This directory contains specialized agent skills for CoPaw operations.

## Available Skills

### Pipeline Orchestration (`pipeline/`)

**Name:** `pipeline-orchestration-specification`

**Purpose:** Authoritative reference for CoPaw pipeline JSON schema, validation rules, step kinds, and composition best practices.

**Location:** `src/copaw/agents/skills/pipeline/`

**When to use:**
- Creating or editing pipeline templates
- Discussing workflow composition and orchestration
- Validating pipeline JSON format and schema
- Debugging pipeline runtime issues
- Applying best practices for pipeline composition
- Designing multi-step workflows

**Files:**
- `SKILL.md` — Complete specification including:
  - Full JSON schema reference with field tables
  - 10 standard and extended step kinds (ingest, transform, alignment, validation, publish, task, analysis, review, parallel)
  - Validation rules (schema compliance + semantic consistency)
  - Naming conventions and best practices
  - 4 common pipeline patterns with working examples
  - Runtime manifest structure and status machine
  - Error handling and debugging guide
  - Integration with Editor/CLI
  - Complete "From Idea to Execution" workflow

- `example-simple-process-v1.json` — Minimal linear pipeline (ingest → transform → publish)
- `example-quality-gate-process-v1.json` — Production pattern with quality validation gate
- `example-bilingual-align-v1.json` — Specialized bilingual content alignment workflow
- `example-analysis-report-v1.json` — Multi-stage analysis and reporting pipeline

## How Skills Are Synced

Agent skills are automatically discovered and made available to the chat agent. Skills are organized by function and can be referenced in both `copilot-instructions.md` and within agent tasks.

## Adding New Agent Skills

1. Create a subdirectory with the skill name (kebab-case).
2. Create a `SKILL.md` file with YAML frontmatter and comprehensive documentation.
3. Add example files or reference materials as needed.
4. The skill will be automatically available to the agent by name.

### SKILL.md Frontmatter Template

```yaml
---
name: skill-name
description: "Concise description of the skill and when to use it."
metadata:
  copaw:
    emoji: "🎯"
    requires: {}
---
```

## Related Directories

- `src/copaw/knowledge/skills/` — Knowledge module skills (e.g., knowledge search assistant)
- `src/copaw/skills_market/` — Marketplace and community skills
- `copilot-instructions.md` — Agent instructions and skill activation rules
