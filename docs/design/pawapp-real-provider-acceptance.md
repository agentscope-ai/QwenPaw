# PawApp Creator real-provider acceptance

P2 requires one explicitly authorized real provider run through Creator's
durable `generate-video` action. The runner at
`plugins/apps/qwenpaw-creator/backend/scripts/pawapp_real_video_acceptance.py`
keeps that run narrow and reviewable:

- preflight performs no provider call and prints no credential, prompt, or
  provider task ID;
- the runner is pinned to Beijing `wan3.0-video-prime`, two output seconds,
  480P, and image-only references;
- it copies the selected Project and its assets into a private run directory,
  without prior Runtime tasks, reviews, logs, or sessions;
- the copied model configuration remains encrypted at rest with owner-only
  permissions;
- the Host policy grants only the exact copied `project_id` and `target_ref`;
- a durable manifest claims the provider submission before network I/O and
  refuses a second submission across process restarts;
- success requires a terminal Host task, one Creator `VideoAsset`, and the
  same bytes published through the Host artifact store.

Run the free preflight first:

```bash
uv run python \
  plugins/apps/qwenpaw-creator/backend/scripts/pawapp_real_video_acceptance.py \
  --source-data-root /absolute/path/to/creator-runtime \
  --project-id PROJECT_ID \
  --target-ref element:ELEMENT_ID
```

The billable command additionally requires an empty persistent run directory,
the exact confirmation token printed by preflight, the current unit price, and
a maximum accepted charge no greater than CNY 2.00:

```bash
uv run python \
  plugins/apps/qwenpaw-creator/backend/scripts/pawapp_real_video_acceptance.py \
  --source-data-root /absolute/path/to/creator-runtime \
  --project-id PROJECT_ID \
  --target-ref element:ELEMENT_ID \
  --run-dir /absolute/private/path/to/acceptance-run \
  --confirm-billable-call I_ACCEPT_ONE_PROVIDER_SUBMISSION \
  --acknowledged-unit-price-cny CURRENT_PRICE \
  --max-charge-cny ACCEPTED_CEILING
```

As of 2026-09-16, Alibaba Cloud lists Beijing
`wan3.0-video-prime` at CNY 0.45 per second for 480P, so this two-second,
image-only case has a CNY 0.90 list-price ceiling before any free quota. Verify
the current value on Alibaba Cloud's official
[model pricing](https://help.aliyun.com/en/model-studio/model-pricing) page
immediately before authorization.

The run directory is the recovery and evidence boundary. Re-run the identical
command with the same directory after an interruption. Do not delete it while
the provider job may still be active. `acceptance-manifest.json` records the
single-submit claim, and a successful run writes `acceptance-result.json` with
the Host task, Project, and artifact references.
