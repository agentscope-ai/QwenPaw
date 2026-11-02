# Main Chat writing → Creator production

Main Chat develops and revises the story. Creator produces it in a persistent
project. The boundary carries the complete agreed writing, not a summary or
the raw conversation. The bilingual bundled `story-writing` skill uses the
same discovery, delegation and handoff tools as other Apps.
Existing skill pools must import the new built-in skill and enable it for the
agent; upgrading does not silently change existing skill selections. Each
new action needs its own Host grant for the selected workspace.

## Contract and lifecycle

`backend/services/story_package.py` defines the strict, versioned contract.
`StoryPackage` v1 contains a stable story ID and revision, title, logline,
synopsis, exact Markdown script, character bible, reference descriptions and
URIs, decisions, constraints, audience, tone, language and production format.
The canonical JSON is bounded to 128 KiB; script text to 50,000 characters.
Unknown fields, duplicate character/reference IDs and empty scripts fail
validation. The SHA-256 digest covers the complete canonical package.

| Action | Input | Effect |
| --- | --- | --- |
| `prepare-production` | Complete package at revision 1 | Create a script-stage project and import the canonical JSON plus exact UTF-8 script; no model or media calls |
| `revise-story` | Complete next revision, project ID, previous story digest and project ETag | Append immutable package/script versions in the same project, select the new revision and invalidate script approval |
| `produce-video` | Project ID, story revision/digest and expected project ETag | Confirm that exact saved revision, admit one production goal in the same project, then reuse the existing video workflow |

Prepare/revise return a schema-checked receipt with `project_id`,
`story_revision`, `story_digest`, `project_etag`, and `project_generation`.
They publish both JSON and Markdown through the Host artifact store. Handoff
opens the already-populated project and carries those exact artifact refs.
The generic Host uses an action's completed text result as context when no
text input exists; it does not interpret story fields.

## Storage, permissions and recovery

- The imported package is a `story_package` ArtifactVersion in `story:main`.
  Its exact script is the selected `timeline_script`; title and synopsis also
  populate the main timeline. The agent reads the JSON artifact before
  planning, so character continuity and agreed decisions remain available.
- Projects are bound to the Host principal/workspace/App tuple, independently
  of the originating chat. Another chat for that scope can reuse the project;
  knowing its ID does not authorize another scope.
- Prepare/revise are replay-safe managed handlers. Submission meaning and
  import receipts are persisted. File names are content-addressed, project
  creation is idempotent and revisions append history under the project lock.
  A crash after import can recover its receipt at the committed generation;
  intervening edits cause a conflict instead of inventing a new receipt.
- Revisions require both the preceding story digest and project ETag.
  Changes made directly in Creator are never silently overwritten. A conflict
  currently requires opening Creator for review; there is no automatic merge
  of chat and editor changes. Revisions also reject active Runtime work;
  finish or explicitly cancel production before replacing the story.
- Production uses stable message/goal IDs. Script confirmation and admission
  are serialized with project edits and Runtime admission. The commit journal
  permits recovery after confirmation but before goal creation; any intervening
  edit fails the admission guard. Replaying a completed goal does not reactivate it.
- Selecting a new package version changes the script approval fingerprint even
  when its Markdown is unchanged. An already-approved film therefore pauses
  when agreed constraints or character details change.
- Production reuses the existing workflow's setup, execution authorization,
  observation, cancellation, canonical final-film validation and publication.
  Confirming the script does not bypass spending authorization.

## Deliberate limits

This is a single-film import into one live narrative timeline. Reference URIs
and notes are preserved as data; binary reference files are not copied or
downloaded, and a URI grants no access. Existing Creator source-import tools
remain responsible for usable media references. The skill does not flatten
multi-episode work into one film or claim that supplied URLs are imported media.

No model-generated rendering is needed to test the import contract. Automated
tests cover exact text/full-package preservation, scoped reuse, stale edits,
revision history, decision-only approval invalidation, production admission
and replay, crash recovery, and the real Host managed-action/artifact/handoff
path. Paid provider output and visual fidelity still require live acceptance.
