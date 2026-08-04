import { fireEvent, render } from "@testing-library/react";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import TimelineLivePreview, {
  motionExitProgress,
  syncMotionAnimation,
} from "@/components/timeline/TimelineLivePreview";
import type { ProjectDocument, TaskView } from "@/contracts/creator";
import { projectDocument } from "@/test/creatorFixtures";

const originalClientWidth = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "clientWidth",
);
const originalClientHeight = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "clientHeight",
);

beforeAll(() => {
  // jsdom does no layout; give boxes a predictable size so the
  // final-render-style bubble SVG can be asserted.
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get() {
      return 640;
    },
  });
  Object.defineProperty(HTMLElement.prototype, "clientHeight", {
    configurable: true,
    get() {
      return 360;
    },
  });
});

afterAll(() => {
  // Restore the prototype to avoid polluting layout assertions in other test files.
  if (originalClientWidth) {
    Object.defineProperty(
      HTMLElement.prototype,
      "clientWidth",
      originalClientWidth,
    );
  } else {
    delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
  }
  if (originalClientHeight) {
    Object.defineProperty(
      HTMLElement.prototype,
      "clientHeight",
      originalClientHeight,
    );
  } else {
    delete (HTMLElement.prototype as { clientHeight?: number }).clientHeight;
  }
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

function renderPreview(
  project: ProjectDocument,
  playheadTick: number,
  tasks: TaskView[] = [],
) {
  const timeline = project.timelines.items["timeline:main"];
  return render(
    <TimelineLivePreview
      project={project}
      timeline={timeline}
      durationTick={20000}
      playheadTick={playheadTick}
      playing={false}
      muted={false}
      tasks={tasks}
      onPlayheadChange={vi.fn()}
      onPlayingChange={vi.fn()}
    />,
  );
}

describe("TimelineLivePreview", () => {
  it("starts exit motion in the final fifteen percent", () => {
    expect(motionExitProgress("soft_fade", 8400, 10000)).toBe(0);
    expect(motionExitProgress("soft_fade", 9250, 10000)).toBeCloseTo(0.5);
    expect(motionExitProgress("soft_fade", 10000, 10000)).toBe(1);
    expect(motionExitProgress("none", 10000, 10000)).toBe(0);
  });

  it("keeps finished entrance animations on their filled final frame", () => {
    const animation = {
      currentTime: 0,
      effect: { getComputedTiming: () => ({ endTime: 600 }) },
      pause: vi.fn(),
      play: vi.fn(),
    } as unknown as Animation;

    syncMotionAnimation(animation, 2000, true);

    expect(animation.currentTime).toBe(600);
    expect(animation.pause).toHaveBeenCalledOnce();
    expect(animation.play).not.toHaveBeenCalled();
  });

  it("continues infinite ambient animations while preview is playing", () => {
    const animation = {
      currentTime: 0,
      effect: { getComputedTiming: () => ({ endTime: Infinity }) },
      pause: vi.fn(),
      play: vi.fn(),
    } as unknown as Animation;

    syncMotionAnimation(animation, 2000, true);

    expect(animation.currentTime).toBe(2000);
    expect(animation.play).toHaveBeenCalledOnce();
    expect(animation.pause).not.toHaveBeenCalled();
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
    ).toEqual(["edit-opening", "r2v-window", "overlay-os"]);

    const editLayer = container.querySelector(
      '[data-live-layer="edit-opening"]',
    ) as HTMLVideoElement;
    expect(editLayer.tagName).toBe("VIDEO");
    expect(editLayer).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/assets/cat-video-v1",
    );
    expect(editLayer).not.toHaveClass("invisible");

    // Same convention as final composition: audio elements don't take part in
    // the preview.
    expect(
      container.querySelector('[data-live-layer="audio-bgm"]'),
    ).not.toBeInTheDocument();

    // pet_os bubble drawn to the final-render spec: white bubble with black
    // border + tail + vibe emoji.
    const bubble = container.querySelector(
      '[data-live-text-overlay="overlay-os"] [data-overlay-copy="pet_os"]',
    ) as HTMLElement;
    expect(bubble).toBeInTheDocument();
    expect(bubble.querySelector("svg rect")).toHaveAttribute(
      "stroke",
      "#141414",
    );
    expect(bubble.querySelector("svg polygon")).toBeInTheDocument();
    expect(bubble).toHaveTextContent("午饭在哪里？");
    expect(bubble.textContent).toContain("😺");
  });

  it("cross-fades the incoming main-track layer inside the transition window", () => {
    // Transition window [7000, 8000): edit-opening → r2v-window, ease-in-out.
    const { container } = renderPreview(cloneProject(), 7500);

    const incoming = container.querySelector(
      '[data-live-layer="r2v-window"]',
    ) as HTMLVideoElement;
    const outgoing = container.querySelector(
      '[data-live-layer="edit-opening"]',
    ) as HTMLVideoElement;
    expect(Number(incoming.style.opacity)).toBeCloseTo(0.5);
    expect(Number(outgoing.style.opacity)).toBe(1);
  });

  it("keeps the incoming layer hidden before its transition starts", () => {
    // 6000 is already inside the overlap of both ends, but blending hasn't
    // started: the frame still belongs to the "from" side.
    const { container } = renderPreview(cloneProject(), 6000);

    const incoming = container.querySelector(
      '[data-live-layer="r2v-window"]',
    ) as HTMLVideoElement;
    expect(Number(incoming.style.opacity)).toBe(0);
  });

  it("covers the whole composite until every visible video has decoded the requested frame", () => {
    const { container } = renderPreview(cloneProject(), 7000);
    const visibleVideos = [
      ...container.querySelectorAll<HTMLVideoElement>(
        "[data-live-layer]:not(.invisible)",
      ),
    ];

    expect(visibleVideos).toHaveLength(2);
    expect(
      container.querySelector("[data-live-preview-incomplete]"),
    ).toHaveTextContent("正在定位画面");

    visibleVideos.forEach((video) => {
      Object.defineProperty(video, "readyState", {
        configurable: true,
        value: 2,
      });
      fireEvent.loadedData(video);
      fireEvent.seeked(video);
    });

    expect(
      container.querySelector("[data-live-preview-incomplete]"),
    ).not.toBeInTheDocument();
  });

  it("recognizes an already-decoded cached video again after the layer remounts", () => {
    const originalReadyState = Object.getOwnPropertyDescriptor(
      HTMLMediaElement.prototype,
      "readyState",
    );
    Object.defineProperty(HTMLMediaElement.prototype, "readyState", {
      configurable: true,
      get: () => 2,
    });
    try {
      const project = cloneProject();
      const timeline = project.timelines.items["timeline:main"];
      const props = {
        project,
        timeline,
        durationTick: 20000,
        playing: false,
        muted: false,
        tasks: [] as TaskView[],
        onPlayheadChange: vi.fn(),
        onPlayingChange: vi.fn(),
      };
      const { container, rerender } = render(
        <TimelineLivePreview {...props} playheadTick={0} />,
      );

      expect(
        container.querySelector('[data-live-layer="edit-opening"]'),
      ).toBeInTheDocument();
      expect(
        container.querySelector("[data-live-preview-incomplete]"),
      ).not.toBeInTheDocument();

      rerender(<TimelineLivePreview {...props} playheadTick={19000} />);
      expect(
        container.querySelector('[data-live-layer="edit-opening"]'),
      ).not.toBeInTheDocument();

      rerender(<TimelineLivePreview {...props} playheadTick={0} />);
      expect(
        container.querySelector('[data-live-layer="edit-opening"]'),
      ).toBeInTheDocument();
      expect(
        container.querySelector("[data-live-preview-incomplete]"),
      ).not.toBeInTheDocument();
    } finally {
      if (originalReadyState) {
        Object.defineProperty(
          HTMLMediaElement.prototype,
          "readyState",
          originalReadyState,
        );
      } else {
        delete (HTMLMediaElement.prototype as { readyState?: number })
          .readyState;
      }
    }
  });

  it("premounts upcoming video layers invisibly for seamless handover", () => {
    const { container } = renderPreview(cloneProject(), 2000);
    const upcoming = container.querySelector(
      '[data-live-layer="r2v-window"]',
    ) as HTMLVideoElement;
    expect(upcoming).toHaveClass("invisible");
    expect(upcoming).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/r2v-window-v1",
    );
  });

  it("renders generated HTML/CSS motion overlays instead of placeholders", () => {
    const { container } = renderPreview(cloneProject(), 2000);
    const motion = container.querySelector(
      '[data-live-motion-overlay="overlay-title"]',
    ) as HTMLIFrameElement;
    expect(motion).toBeInTheDocument();
    expect(motion).toHaveAttribute("sandbox", "allow-same-origin");
    expect(motion.srcdoc).toContain("小猫出发");
    expect(
      container.querySelector('[data-live-placeholder="overlay-title"]'),
    ).not.toBeInTheDocument();
  });

  it("reduces older agent paw trails to the trusted three-paw sequence", () => {
    const project = cloneProject();
    const overlay =
      project.timelines.items["timeline:main"].elements_by_id["overlay-title"];
    if (overlay.creation.type !== "overlay" || !overlay.creation.motion) {
      throw new Error("expected generated motion overlay");
    }
    overlay.creation.motion.html =
      '<html><head></head><body><div data-motion-motif="paw_trail"><i class="p5"></i></div></body></html>';

    const { container } = renderPreview(project, 2000);
    const iframe = container.querySelector(
      '[data-live-motion-overlay="overlay-title"]',
    ) as HTMLIFrameElement;
    expect(iframe.srcdoc).toContain("data-qwenpaw-motion-compat");
    expect(iframe.srcdoc).toContain(".p5{display:none!important}");
    expect(iframe.srcdoc).toContain("qwenpaw-paw-appear");
  });

  it("hides retired motion motifs already stored in older projects", () => {
    const project = cloneProject();
    const overlay =
      project.timelines.items["timeline:main"].elements_by_id["overlay-title"];
    if (overlay.creation.type !== "overlay" || !overlay.creation.motion) {
      throw new Error("expected generated motion overlay");
    }
    overlay.creation.motion.html =
      '<html><body><div data-motion-motif="surprised_cat"></div></body></html>';

    const { container } = renderPreview(project, 2000);
    expect(
      container.querySelector('[data-live-motion-overlay="overlay-title"]'),
    ).not.toBeInTheDocument();
  });

  it("normalizes generated OS text effects for readable preview", () => {
    const project = cloneProject();
    const overlay =
      project.timelines.items["timeline:main"].elements_by_id["overlay-os"];
    if (overlay.creation.type !== "overlay")
      throw new Error("expected overlay");
    overlay.creation.motion = {
      format: "html_css",
      html: '<html><head></head><body><div class="text-row">午饭在哪里？</div></body></html>',
      fps: 24,
      loop: false,
      design_notes: "test",
    };

    const { container } = renderPreview(project, 7000);
    const iframe = container.querySelector(
      '[data-live-motion-overlay="overlay-os"]',
    ) as HTMLIFrameElement;

    expect(iframe.srcdoc).toContain("data-qwenpaw-viewport-safety");
    expect(iframe.srcdoc).toContain("-webkit-text-stroke:0!important");
    expect(iframe.srcdoc).toContain("font-size:min(18vh,20vw)!important");
    expect(iframe.srcdoc).toContain("line-height:1.15!important");
    expect(iframe.srcdoc).toContain("white-space:normal!important");
    expect(iframe.srcdoc).toContain("overflow:visible!important");
    expect(iframe.srcdoc).toContain("transform:scale(.9)!important");
  });

  it("renders a full-frame generating placeholder while the r2v artifact is still pending", () => {
    const project = cloneProject();
    project.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = null;
    const { container } = renderPreview(project, 9000, [
      runningTask("r2v-window"),
    ]);

    const placeholder = container.querySelector(
      '[data-live-placeholder="r2v-window"]',
    ) as HTMLElement;
    expect(placeholder).toBeInTheDocument();
    expect(placeholder).toHaveAttribute(
      "data-live-placeholder-state",
      "generating",
    );
    expect(placeholder).toHaveTextContent("画面生成中");
    expect(placeholder.style.width).toBe("100%");
    // Layers stay mounted in the background, but the full-frame notice covers
    // the half-assembled composition.
    expect(
      container.querySelector('[data-live-text-overlay="overlay-os"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector("[data-live-preview-incomplete]"),
    ).toHaveTextContent("该时间点尚未渲染完成");
  });

  it("keeps unready located overlays visible as positioned dashed placeholders", () => {
    const project = cloneProject();
    const timeline = project.timelines.items["timeline:main"];
    const overlay = timeline.elements_by_id["overlay-os"];
    if (overlay.creation.type === "overlay") overlay.creation.text = "";
    const { container } = renderPreview(project, 7000);

    const placeholder = container.querySelector(
      '[data-live-placeholder="overlay-os"]',
    ) as HTMLElement;
    expect(placeholder).toBeInTheDocument();
    expect(placeholder).toHaveAttribute(
      "data-live-placeholder-state",
      "pending",
    );
    expect(placeholder.className).toContain("border-dashed");
    expect(placeholder.style.left).toBe("51%");
    expect(placeholder.style.width).toBe("42%");
    // The ready video layer underneath stays pre-mounted; visually it is fully
    // covered by the full-frame notice.
    expect(
      container.querySelector('[data-live-layer="edit-opening"]'),
    ).not.toHaveClass("invisible");
    expect(
      container.querySelector("[data-live-preview-incomplete]"),
    ).toHaveTextContent("完整画面就绪后才能预览");
  });

  it("hot-swaps a placeholder into a real media layer once the artifact arrives", () => {
    const pendingProject = cloneProject();
    pendingProject.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = null;
    const timeline = pendingProject.timelines.items["timeline:main"];
    const { container, rerender } = render(
      <TimelineLivePreview
        project={pendingProject}
        timeline={timeline}
        durationTick={20000}
        playheadTick={9000}
        playing={false}
        muted={false}
        tasks={[runningTask("r2v-window")]}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );
    expect(
      container.querySelector('[data-live-placeholder="r2v-window"]'),
    ).toBeInTheDocument();

    const readyProject = cloneProject();
    rerender(
      <TimelineLivePreview
        project={readyProject}
        timeline={readyProject.timelines.items["timeline:main"]}
        durationTick={20000}
        playheadTick={9000}
        playing={false}
        muted={false}
        tasks={[]}
        onPlayheadChange={vi.fn()}
        onPlayingChange={vi.fn()}
      />,
    );
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

  it("seeks visible video layers onto the paused playhead", () => {
    const { container } = renderPreview(cloneProject(), 2000);
    const editLayer = container.querySelector(
      '[data-live-layer="edit-opening"]',
    ) as HTMLVideoElement;
    expect(editLayer.currentTime).toBeCloseTo(2, 3);
  });
});
