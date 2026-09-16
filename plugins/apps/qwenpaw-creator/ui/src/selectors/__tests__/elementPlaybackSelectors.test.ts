import { describe, expect, it } from "vitest";
import type {
  ProjectDocument,
  TaskView,
  TimelineElementDocument,
} from "@/contracts/creator";
import {
  playbackLayersAtTick,
  playbackLayersInWindow,
  resolveElementPlayback,
  transitionOpacityAtTick,
} from "@/selectors/elementPlaybackSelectors";
import { classifyElementTrack } from "@/selectors/timelineElementSelectors";
import { projectDocument } from "@/test/creatorFixtures";

function cloneProject(): ProjectDocument {
  return structuredClone(projectDocument);
}

function timelineOf(project: ProjectDocument) {
  return project.timelines.items["timeline:main"];
}

const resolve = (project: ProjectDocument, id: string, tasks?: TaskView[]) =>
  resolveElementPlayback(
    project,
    timelineOf(project),
    timelineOf(project).elements_by_id[id],
    tasks,
  );

const opacity = (
  timeline: ReturnType<typeof timelineOf>,
  id: string,
  tick: number,
) => transitionOpacityAtTick(timeline, timeline.elements_by_id[id], tick);

function task(overrides: Partial<TaskView>): TaskView {
  return {
    id: "task-1",
    projectId: "p1",
    transactionId: null,
    specialistRunId: null,
    kind: "r2v_generation",
    targetRef: "element:r2v-window",
    status: "RUNNING",
    progress: null,
    resultRefs: [],
    createdAt: "2026-07-20T00:00:00Z",
    ...overrides,
  };
}

describe("resolveElementPlayback", () => {
  it("marks a designed motion clip ready and keeps its clip-track slot", () => {
    const project = cloneProject();
    timelineOf(project).elements_by_id["clip-scene"] = {
      element_id: "clip-scene",
      enabled: true,
      span: { start_tick: 0, duration_tick: 4000 },
      z_index: 0,
      creation: {
        type: "motion_clip",
        motion: { format: "html_js", html_file_id: "file-motion-doc" },
      },
      outputs: {},
      render_source: null,
    } as unknown as TimelineElementDocument;
    // The designed document is the picture; the backend rasterizes it at
    // composite time, so the segment must not stay "pending" forever.
    expect(resolve(project, "clip-scene").status).toBe("ready");
    expect(
      classifyElementTrack(timelineOf(project).elements_by_id["clip-scene"]),
    ).toBe("clip");
  });

  it("resolves edit elements from their source asset render_source", () => {
    const playback = resolve(cloneProject(), "edit-opening");
    expect(playback.status).toBe("ready");
    expect(playback.media).toMatchObject({
      url: "/api/qwenpaw-creator/media/assets/cat-video-v1",
      mediaKind: "video",
      versionId: "cat-video-v1",
      sourceInSeconds: 0,
      sourceOutSeconds: 8,
      playbackRate: 1,
    });
  });

  it("resolves r2v via element_output and falls back when render_source is missing", () => {
    const project = cloneProject();
    const withSource = resolve(project, "r2v-window");
    expect(withSource.status).toBe("ready");
    expect(withSource.media).toMatchObject({
      url: "/api/qwenpaw-creator/media/artifacts/r2v-window-v1",
      mediaKind: "video",
      versionId: "r2v-window-v1",
    });
    timelineOf(project).elements_by_id["r2v-window"].render_source = null;
    const fallback = resolve(project, "r2v-window");
    expect(fallback.status).toBe("ready");
    expect(fallback.media).toMatchObject({
      versionId: "r2v-window-v1",
      sourceInSeconds: 0,
      sourceOutSeconds: null,
    });
  });

  it("keeps stale media visible but excludes it from the ready state", () => {
    const project = cloneProject();
    project.assets.artifact_versions_by_id["r2v-window-v1"].stale = true;
    const playback = resolve(project, "r2v-window");
    expect(playback.status).toBe("stale");
    expect(playback.media).toMatchObject({
      versionId: "r2v-window-v1",
      stale: true,
    });
  });

  it("maps the related Task status when no media is available", () => {
    const project = cloneProject();
    const element = timelineOf(project).elements_by_id["r2v-window"];
    element.render_source = null;
    element.outputs = {};
    for (const [status, expected] of [
      ["RUNNING", "generating"],
      ["QUEUED", "queued"],
      ["FAILED", "failed"],
    ] as const) {
      expect(resolve(project, "r2v-window", [task({ status })]).status).toBe(
        expected,
      );
    }
    expect(resolve(project, "r2v-window").status).toBe("pending");
  });

  it("treats a slot without a selected version as not ready", () => {
    const project = cloneProject();
    project.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = null;
    const playback = resolve(project, "r2v-window", [
      task({ status: "RUNNING" }),
    ]);
    expect(playback.status).toBe("generating");
    expect(playback.media).toBeNull();
  });

  it.each([
    ["copy overlay", "overlay-os"],
    ["generated HTML/CSS motion overlay", "overlay-title"],
    ["transition", "transition"],
  ])("marks a %s ready without a media layer", (_kind, elementId) => {
    const playback = resolve(cloneProject(), elementId);
    expect(playback.status).toBe("ready");
    expect(playback.media).toBeNull();
  });

  it("keeps motion overlays pending when no motion document or artifact exists", () => {
    const project = cloneProject();
    const element = timelineOf(project).elements_by_id["overlay-title"];
    if (element.creation.type === "overlay") {
      // A text-free decoration overlay without a designed document has
      // nothing to preview; captions (non-empty text) stay ready instead.
      element.creation.text = "";
      element.creation.motion = null;
    }
    expect(resolve(project, "overlay-title").status).toBe("pending");
  });
});

describe("playback layer selection", () => {
  it("returns overlapping layers sorted by z_index and skips disabled elements", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const ids = () =>
      playbackLayersAtTick(project, timeline, 7000).map(
        (layer) => layer.element.element_id,
      );
    expect(ids()).toEqual([
      "audio-bgm",
      "edit-opening",
      "r2v-window",
      "overlay-os",
    ]);
    timeline.elements_by_id["edit-opening"].enabled = false;
    expect(ids()).not.toContain("edit-opening");
  });

  it("premounts layers around the playhead within the window", () => {
    const project = cloneProject();
    const layers = playbackLayersInWindow(project, timelineOf(project), 0);
    expect(layers.map((layer) => layer.element.element_id)).toEqual([
      "audio-bgm",
      "edit-opening",
      "r2v-window",
      "overlay-title",
      "overlay-os",
    ]);
  });
});

describe("transitionOpacityAtTick", () => {
  // Fixture facts: transition window [7000, 8000), edit-opening → r2v-window,
  // easing is ease-in-out.
  it("fades the incoming element and hides it during the pre-blend overlap", () => {
    const timeline = timelineOf(cloneProject());
    // r2v-window overlaps from 5000 but the blend starts at 7000: stays hidden.
    expect(opacity(timeline, "r2v-window", 6000)).toBe(0);
    expect(opacity(timeline, "r2v-window", 7000)).toBe(0);
    expect(opacity(timeline, "r2v-window", 7500)).toBeCloseTo(0.5);
    expect(opacity(timeline, "r2v-window", 8000)).toBe(1);
  });

  it("keeps the outgoing element and unrelated elements fully opaque", () => {
    const timeline = timelineOf(cloneProject());
    expect(opacity(timeline, "edit-opening", 7500)).toBe(1);
    expect(opacity(timeline, "overlay-os", 7500)).toBe(1);
  });

  it("ignores disabled transitions and hard cuts", () => {
    const timeline = timelineOf(cloneProject());
    timeline.elements_by_id.transition.enabled = false;
    expect(opacity(timeline, "r2v-window", 7500)).toBe(1);
    timeline.elements_by_id.transition.enabled = true;
    if (timeline.elements_by_id.transition.creation.type === "transition") {
      timeline.elements_by_id.transition.creation.transition_kind = "cut";
    }
    expect(opacity(timeline, "r2v-window", 7500)).toBe(1);
  });

  it("applies the declared easing to the fade progress", () => {
    const timeline = timelineOf(cloneProject());
    if (timeline.elements_by_id.transition.creation.type === "transition") {
      timeline.elements_by_id.transition.creation.easing = "ease-in";
    }
    // ease-in yields 0.0625 at 25% progress.
    expect(opacity(timeline, "r2v-window", 7250)).toBeCloseTo(0.0625);
  });
});
