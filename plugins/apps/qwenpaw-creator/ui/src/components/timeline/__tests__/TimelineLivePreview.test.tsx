import { act, fireEvent, render } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import TimelineLivePreview, {
  syncMotionAnimation,
} from "@/components/timeline/TimelineLivePreview";
import type { ProjectDocument, TaskView } from "@/contracts/creator";
import { projectDocument } from "@/test/creatorFixtures";

/** Stub a prototype getter and return a restore function. */
function stubProtoGetter(proto: object, name: string, value: number) {
  const original = Object.getOwnPropertyDescriptor(proto, name);
  Object.defineProperty(proto, name, { configurable: true, get: () => value });
  return () => {
    if (original) Object.defineProperty(proto, name, original);
    else delete (proto as Record<string, unknown>)[name];
  };
}

const restores: Array<() => void> = [];

beforeAll(() => {
  restores.push(
    stubProtoGetter(HTMLElement.prototype, "clientWidth", 640),
    stubProtoGetter(HTMLElement.prototype, "clientHeight", 360),
  );
});

afterAll(() => {
  restores.splice(0).forEach((restore) => restore());
});

function cloneProject(): ProjectDocument {
  return structuredClone(projectDocument);
}

function runningTask(elementId: string): TaskView {
  return {
    id: "task-1",
    projectId: "p1",
    transactionId: null,
    specialistRunId: null,
    kind: "r2v_generation",
    targetRef: `element:${elementId}`,
    status: "RUNNING",
    progress: null,
    resultRefs: [],
    createdAt: "2026-07-20T00:00:00Z",
  };
}

function previewProps(
  project: ProjectDocument,
  playheadTick: number,
  tasks: TaskView[] = [],
) {
  return {
    project,
    timeline: project.timelines.items["timeline:main"],
    durationTick: 20000,
    playheadTick,
    playing: false,
    muted: false,
    tasks,
    onPlayheadChange: vi.fn(),
    onPlayingChange: vi.fn(),
  };
}

function renderPreview(...args: Parameters<typeof previewProps>) {
  return render(<TimelineLivePreview {...previewProps(...args)} />);
}

/** Grab an overlay creation from the main timeline for fixture mutation. */
function overlayCreation(project: ProjectDocument, id = "overlay-title") {
  const overlay = project.timelines.items["timeline:main"].elements_by_id[id];
  if (overlay.creation.type !== "overlay") {
    throw new Error("expected overlay Element");
  }
  return overlay.creation;
}

/** Simulate every given video finishing decode of the requested frame. */
function markDecoded(videos: Iterable<Element>) {
  for (const video of videos) {
    Object.defineProperty(video, "readyState", {
      configurable: true,
      value: 2,
    });
    fireEvent.loadedData(video);
    fireEvent.seeked(video);
  }
}

/** The opaque "frame not ready" cover, if currently shown. */
function incompleteNotice(container: HTMLElement) {
  return container.querySelector("[data-live-preview-incomplete]");
}

describe("TimelineLivePreview", () => {
  it.each<[string, number, number, "pause" | "play"]>([
    ["holds finished entrances on their filled final frame", 600, 600, "pause"],
    [
      "keeps infinite ambient loops running while playing",
      Infinity,
      2000,
      "play",
    ],
  ])("%s", (_name, endTime, expectedTime, expectedCall) => {
    const animation = {
      currentTime: 0,
      effect: { getComputedTiming: () => ({ endTime }) },
      pause: vi.fn(),
      play: vi.fn(),
    } as unknown as Animation;
    syncMotionAnimation(animation, 2000, true);

    expect(animation.currentTime).toBe(expectedTime);
    const other = expectedCall === "pause" ? "play" : "pause";
    expect(animation[expectedCall]).toHaveBeenCalledOnce();
    expect(animation[other]).not.toHaveBeenCalled();
  });

  it("stacks ready media and compose-grade copy overlays by z_index at the playhead", () => {
    const { container } = renderPreview(cloneProject(), 7000);

    const nodes = [
      ...container.querySelectorAll(
        "[data-live-layer], [data-live-text-overlay], [data-live-placeholder]",
      ),
    ];
    expect(
      nodes.map(
        (node) =>
          node.getAttribute("data-live-layer") ??
          node.getAttribute("data-live-text-overlay") ??
          node.getAttribute("data-live-placeholder"),
      ),
    ).toEqual(["audio-bgm", "edit-opening", "r2v-window", "overlay-os"]);

    const editLayer = container.querySelector(
      '[data-live-layer="edit-opening"]',
    ) as HTMLVideoElement;
    expect(editLayer.tagName).toBe("VIDEO");
    expect(editLayer).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/assets/cat-video-v1",
    );
    expect(editLayer).not.toHaveClass("invisible");

    // Narration/BGM plays through a hidden <audio> node.
    const audioLayer = container.querySelector(
      '[data-live-layer="audio-bgm"]',
    ) as HTMLAudioElement;
    expect(audioLayer.tagName).toBe("AUDIO");

    // pet_os bubble to final-render spec: white bubble, black border + tail.
    const bubble = container.querySelector(
      '[data-live-text-overlay="overlay-os"] [data-overlay-copy="pet_os"]',
    ) as HTMLElement;
    expect(bubble.querySelector("svg polygon")).toBeInTheDocument();
    expect(bubble).toHaveTextContent("午饭在哪里？");
  });

  it("cross-fades the incoming main-track layer only inside the transition window", () => {
    // Transition window [7000, 8000): edit-opening → r2v-window; at 6000
    // the frame still belongs to the "from" side.
    const { container, rerender } = renderPreview(cloneProject(), 6000);
    const incoming = container.querySelector(
      '[data-live-layer="r2v-window"]',
    ) as HTMLVideoElement;
    expect(Number(incoming.style.opacity)).toBe(0);

    rerender(<TimelineLivePreview {...previewProps(cloneProject(), 7500)} />);
    const outgoing = container.querySelector(
      '[data-live-layer="edit-opening"]',
    ) as HTMLVideoElement;
    const blended = container.querySelector(
      '[data-live-layer="r2v-window"]',
    ) as HTMLVideoElement;
    expect(Number(blended.style.opacity)).toBeCloseTo(0.5);
    expect(Number(outgoing.style.opacity)).toBe(1);
  });

  it("covers the composite until every visible video decodes, tolerating transient seeks", () => {
    vi.useFakeTimers();
    try {
      const { container } = renderPreview(cloneProject(), 7000);
      const visibleVideos = [
        ...container.querySelectorAll<HTMLVideoElement>(
          "video[data-live-layer]:not(.invisible)",
        ),
      ];
      expect(visibleVideos).toHaveLength(2);
      expect(incompleteNotice(container)).toHaveTextContent("正在定位画面");

      markDecoded(visibleVideos);
      expect(incompleteNotice(container)).not.toBeInTheDocument();

      // A drift-correction seek on an already-complete composite keeps the
      // last painted frame instead of flashing the opaque notice.
      const [firstVideo] = visibleVideos;
      Object.defineProperty(firstVideo, "seeking", {
        configurable: true,
        value: true,
      });
      fireEvent.seeking(firstVideo);
      expect(incompleteNotice(container)).not.toBeInTheDocument();

      // Only a persistent gap surfaces the notice.
      act(() => {
        vi.advanceTimersByTime(400);
      });
      expect(incompleteNotice(container)).toHaveTextContent("正在定位画面");

      Object.defineProperty(firstVideo, "seeking", {
        configurable: true,
        value: false,
      });
      fireEvent.seeked(firstVideo);
      expect(incompleteNotice(container)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("premounts upcoming video layers invisibly and seeks visible ones onto the paused playhead", () => {
    const { container } = renderPreview(cloneProject(), 2000);
    const upcoming = container.querySelector(
      '[data-live-layer="r2v-window"]',
    ) as HTMLVideoElement;
    expect(upcoming).toHaveClass("invisible");
    expect(upcoming).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/r2v-window-v1",
    );

    const editLayer = container.querySelector(
      '[data-live-layer="edit-opening"]',
    ) as HTMLVideoElement;
    expect(editLayer.currentTime).toBeCloseTo(2, 3);

    // Generated HTML/CSS motion overlays mount as sandboxed iframes.
    const motion = container.querySelector(
      '[data-live-motion-overlay="overlay-title"]',
    ) as HTMLIFrameElement;
    expect(motion).toHaveAttribute("sandbox", "allow-same-origin");
    expect(motion.srcdoc).toContain("小猫出发");
    expect(
      container.querySelector('[data-live-placeholder="overlay-title"]'),
    ).not.toBeInTheDocument();
  });

  it("previews html_js overlays as backend posters, never script iframes", () => {
    const project = cloneProject();
    // js timelines never execute in the preview sandbox; the layer must
    // show the deterministic backend poster instead of a dead iframe.
    Object.assign(overlayCreation(project).motion!, {
      format: "html_js",
      html: null,
      html_file_id: "file-motion-poster-test",
    });

    const { container } = renderPreview(project, 2000);
    const poster = container.querySelector(
      '[data-live-motion-overlay="overlay-title"]',
    ) as HTMLImageElement;
    expect(poster.tagName).toBe("IMG");
    expect(poster).toHaveAttribute("data-live-motion-poster", "true");
    expect(poster.getAttribute("src")).toContain(
      "/media/motion-documents/file-motion-poster-test/poster",
    );
    expect(poster.getAttribute("src")).toContain("format=html_js");
    expect(
      container.querySelector("iframe[data-live-motion-overlay]"),
    ).not.toBeInTheDocument();

    // A same-source player mounts alongside in an opaque-origin sandbox:
    // scripts may run, nothing else. Hidden until the document boots; the
    // poster underlay carries the first paint.
    const player = container.querySelector(
      'iframe[data-live-motion-player="overlay-title"]',
    ) as HTMLIFrameElement;
    expect(player.getAttribute("sandbox")).toBe("allow-scripts");
    expect(player.getAttribute("src")).toContain(
      "/media/motion-documents/file-motion-poster-test/preview",
    );
    expect(player.style.visibility).toBe("hidden");
  });

  // Inline html_js can't exist in committed Projects (schema rejects it) and
  // retired motifs may linger in old ones; both must render nothing instead
  // of a dead or off-brand document.
  it.each<[string, "format" | "html", string]>([
    ["fails closed for html_js without a poster", "format", "html_js"],
    [
      "hides retired motion motifs already stored in older projects",
      "html",
      '<html><body><div data-motion-motif="surprised_cat"></div></body></html>',
    ],
  ])("%s", (_name, key, value) => {
    const project = cloneProject();
    overlayCreation(project).motion![key] = value as never;
    const { container } = renderPreview(project, 2000);
    expect(
      container.querySelector('[data-live-motion-overlay="overlay-title"]'),
    ).not.toBeInTheDocument();
  });

  it("renders a full-frame generating placeholder and hot-swaps it into a real media layer", () => {
    const project = cloneProject();
    project.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = null;
    const { container, rerender } = renderPreview(project, 9000, [
      runningTask("r2v-window"),
    ]);

    const placeholder = container.querySelector(
      '[data-live-placeholder="r2v-window"]',
    ) as HTMLElement;
    expect(placeholder).toHaveAttribute(
      "data-live-placeholder-state",
      "generating",
    );
    expect(placeholder).toHaveTextContent("画面生成中");
    expect(placeholder.style.width).toBe("100%");
    expect(incompleteNotice(container)).toHaveTextContent(
      "该时间点尚未渲染完成",
    );

    // Once the artifact arrives the placeholder hot-swaps into the layer.
    rerender(<TimelineLivePreview {...previewProps(cloneProject(), 9000)} />);
    expect(
      container.querySelector('[data-live-placeholder="r2v-window"]'),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector('[data-live-layer="r2v-window"]'),
    ).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/r2v-window-v1",
    );
  });

  it("freezes a trimmed clip on the frame the readiness check expects", () => {
    // A clip cut from the middle of its source (source_in 2s, window 3s)
    // whose span outlives the window: the frozen frame must live at
    // source_in + window (the drift target) or the notice pins forever.
    const restore = stubProtoGetter(
      HTMLMediaElement.prototype,
      "duration",
      5.04,
    );
    try {
      const project = cloneProject();
      const timeline = project.timelines.items["timeline:main"];
      const source =
        timeline.elements_by_id["edit-opening"].render_source ?? ({} as never);
      Object.assign(source, {
        source_in_tick: 2000,
        source_out_tick: 5000,
      });
      const { container } = renderPreview(project, 4500);

      const editLayer = container.querySelector(
        '[data-live-layer="edit-opening"]',
      ) as HTMLVideoElement;
      expect(editLayer.currentTime).toBeCloseTo(2 + 3 - 0.033, 3);

      // Release every mounted video layer; with the old freeze offset the
      // notice below could never clear.
      markDecoded(container.querySelectorAll("[data-live-layer]"));
      container
        .querySelectorAll("[data-live-motion-overlay]")
        .forEach((frame) => fireEvent.load(frame));
      expect(incompleteNotice(container)).not.toBeInTheDocument();
    } finally {
      restore();
    }
  });
});
