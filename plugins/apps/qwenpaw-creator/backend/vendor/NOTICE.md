# Third-Party Vendored Code Notice

This directory contains source code vendored (algorithm ported) from
third-party projects under their respective licenses. Vendoring follows the
project-wide rule set in
`docs/proposals/mm-plugins-creator-integration/MM_PLUGINS_INTEGRATION_PLAN.md`
(§2.2, technique B): no runtime dependency on the upstream package, no
environment-variable injection, no in-process invocation of upstream code.

## Qwen-MM-Plugins

- Upstream repository: Qwen-MM-Plugins
  (local mirror: `/Users/linxuanrui/Documents/projects/Project-Creator/Qwen-MM-Plugins`)
- Upstream baseline: `release` branch, commit `077aea6`
- License: Apache License 2.0 (see upstream `LICENSE`)
- Vendored location: `backend/vendor/mm_plugins/`

Per Apache-2.0 §4(b), every vendored file keeps an attribution header naming
the upstream path and commit, and states that the file carries modifications
for QwenPaw Creator. The canonical header template is:

```python
# Vendored from Qwen-MM-Plugins (Apache-2.0), release commit 077aea6.
# Upstream path: <path inside upstream repository>
# Modified for QwenPaw Creator. See backend/vendor/NOTICE.md.
```

### Module inventory

| Vendored module | Upstream source | Modifications |
| --- | --- | --- |
| `mm_plugins/image_budget.py` | `src/shared/image.py` (`budget_to_pixels`, `smart_resize`) + constants from `src/shared/env.py` | Constants inlined (no env lookups); `smart_resize` floors the over-budget branch (matching canonical `qwen_vl_utils`) and shrinks the long side after short-side clamping so results never exceed the pixel budget, even at extreme aspect ratios. Kept byte-identical across vendoring branches. Render-review (WT4) adds the `VIDEO_BUDGET_TOKENS`/`VIDEO_MIN_PIXELS` constants as a pure additive block on top of the canonical copy. |
| `mm_plugins/renderers/__init__.py` | `src/capabilities/core/qwen_mm_plugins_core/renderers/__init__.py` | Registry trimmed to the formats Creator ships (no latex/model3d/geo/drawio/blender); renderers emit PIL images + meta blocks instead of base64 MCP blocks; `cached_pdf` replaced by caller-owned temp dirs; added `configure_matplotlib_cjk` so table images keep CJK text. |
| `mm_plugins/renderers/pdf.py` | `.../renderers/pdf.py` | Returns PIL page images with page numbers and text layers; response-size capping and base64 encoding removed (resizing/persistence is done by `services/document_reader.py`); full-text extraction decoupled from the rendered page range via `full_text` blocks (`max_text_pages`, default 500) with a structured `extraction_note` block when the page cap cuts extraction short. |
| `mm_plugins/renderers/office.py` | `.../renderers/office.py` | `which_tool` lookup replaced by an explicit `soffice` executable argument resolved by Creator's runtime-dependency layer; conversion timeout raised to cover the macOS first-launch Gatekeeper scan. |
| `mm_plugins/renderers/data.py` | `.../renderers/data.py` | Emits PIL table images + markdown text blocks; sheet ordinal exposed as page number; table rendering prefers an installed CJK font; empty cells render blank instead of "nan"; the markdown row cap is overridable via `max_rows`; every sheet's complete rows (cap 100k) are emitted as `full_text` blocks independent of the displayed subset, with a structured `extraction_note` block when the row cap cuts extraction short. |
| `mm_plugins/renderers/subtitle.py` | `.../renderers/subtitle.py` | Added a minimal `.ass` dialogue parser (upstream supports SRT/VTT only). |
| `mm_plugins/renderers/code.py` | `.../renderers/code.py` | Verbatim aside from block meta additions; the line cap is overridable via `max_lines`, and the complete file is emitted as a `full_text` block when the display is truncated. |
| `mm_plugins/renderers/svg.py` | `.../renderers/svg.py` + `svg_to_image` from `src/shared/image.py` | `svg_to_image` inlined; returns a PIL image block. |
| `mm_plugins/renderers/notebook.py` | `.../renderers/notebook.py` | Output images decoded to PIL; base64 passthrough removed. |
| `mm_plugins/renderers/web.py` | `.../renderers/web.py` | Kept Playwright screenshot flow; enablement is config-gated by Creator (`CREATOR_DOC_READER_WEB_ENABLED`), Playwright is not a declared dependency. |
| `mm_plugins/review_rubrics.py` | `src/capabilities/video-edit/skill/review/final-review.md` (§D Appeal rubric `[rubric-verbatim]` rows, common failures), `review/scene-review.md` (six checks), `review/source-review.md` (technical probe fields) | Markdown tables ported to structured constants; row names and anchor questions kept verbatim. The upstream concept-veto ("<=5 caps the verdict at revise") is NOT ported — Creator run review is advisory, a weak concept becomes a major-severity suggestion. |
| `mm_plugins/review_gates.py` | `src/capabilities/video-edit/skill/scripts/black_check.sh`, `loudness_check.sh`, `review_gate.sh` | Shell gates ported to Python with thresholds preserved (blackdetect d=0.1/pix_th=0.10/grace=0.5; -inf and <-50 LUFS silence; -10/-24/-1.0 advisories; ffprobe→loudness→black order and the evidence-block hash). The upstream `exit 2` delivery-blocking semantics and plan gate are not ported — gate failures become advisory findings. |
| `mm_plugins/frame_stats.py` | `src/capabilities/video-edit/skill/scripts/auto_grade.py` (`probe_duration`, `sample_stats`, analyze judgments) | Analyze side only; `sys.exit` becomes `FrameStatsError`; still-image helper added. The eq-filter derivation/apply mode is intentionally not vendored (grading stays an opt-in art-direction decision). |

Formats intentionally not vendored: `latex`, `model3d`, `geo`, `drawio`,
`_blender_render`.

### Vendored modules (video-memory)

Ported from `src/capabilities/video-memory/` into
`backend/vendor/mm_plugins/video_memory/`:

| Vendored file | Upstream origin | Modifications |
|---|---|---|
| `schema.py` | `skill/script/build_memory/schema.py` | dropped the legacy `hierarchical_graph_final.json` loader; comments trimmed; `load` split into `from_payload` + file IO so merged in-memory graphs reuse the same parser |
| `prompts.py` | `skill/script/build_memory/prompts.py` | verbatim prompt constants |
| `time_utils.py` | `skill/script/build_memory/time_utils.py` | verbatim |
| `json_utils.py` | `skill/script/build_memory/llm_client.py` (`extract_json` only) | extracted the JSON-repair parser; the HTTP client itself is NOT vendored (rewritten as Creator-native clients) |
| `segmentation.py` | `skill/script/build_memory/build_graph.py` (Phase 1) | frame extraction/IO moved to the Creator service; OpenCV HLS conversion re-implemented with Pillow + NumPy; pure planning functions kept |
| `subgraph.py` | `skill/script/build_memory/build_graph.py` (Phase 2 parsing) | media clipping/upload and VLM transport removed (Creator `creator_vlm_model` backend is used instead); response parsing and relative→absolute time shifting kept |
| `aggregation.py` | `skill/script/build_memory/build_graph.py` (Phase 3) + `pipeline_worker.py` orchestration ideas | orchestration rewritten as `async` around an injected LLM callable; window/parse/fallback logic kept |
| `embeddings.py` | `skill/script/build_memory/embeddings.py` | DashScope HTTP client removed (rewritten as `backend/models/embedding_model.py`); BM25 index, hybrid RRF search and `.npz` persistence kept; search accepts a precomputed query embedding; tokenizer splits CJK runs into character bigrams for exact short-phrase BM25 matches; zero-score BM25 candidates no longer earn a sparse RRF rank |
| `toolkit.py` | `qwen_mm_plugins_video_memory/toolkit.py` + query logic of `loader.py` | EgoLife time system and cutoff support removed; methods return Python objects instead of JSON strings; embedding lookups take a precomputed query vector |
| `merge.py` | `skill/script/build_memory/merge_memories.py` | CLI entry point, `*.memory` directory scanning and embeddings-file IO removed (the Creator source-memory service owns artifact discovery, caching and index construction); ID prefixing, mechanical root synthesis and embedding-node ID rewriting kept |

Not vendored: `llm_client.py`, `env_config.py` (env-driven configuration is
replaced by the Creator config tree), the MCP server wrappers under
`qwen_mm_plugins_video_memory/tools/` (their query logic is reachable through
the vendored `toolkit.py`).
