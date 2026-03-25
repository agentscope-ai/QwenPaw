# Built-in Knowledge Module Skills

This directory contains built-in skills that are automatically synced to the active skills directory when the knowledge module is enabled.

## Available Skills

### 1. Knowledge Search Assistant (`knowledge_search_assistant/`)
- **Purpose:** Proactively use knowledge_search when answering questions about project facts, process notes, and archived materials.
- **When to use:** User asks about existing knowledge, prior decisions, or whether something is already documented.
- **File:** `knowledge_search_assistant/SKILL.md`

## Usage

These skills are automatically loaded via the `sync_knowledge_module_skills()` function in `module_skills.py`. When enabled, each skill is synced to the active skills directory and available to the agent.

To view or use these skills, reference the `SKILL.md` file in the corresponding skill directory.

## Adding New Knowledge Skills

1. Create a new directory under `skills/` with the skill name (kebab-case).
2. Create a `SKILL.md` file with YAML frontmatter and Markdown content.
3. Add the skill name to `KNOWLEDGE_MODULE_SKILL_NAMES` in `module_skills.py` (in parenthesized tuple format).
4. Commit and the skill will be automatically synced on next load.

## Notes

- All skills follow the SKILL.md standard format with YAML frontmatter.
- Skills are synced to `ACTIVE_SKILLS_DIR` via `skills_manager.sync_skill_dir_to_active()`.
- The emoji in metadata is used for UI display.
- The `requires` field in metadata specifies skill dependencies (if any).

## Related Skill Directories

For other agent skills (including pipeline orchestration), see:
- `src/copaw/agents/skills/` — Agent-level skills (e.g., pipeline, browser, file operations)
- `src/copaw/skills_market/` — Community and marketplace skills

