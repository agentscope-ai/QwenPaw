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
    const timeline = timelineOf(project);
    timeline.elements_by_id["clip-scene"] = {
      element_id: "clip-scene",
      label: "开场题面",
      enabled: true,
      span: { start_tick: 0, duration_tick: 4000 },
      location: null,
      z_index: 0,
      creation: {
        type: "motion_clip",
        intent: "",
        prompt: "开场题面",
        motion: {
          format: "html_js",
          html: null,
          html_file_id: "file-motion-doc",
          fps: 24,
          loop: false,
        },
      },
      outputs: {},
      render_source: null,
      provenance_refs: [],
    } as unknown as TimelineElementDocument;
    const element = timeline.elements_by_id["clip-scene"];
    const playback = resolveElementPlayback(project, timeline, element);
    // The designed document is the picture; the backend rasterizes it at
    // composite time, so the segment must not stay "pending" forever.
    expect(playback.status).toBe("ready");
    expect(classifyElementTrack(element)).toBe("clip");
  });

  it("resolves edit elements from their source asset render_source", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const playback = resolveElementPlayback(
      project,
      timeline,
      timeline.elements_by_id["edit-opening"],
    );
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

  it("resolves r2v elements through element_output onto the selected artifact", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const playback = resolveElementPlayback(
      project,
      timeline,
      timeline.elements_by_id["r2v-window"],
    );
    expect(playback.status).toBe("ready");
    expect(playback.media).toMatchObject({
      url: "/api/qwenpaw-creator/media/artifacts/r2v-window-v1",
      mediaKind: "video",
      versionId: "r2v-window-v1",
    });
  });

  it("keeps stale media visible but excludes it from the ready state", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    project.assets.artifact_versions_by_id["r2v-window-v1"].stale = true;
    project.assets.artifact_versions_by_id["r2v-window-v1"].stale_reason =
      "生成输入已修改";

    const playback = resolveElementPlayback(
      project,
      timeline,
      timeline.elements_by_id["r2v-window"],
    );
    expect(playback.status).toBe("stale");
    expect(playback.media).toMatchObject({
      versionId: "r2v-window-v1",
      stale: true,
    });
  });

  it("falls back to selected outputs when render_source is missing", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const element = timeline.elements_by_id["r2v-window"];
    element.render_source = null;
    const playback = resolveElementPlayback(project, timeline, element);
    expect(playback.status).toBe("ready");
    expect(playback.media).toMatchObject({
      versionId: "r2v-window-v1",
      sourceInSeconds: 0,
      sourceOutSeconds: null,
    });
  });

  it("maps the related Task status when no media is available", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const element = timeline.elements_by_id["r2v-window"];
    element.render_source = null;
    element.outputs = {};

    expect(
      resolveElementPlayback(project, timeline, element, [
        task({ status: "RUNNING" }),
      ]).status,
    ).toBe("generating");
    expect(
      resolveElementPlayback(project, timeline, element, [
        task({ status: "QUEUED" }),
      ]).status,
    ).toBe("queued");
    expect(
      resolveElementPlayback(project, timeline, element, [
        task({ status: "FAILED" }),
      ]).status,
    ).toBe("failed");
    expect(resolveElementPlayback(project, timeline, element).status).toBe(
      "pending",
    );
  });

  it("treats a slot without a selected version as not ready", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const element = timeline.elements_by_id["r2v-window"];
    project.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = null;
    const playback = resolveElementPlayback(project, timeline, element, [
      task({ status: "RUNNING" }),
    ]);
    expect(playback.status).toBe("generating");
    expect(playback.media).toBeNull();
  });

  it("marks copy overlays (pet_os/interview_summary) ready for deterministic rendering", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const playback = resolveElementPlayback(
      project,
      timeline,
      timeline.elements_by_id["overlay-os"],
    );
    expect(playback.status).toBe("ready");
    expect(playback.media).toBeNull();
  });

  it("marks generated HTML/CSS motion overlays ready for browser preview", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const playback = resolveElementPlayback(
      project,
      timeline,
      timeline.elements_by_id["overlay-title"],
    );
    expect(playback.status).toBe("ready");
    expect(playback.media).toBeNull();
  });

  it("keeps motion overlays pending when no motion document or artifact exists", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const element = timeline.elements_by_id["overlay-title"];
    if (element.creation.type === "overlay") {
      // A text-free decoration overlay without a designed document has
      // nothing to preview; captions (non-empty text) stay ready instead.
      element.creation.text = "";
      element.creation.motion = null;
    }
    expect(resolveElementPlayback(project, timeline, element).status).toBe(
      "pending",
    );
  });

  it("treats transitions as ready without a media layer", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const playback = resolveElementPlayback(
      project,
      timeline,
      timeline.elements_by_id.transition,
    );
    expect(playback.status).toBe("ready");
    expect(playback.media).toBeNull();
  });
});

describe("playbackLayersAtTick", () => {
  it("returns overlapping layers sorted by z_index without transitions", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const layers = playbackLayersAtTick(project, timeline, 7000);
    expect(layers.map((layer) => layer.element.element_id)).toEqual([
      "audio-bgm",
      "edit-opening",
      "r2v-window",
      "overlay-os",
    ]);
  });

  it("skips disabled elements", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    (
      timeline.elements_by_id["edit-opening"] as TimelineElementDocument
    ).enabled = false;
    const layers = playbackLayersAtTick(project, timeline, 7000);
    expect(layers.map((layer) => layer.element.element_id)).not.toContain(
      "edit-opening",
    );
  });
});

describe("playbackLayersInWindow", () => {
  it("premounts layers around the playhead within the window", () => {
    const project = cloneProject();
    const timeline = timelineOf(project);
    const layers = playbackLayersInWindow(project, timeline, 0);
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
  it("fades the incoming element across the transition window", () => {
    const timeline = timelineOf(cloneProject());
    const incoming = timeline.elements_by_id["r2v-window"];
    expect(transitionOpacityAtTick(timeline, incoming, 7000)).toBe(0);
    expect(transitionOpacityAtTick(timeline, incoming, 7500)).toBeCloseTo(0.5);
    expect(transitionOpacityAtTick(timeline, incoming, 8000)).toBe(1);
  });

  it("hides the incoming element during the pre-blend overlap", () => {
    const timeline = timelineOf(cloneProject());
    const incoming = timeline.elements_by_id["r2v-window"];
    // r2v-window overlaps from 5000 but the blend starts at 7000: stays hidden.
    expect(transitionOpacityAtTick(timeline, incoming, 6000)).toBe(0);
  });

  it("keeps the outgoing element and unrelated elements fully opaque", () => {
    const timeline = timelineOf(cloneProject());
    expect(
      transitionOpacityAtTick(
        timeline,
        timeline.elements_by_id["edit-opening"],
        7500,
      ),
    ).toBe(1);
    expect(
      transitionOpacityAtTick(
        timeline,
        timeline.elements_by_id["overlay-os"],
        7500,
      ),
    ).toBe(1);
  });

  it("ignores disabled transitions and hard cuts", () => {
    const timeline = timelineOf(cloneProject());
    const incoming = timeline.elements_by_id["r2v-window"];
    timeline.elements_by_id.transition.enabled = false;
    expect(transitionOpacityAtTick(timeline, incoming, 7500)).toBe(1);
    timeline.elements_by_id.transition.enabled = true;
    if (timeline.elements_by_id.transition.creation.type === "transition") {
      timeline.elements_by_id.transition.creation.transition_kind = "cut";
    }
    expect(transitionOpacityAtTick(timeline, incoming, 7500)).toBe(1);
  });

  it("applies the declared easing to the fade progress", () => {
    const timeline = timelineOf(cloneProject());
    const incoming = timeline.elements_by_id["r2v-window"];
    if (timeline.elements_by_id.transition.creation.type === "transition") {
      timeline.elements_by_id.transition.creation.easing = "ease-in";
    }
    // ease-in yields 0.0625 at 25% progress.
    expect(transitionOpacityAtTick(timeline, incoming, 7250)).toBeCloseTo(
      0.0625,
    );
  });
});
