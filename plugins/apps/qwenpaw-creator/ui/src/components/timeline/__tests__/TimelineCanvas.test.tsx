import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TimelineCanvas from "@/components/timeline/TimelineCanvas";
import { projectDocument } from "@/test/creatorFixtures";

describe("TimelineCanvas preview scrubber", () => {
  it("keeps the global Timeline playhead visible and follows preview time", () => {
    const project = structuredClone(projectDocument);
    const timeline = project.timelines.items["timeline:main"];
    const props = {
      project,
      timeline,
      durationTick: 20000,
      selectedElementId: null,
      previewOpen: true,
      tasks: [],
      onPreviewOpenChange: vi.fn(),
      onPlayheadChange: vi.fn(),
      onSelectElement: vi.fn(),
      onActiveElementIdsChange: vi.fn(),
    };

    const { container, rerender } = render(
      <TimelineCanvas {...props} playheadTick={2000} />,
    );
    const playhead = container.querySelector(
      "[data-timeline-playhead]",
    ) as HTMLDivElement;
    const initialLeft = playhead.style.left;

    expect(playhead).toHaveClass("border-l-2", "border-[var(--color-accent)]");

    rerender(<TimelineCanvas {...props} playheadTick={12000} />);

    expect(playhead.style.left).not.toBe(initialLeft);
    expect(playhead.style.left).toContain("0.6");
  });

  it("positions the selection toolbar beside the selected line's upper-right", () => {
    const project = structuredClone(projectDocument);
    const timeline = project.timelines.items["timeline:main"];
    const { container } = render(
      <TimelineCanvas
        project={project}
        timeline={timeline}
        durationTick={20000}
        playheadTick={2000}
        selectedElementId={null}
        previewOpen
        tasks={[]}
        onPreviewOpenChange={vi.fn()}
        onPlayheadChange={vi.fn()}
        onSelectElement={vi.fn()}
        onActiveElementIdsChange={vi.fn()}
      />,
    );
    const chart = container.querySelector(
      "[data-timeline-chart]",
    ) as HTMLDivElement;
    vi.spyOn(chart, "getBoundingClientRect").mockReturnValue({
      x: 100,
      y: 300,
      left: 100,
      top: 300,
      right: 700,
      bottom: 500,
      width: 600,
      height: 200,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(chart, {
      button: 0,
      pointerId: 11,
      clientX: 300,
    });
    fireEvent.pointerUp(chart, {
      button: 0,
      pointerId: 11,
      clientX: 300,
    });

    const toolbar = document.querySelector(
      "[data-timeline-selection-toolbar]",
    ) as HTMLDivElement;
    expect(toolbar).toHaveStyle({ top: "262px" });
    expect(Number.parseFloat(toolbar.style.left)).toBeCloseTo(308, 0);
    expect(
      container.querySelector("[data-timeline-selection-range]"),
    ).not.toBeInTheDocument();
    expect(container.querySelectorAll("[data-timeline-playhead]")).toHaveLength(
      1,
    );
  });

  it("renders adaptive major and minor scale ticks with aligned track guides", () => {
    const project = structuredClone(projectDocument);
    const timeline = project.timelines.items["timeline:main"];
    const { container } = render(
      <TimelineCanvas
        project={project}
        timeline={timeline}
        durationTick={20000}
        playheadTick={2000}
        selectedElementId={null}
        previewOpen={false}
        tasks={[]}
        onPreviewOpenChange={vi.fn()}
        onPlayheadChange={vi.fn()}
        onSelectElement={vi.fn()}
        onActiveElementIdsChange={vi.fn()}
      />,
    );

    const scale = container.querySelector("[data-timeline-scale]");
    const majorTicks = scale?.querySelectorAll(
      '[data-timeline-scale-tick][data-major="true"]',
    );
    const minorTicks = scale?.querySelectorAll(
      '[data-timeline-scale-tick][data-major="false"]',
    );

    expect(scale).toBeInTheDocument();
    expect(majorTicks?.length).toBeGreaterThanOrEqual(5);
    expect(minorTicks?.length).toBeGreaterThan(0);
    expect(container.querySelector("[data-timeline-grid]")).toBeInTheDocument();
  });

  it("moves the shared playhead throughout a real pointer drag", () => {
    const project = structuredClone(projectDocument);
    const timeline = project.timelines.items["timeline:main"];
    const onPlayheadChange = vi.fn();

    render(
      <TimelineCanvas
        project={project}
        timeline={timeline}
        durationTick={20000}
        playheadTick={2000}
        selectedElementId={null}
        previewOpen
        tasks={[]}
        onPreviewOpenChange={vi.fn()}
        onPlayheadChange={onPlayheadChange}
        onSelectElement={vi.fn()}
        onActiveElementIdsChange={vi.fn()}
      />,
    );

    const scrubber = screen.getByRole("slider", {
      name: "拖动预览时间轴",
    });
    vi.spyOn(scrubber, "getBoundingClientRect").mockReturnValue({
      x: 100,
      y: 400,
      left: 100,
      top: 400,
      right: 500,
      bottom: 428,
      width: 400,
      height: 28,
      toJSON: () => ({}),
    });

    fireEvent.pointerDown(scrubber, {
      button: 0,
      buttons: 1,
      pointerId: 7,
      clientX: 200,
    });
    fireEvent.pointerMove(scrubber, {
      buttons: 1,
      pointerId: 7,
      clientX: 440,
    });
    fireEvent.pointerUp(scrubber, {
      button: 0,
      pointerId: 7,
      clientX: 440,
    });

    expect(onPlayheadChange.mock.calls.map(([tick]) => tick)).toEqual([
      5000, 17000, 17000,
    ]);
  });

  it("supports keyboard seeking on the preview progress bar", () => {
    const project = structuredClone(projectDocument);
    const timeline = project.timelines.items["timeline:main"];
    const onPlayheadChange = vi.fn();

    render(
      <TimelineCanvas
        project={project}
        timeline={timeline}
        durationTick={20000}
        playheadTick={2000}
        selectedElementId={null}
        previewOpen
        tasks={[]}
        onPreviewOpenChange={vi.fn()}
        onPlayheadChange={onPlayheadChange}
        onSelectElement={vi.fn()}
        onActiveElementIdsChange={vi.fn()}
      />,
    );

    const scrubber = screen.getByRole("slider", {
      name: "拖动预览时间轴",
    });
    fireEvent.keyDown(scrubber, { key: "ArrowRight" });
    fireEvent.keyDown(scrubber, { key: "End" });

    expect(onPlayheadChange.mock.calls.map(([tick]) => tick)).toEqual([
      3000, 20000,
    ]);
  });

  it("covers the final render until the requested frame finishes seeking", () => {
    vi.useFakeTimers();
    try {
      const project = structuredClone(projectDocument);
      const timeline = project.timelines.items["timeline:main"];
      const { container } = render(
        <TimelineCanvas
          project={project}
          timeline={timeline}
          durationTick={20000}
          playheadTick={2000}
          selectedElementId={null}
          previewOpen
          tasks={[]}
          onPreviewOpenChange={vi.fn()}
          onPlayheadChange={vi.fn()}
          onSelectElement={vi.fn()}
          onActiveElementIdsChange={vi.fn()}
        />,
      );
      const video = container.querySelector(
        "[data-timeline-video-preview] video",
      ) as HTMLVideoElement;

      expect(
        container.querySelector("[data-final-preview-incomplete]"),
      ).toHaveTextContent("正在定位画面");

      Object.defineProperties(video, {
        duration: { configurable: true, value: 20 },
        readyState: { configurable: true, value: 2 },
      });
      fireEvent.loadedData(video);
      fireEvent.seeked(video);

      expect(
        container.querySelector("[data-final-preview-incomplete]"),
      ).not.toBeInTheDocument();

      // A transient seek keeps the last painted frame: the opaque cover only
      // returns when the gap outlives the debounce window.
      Object.defineProperty(video, "seeking", {
        configurable: true,
        value: true,
      });
      fireEvent.seeking(video);
      expect(
        container.querySelector("[data-final-preview-incomplete]"),
      ).not.toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(400);
      });
      expect(
        container.querySelector("[data-final-preview-incomplete]"),
      ).toBeInTheDocument();

      // Finishing the seek clears the cover again.
      Object.defineProperty(video, "seeking", {
        configurable: true,
        value: false,
      });
      fireEvent.seeked(video);
      expect(
        container.querySelector("[data-final-preview-incomplete]"),
      ).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("recovers when media becomes ready without another canplay event", async () => {
    const project = structuredClone(projectDocument);
    const timeline = project.timelines.items["timeline:main"];
    const { container } = render(
      <TimelineCanvas
        project={project}
        timeline={timeline}
        durationTick={20000}
        playheadTick={0}
        selectedElementId={null}
        previewOpen
        tasks={[]}
        onPreviewOpenChange={vi.fn()}
        onPlayheadChange={vi.fn()}
        onSelectElement={vi.fn()}
        onActiveElementIdsChange={vi.fn()}
      />,
    );
    const video = container.querySelector(
      "[data-timeline-video-preview] video",
    ) as HTMLVideoElement;

    Object.defineProperties(video, {
      duration: { configurable: true, value: 20 },
      readyState: { configurable: true, value: 4 },
    });

    await waitFor(
      () =>
        expect(
          container.querySelector("[data-final-preview-incomplete]"),
        ).not.toBeInTheDocument(),
      { timeout: 1000 },
    );
  });

  it("uses completed stale frames outside the Element changed by the latest edit", () => {
    const project = structuredClone(projectDocument);
    const timeline = project.timelines.items["timeline:main"];
    const finalRender = project.assets.artifact_versions_by_id["final-v1"];
    finalRender.stale = true;
    finalRender.stale_reason = "时间线内容已修改，需要重新合成";
    finalRender.metadata.pendingAffectedElementIds = ["overlay-os"];
    const props = {
      project,
      timeline,
      durationTick: 20000,
      selectedElementId: null,
      previewOpen: true,
      tasks: [],
      onPreviewOpenChange: vi.fn(),
      onPlayheadChange: vi.fn(),
      onSelectElement: vi.fn(),
      onActiveElementIdsChange: vi.fn(),
    };

    const { container, rerender } = render(
      <TimelineCanvas {...props} playheadTick={5000} />,
    );
    const sourceChip = () =>
      container.querySelector("[data-preview-source-chip]");

    expect(sourceChip()).toHaveTextContent("未受影响 · 已完成画面");

    rerender(<TimelineCanvas {...props} playheadTick={6000} />);
    expect(sourceChip()).toHaveTextContent("内容已更新 · 实时预览");

    rerender(<TimelineCanvas {...props} playheadTick={10500} />);
    expect(sourceChip()).toHaveTextContent("未受影响 · 已完成画面");
  });
});
