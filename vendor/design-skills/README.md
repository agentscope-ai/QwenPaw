# Hub design skill sources

Local Git clones, intentionally excluded from the parent Git repository to avoid accidental gitlinks.

- `make-interfaces-feel-better/`: https://github.com/jakubkrehel/make-interfaces-feel-better — revision `35545ea1512ad59fa463e6b1f95ca9c052981fe6`, MIT; entry: `skills/make-interfaces-feel-better/SKILL.md`.
- `claude-code/`: https://github.com/anthropics/claude-code — revision `68ac8bbf0245b615b41517bf8f2b2f35af1ae31d`, sparse checkout of `plugins/frontend-design`; entry: `plugins/frontend-design/skills/frontend-design/SKILL.md`. Original root LICENSE.md retained; skill mentions LICENSE.txt but that file is absent from this checkout.

Recreate with `git clone --depth 1` for the first repository, and `git clone --depth 1 --filter=blob:none --sparse` followed by `git sparse-checkout set plugins/frontend-design` for the second. Revisions above record the versions reviewed on 2026-09-17; a fresh shallow clone may use a newer revision.
