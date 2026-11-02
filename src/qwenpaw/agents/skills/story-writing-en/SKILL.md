---
name: story-writing
description: "Develop stories, character bibles, treatments and scripts in Main Chat; preserve the agreed writing when handing a single film to QwenPaw Creator for production. Use for storytelling, script revision, or moving an agreed story into Creator."
metadata:
  builtin_skill_version: "1.0"
  qwenpaw:
    emoji: "✍️"
    requires: {}
---

# Write here, produce in Creator

Help the user develop the story in Main Chat. Creator is optional while writing.
Use the user's language. Ask only for missing choices that materially affect
the work; otherwise state reasonable assumptions and write.

## Develop the complete story

1. Establish the intended audience, format, length, language, tone and premise.
2. Develop the protagonist's motivation, conflict, stakes and turning points.
   Fit the structure to the work: a product film or quiet visual vignette need
   not have a conventional dramatic arc.
3. Keep a character bible with stable IDs, names, descriptions and continuity
   constraints. Record reference labels, supplied URIs and why each matters.
4. Write a complete scene-by-scene script: action, setting, dialogue verbatim,
   speaker, narration, sound and ending. Do not substitute a synopsis for it.
5. Revise with the user. Keep explicit decisions and constraints, distinguishing
   agreed choices from your proposals. Preserve exact approved text, including
   multilingual dialogue and intentional silence. Do not add narration to a
   deliberately silent ending.

Deliver readable writing in chat. The user need not understand the package
format. A request to write or revise alone does not authorize media production.

## Carry the agreed writing into Creator

When the user asks to move the story into Creator:

1. Call `list_apps`, then `describe_action` for the granted
   `qwenpaw-creator` / `prepare-production` action. The returned schema is the
   authority; do not guess unavailable actions or permissions.
2. Build a full `story` object matching that schema:
   - `schema_version: 1`, a stable `story_id`, `revision: 1`, and `title`.
   - `logline`, `synopsis`, **the complete exact `script_markdown`**.
   - `audience`, `tone`, `language`, `duration_seconds` if known,
     `aspect_ratio`, `resolution`, `scenario`.
   - `characters`: `{id, name, description, continuity}`.
   - `references`: `{id, label, uri, notes}`.
   - `decisions` and `constraints`: the full agreed lists.
3. Delegate `prepare-production` with `{"story": ...}` and a stable request ID.
   An uncertain retry uses exactly the same ID and inputs. After acceptance,
   end the turn; the Host task card monitors and returns completion. Do not
   poll or sleep in that turn.
4. On completion, retain the task ID and structured receipt: `project_id`,
   `story_revision`, `story_digest`, `project_etag`, `project_generation`.
   The task also publishes the complete JSON package and Markdown script.
   Use `open_app` with the completed task ID to open the imported project.
   Report preparation as preparation, not as a rendered video.

This action preserves reference descriptions and URIs; it does not copy or
download their binary files. Never claim a reference image or attachment is
available to production merely because its URI is in the package. Ask for
the necessary source import in Creator when production depends on it.

## Revise or produce the same project

- For an agreed story change, describe `revise-story`. Send the **entire**
  updated package with the same story ID and the next revision, plus
  `project_id`, `expected_story_digest` and `expected_project_etag` from the
  last receipt. Keep unchanged dialogue verbatim. The action retains history
  and invalidates prior script approval, including for decision-only changes.
  Finish or explicitly cancel active production before revising; a busy
  project is rejected rather than changing the story under a running goal.
- For an explicit request to produce the film, describe `produce-video`.
  Send `project_id`, `story_revision`, `story_digest`, and
  `expected_project_etag` (the receipt's `project_etag`). This confirms that
  exact story revision for production. Provider configuration and spending
  approval still apply. Follow the task's setup or approval request.
- If the user asked for both handoff and production, first prepare. On its
  completion continuation, produce using the returned receipt and the user's
  existing authorization. Do not invent a project ID or skip preparation.
- A conflict means Creator changed or another revision won. Open the project
  for review. Do not silently refresh the ETag, overwrite Creator changes,
  create a replacement project, or repeatedly retry with a new request ID.
- In a later chat, retrieve the recorded task/receipt or discover published
  artifacts with `list_app_artifacts`; do not invent identity or revision.
  Same-user, same-workspace reuse is supported; another user's or workspace's
  project is not authorized by knowing its ID.

The production action handles **one film / one live narrative timeline**.
For an episodic or multi-film request, agree on separate films and hand off
each deliberately. Do not silently flatten several episodes into one script.
If Creator or its actions are unavailable, finish the writing and explain the
missing handoff capability without pretending a project was created.
