import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TimelineCanvas from "@/components/timeline/TimelineCanvas";
import { projectDocument } from "@/test/creatorFixtures";

type CanvasProps = Parameters<typeof TimelineCanvas>[0];

function setup(overrides: Partial<CanvasProps> = {}) {
  const project = overrides.project ?? structuredClone(projectDocument);
  const timeline = project.timelines.items["timeline:main"];
  const props = {
    project,
    timeline,
    durationTick: 20000,
    playheadTick: 2000,
    selectedElementId: null,
    previewOpen: true,
    tasks: [],
    onPreviewOpenChange: vi.fn(),
    onPlayheadChange: vi.fn(),
    onSelectElement: vi.fn(),
    onActiveElementIdsChange: vi.fn(),
    ...overrides,
  };
  return { ...render(<TimelineCanvas {...props} />), props };
}

function mockRect(element: Element, rect: Partial<DOMRect>) {
  vi.spyOn(element, "getBoundingClientRect").mockReturnValue(rect as DOMRect);
}

const previewVideo = (container: HTMLElement) =>
  container.querySelector("[data-timeline-video-preview] video")!;

const incompleteCover = (container: HTMLElement) =>
  container.querySelector("[data-final-preview-incomplete]");

describe("TimelineCanvas preview scrubber", () => {
  it("moves the shared playhead throughout a real pointer drag", () => {
    const { props } = setup();
    const scrubber = screen.getByRole("slider", { name: "拖动预览时间轴" });
    mockRect(scrubber, {
      left: 100,
      top: 400,
      right: 500,
      bottom: 428,
      width: 400,
      height: 28,
    });

    fireEvent.pointerDown(scrubber, {
      button: 0,
      buttons: 1,
      pointerId: 7,
      clientX: 200,
    });
    fireEvent.pointerMove(scrubber, { buttons: 1, pointerId: 7, clientX: 440 });
    fireEvent.pointerUp(scrubber, { button: 0, pointerId: 7, clientX: 440 });

    expect(
      vi.mocked(props.onPlayheadChange).mock.calls.map(([tick]) => tick),
    ).toEqual([5000, 17000, 17000]);
  });

  it("covers the final render until the requested frame finishes seeking", () => {
    vi.useFakeTimers();
    try {
      const { container } = setup();
      const video = previewVideo(container);

      expect(incompleteCover(container)).toHaveTextContent("正在定位画面");

      Object.defineProperties(video, {
        duration: { configurable: true, value: 20 },
        readyState: { configurable: true, value: 2 },
      });
      fireEvent.loadedData(video);
      fireEvent.seeked(video);

      expect(incompleteCover(container)).not.toBeInTheDocument();

      // A transient seek keeps the last painted frame; the opaque cover only
      // returns when the gap outlives the debounce window.
      Object.defineProperty(video, "seeking", {
        configurable: true,
        value: true,
      });
      fireEvent.seeking(video);
      expect(incompleteCover(container)).not.toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(400);
      });
      expect(incompleteCover(container)).toBeInTheDocument();

      Object.defineProperty(video, "seeking", {
        configurable: true,
        value: false,
      });
      fireEvent.seeked(video);
      expect(incompleteCover(container)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("uses completed stale frames outside the Element changed by the latest edit", () => {
    const project = structuredClone(projectDocument);
    const finalRender = project.assets.artifact_versions_by_id["final-v1"];
    finalRender.stale = true;
    finalRender.stale_reason = "时间线内容已修改，需要重新合成";
    finalRender.metadata.pendingAffectedElementIds = ["overlay-os"];
    const { container, props, rerender } = setup({
      project,
      playheadTick: 5000,
    });
    const sourceChip = () =>
      container.querySelector("[data-preview-source-chip]");

    expect(sourceChip()).toHaveTextContent("未受影响 · 已完成画面");

    rerender(<TimelineCanvas {...props} playheadTick={6000} />);
    expect(sourceChip()).toHaveTextContent("内容已更新 · 实时预览");

    rerender(<TimelineCanvas {...props} playheadTick={10500} />);
    expect(sourceChip()).toHaveTextContent("未受影响 · 已完成画面");
  });
});
