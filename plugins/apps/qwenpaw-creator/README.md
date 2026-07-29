# QwenPaw Creator

Creator is a QwenPaw PawApp for file-native script, asset, storyboard, video
generation, editing, and composition workflows.

## Native runtime tools

Creator resolves native tools without modifying the host application's system
installation:

- `jq` powers the `jq_project` editing tool. Configure an absolute executable
  with `CREATOR_JQ_PATH`, or install `jq` on `PATH`.
- `ffmpeg` powers media probing, rendering, and composition. Configure
  `CREATOR_FFMPEG_PATH`; otherwise Creator uses system `ffmpeg` or the
  `imageio-ffmpeg` package fallback.
- `ffprobe` is optional. Configure `CREATOR_FFPROBE_PATH`; when absent, Creator
  falls back to `ffmpeg` metadata probing.
- `CREATOR_BINARY_DIR` selects Creator's managed executable directory and must
  be absolute.

Creator does **not** download executables during startup by default. To opt in
to downloading the pinned, SHA-256-verified jq release, set
`CREATOR_AUTO_INSTALL_BINARIES=1`. `CREATOR_JQ_BASE_URL` may select an approved
mirror. If jq is unavailable or the opt-in download fails, Creator starts in
degraded mode and reports the missing dependency through
`GET /api/qwenpaw-creator/health`; workflows that require `jq_project` remain
unavailable until jq is configured.

Model and OSS credentials should normally be configured through the six
`creator_*` entries in QwenPaw Tools. `.env.example` documents local-development
fallback variables.
