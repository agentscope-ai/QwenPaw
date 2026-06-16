---
name: brief
description: Create or update INTRODUCTION.md as an external-facing product brief from architecture sources only. Use when the user asks for a product brief, external introduction, adoption-facing documentation, or INTRODUCTION.md refresh.
disable-model-invocation: true
---

Create or update INTRODUCTION.md at the workspace root.

Treat this as a Brief/Documentation task.

Read only these architecture sources before writing:
- OVERALL_ARCHITECTURE.md
- relevant ARCHITECTURE.md files
- design/KG/SystemArchitecture.json
- existing INTRODUCTION.md, if it already exists, only as the current document to maintain

Do not expand the fact source to other code, tests, scripts, configuration, or documentation.

Write for external callers, adopters, and integrators. Only include claims that are supported by the allowed architecture sources.

The result must cover:
- product overview
- capability summary
- interfaces and integration points
- how to use or adopt the system
- constraints, prerequisites, and unsuitable scenarios

For every external interface, integration point, or configuration entry, include:
- name
- purpose and usage scenario
- invocation or access path
- input parameters, defaults, and constraints when the repository proves them
- outputs, errors, artifacts, or observable results when the repository proves them
- prerequisites and dependencies
- a minimal usage example or an explicit note that the repository does not provide one
- evidence source
- known limits or missing repository evidence

Do not treat "no public API" as a reason to skip interface documentation. Command entrypoints, config entrypoints, document entrypoints, and human-operated entrypoints still count as external interfaces when they are the way adopters use the system.

Use Chinese.

Do not modify business code or tests. Only create or update INTRODUCTION.md.

If the user passed arguments, treat them as the emphasis for the brief.
