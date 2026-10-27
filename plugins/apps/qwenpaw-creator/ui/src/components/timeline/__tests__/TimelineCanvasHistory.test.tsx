import { fireEvent, render, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import TimelineCanvas from "@/components/timeline/TimelineCanvas";
import { projectDocument } from "@/test/creatorFixtures";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import type { ProjectDocument } from "@/contracts/creator";

function setup() {
  const project = structuredClone(projectDocument) as ProjectDocument;
  const timeline = project.timelines.items["timeline:main"];
  const patchMock = vi.fn(
    async (
      _projectId: string,
      operations: { path: string; value: unknown }[],
    ) => {
      const state = useProjectSnapshotStore.getState();
      const next = structuredClone(state.project) as ProjectDocument;
      for (const operation of operations) {
        const segments = operation.path.split("/").filter(Boolean);
        let cursor: Record<string, unknown> = next as never;
        for (const key of segments.slice(0, -1)) {
          cursor = cursor[key] as Record<string, unknown>;
        }
        cursor[segments[segments.length - 1]] = operation.value;
      }
      useProjectSnapshotStore.setState({ project: next });
      return {
        projectId: "p1",
        generation: 2,
        etag: '"sha256:x"',
        changedPointers: [],
        project: next,
        editImpact: {
          affectedElementIds: [],
          renderTimelineIds: [],
          regenerationRequired: false,
        },
      } as never;
    },
  );
  useProjectSnapshotStore.getState().reset("p1");
  useProjectSnapshotStore.setState({
    projectId: "p1",
    project,
    generation: 1,
    etag: '"sha256:g1"',
    patch: patchMock as never,
  });
  const props = {
    project,
    timeline,
    durationTick: 20000,
    playheadTick: 0,
    selectedElementId: "edit-opening",
    previewOpen: false,
    tasks: [],
    onPreviewOpenChange: vi.fn(),
    onPlayheadChange: vi.fn(),
    onSelectElement: vi.fn(),
    onActiveElementIdsChange: vi.fn(),
  };
  const utils = render(<TimelineCanvas {...props} />);
  const chart = utils.container.querySelector(
    "[data-timeline-chart]",
  ) as HTMLDivElement;
  vi.spyOn(chart, "getBoundingClientRect").mockReturnValue({
    left: 0,
    top: 100,
    right: 692,
    bottom: 300,
    width: 692,
    height: 200,
  } as DOMRect);
  const refresh = () => {
    const p = useProjectSnapshotStore.getState().project as ProjectDocument;
    const tl = p.timelines.items["timeline:main"];
    utils.rerender(<TimelineCanvas {...props} project={p} timeline={tl} />);
  };
  return { ...utils, patchMock, refresh };
}

const editOpeningSpan = () =>
  (useProjectSnapshotStore.getState().project as ProjectDocument).timelines
    .items["timeline:main"].elements_by_id["edit-opening"].span;

const span = (start_tick: number, duration_tick: number) => ({
  start_tick,
  duration_tick,
});

const undo = (shiftKey = false) =>
  fireEvent.keyDown(document.body, { key: "z", ctrlKey: true, shiftKey });

/** Start-trim drag on edit-opening: +31.2px = +1000 ticks (624px/20000). */
function trim(container: HTMLElement, pointerId: number, fromX = 100) {
  const handle = container.querySelector(
    '[data-element-block="edit-opening"] [data-element-trim="start"]',
  ) as HTMLElement;
  const block = container.querySelector(
    '[data-element-block="edit-opening"]',
  ) as HTMLElement;
  fireEvent.pointerDown(handle, { button: 0, pointerId, clientX: fromX });
  fireEvent.pointerMove(block, { pointerId, clientX: fromX + 31.2 });
  fireEvent.pointerUp(block, { button: 0, pointerId, clientX: fromX + 31.2 });
}

describe("TimelineCanvas span edit history", () => {
  it("undoes and redoes a committed trim with Ctrl+Z / Ctrl+Shift+Z", async () => {
    const { container, patchMock } = setup();
    // Nothing to undo yet: Ctrl+Z must not fire a patch.
    undo();
    expect(patchMock).not.toHaveBeenCalled();

    trim(container, 5);
    await waitFor(() => expect(editOpeningSpan()).toEqual(span(1000, 7000)));

    undo();
    await waitFor(() => expect(editOpeningSpan()).toEqual(span(0, 8000)));

    undo(true);
    await waitFor(() => expect(editOpeningSpan()).toEqual(span(1000, 7000)));
    expect(patchMock).toHaveBeenCalledTimes(3);
  });

  it("keeps the history entry when the undo patch fails", async () => {
    const { container, patchMock } = setup();
    trim(container, 6);
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1));

    // First undo attempt hits a transient failure (409/network/503).
    patchMock.mockImplementationOnce(async () => {
      throw new Error("瞬时失败");
    });
    undo();
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(2));
    expect(editOpeningSpan()).toEqual(span(1000, 7000));

    undo();
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(editOpeningSpan()).toEqual(span(0, 8000)));
  });

  it("undoes only the newest edit when pressed while a commit is pending", async () => {
    const { container, patchMock, refresh } = setup();
    trim(container, 8);
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1));
    refresh();

    // Second trim B -> C(2000/6000): its PATCH hangs until released.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const original = patchMock.getMockImplementation()!;
    patchMock.mockImplementationOnce(async (...args) => {
      await gate;
      return original(...(args as Parameters<typeof original>)) as never;
    });
    trim(container, 9, 200);
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(2));

    // Undo pressed while the second commit is in flight must wait for the
    // queue and then revert C -> B, never jumping back to A.
    undo();
    release();
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(3));
    await waitFor(() => expect(editOpeningSpan()).toEqual(span(1000, 7000)));
  });

  it("refuses to undo over a change written by someone else", async () => {
    const { container, patchMock } = setup();
    trim(container, 7);
    await waitFor(() => expect(patchMock).toHaveBeenCalledTimes(1));

    // An Agent (or another page) rewrites the same span in between.
    const next = structuredClone(
      useProjectSnapshotStore.getState().project,
    ) as ProjectDocument;
    next.timelines.items["timeline:main"].elements_by_id["edit-opening"].span =
      span(2000, 6000);
    useProjectSnapshotStore.setState({ project: next });

    undo();
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(patchMock).toHaveBeenCalledTimes(1);
    expect(editOpeningSpan()).toEqual(span(2000, 6000));
  });
});
