import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import WorkGraphPanel from "@/components/agent/WorkGraphPanel";
import type { WorkGraphView } from "@/contracts/creator/workGraph";
import { useWorkGraphStore } from "@/store/workGraphStore";

const navigateToLocator = vi.fn();
vi.mock("@/routing/locators", () => ({
  navigateToLocator: (...args: unknown[]) => navigateToLocator(...args),
}));

const graph: WorkGraphView = {
  projectId: "p1",
  generation: 7,
  counts: { total: 5, done: 2, running: 1, failed: 1, gated: 1 },
  mediaCalls: 12,
  mediaCallBudget: 200,
  nodes: [
    {
      id: "visual:char:a:var:x",
      kind: "visual",
      label: "梅西 · x",
      status: "done",
      deps: [],
      lane: "visual",
      taskId: null,
      progress: null,
      error: null,
      missing: [],
      locator: { page: "assets", assetId: "char:a" },
      dispatchable: true,
    },
    {
      id: "lineup:lineup:trio",
      kind: "lineup",
      label: "三人组 阵容图",
      status: "failed",
      deps: ["visual:char:a:var:x"],
      lane: "lineup",
      taskId: null,
      progress: null,
      error: "safety rejected",
      missing: [],
      locator: { page: "assets" },
      dispatchable: true,
    },
    {
      id: "storyboard:elem:one",
      kind: "storyboard",
      label: "开场 · 分镜",
      status: "running",
      deps: [],
      lane: "element:elem:one",
      taskId: "task-1",
      progress: 0.5,
      error: null,
      missing: [],
      locator: { page: "plan", elementId: "elem:one" },
      dispatchable: true,
    },
    {
      id: "video:elem:one",
      kind: "video",
      label: "开场 · 视频",
      status: "gated",
      deps: ["storyboard:elem:one"],
      lane: "element:elem:one",
      taskId: null,
      progress: null,
      error: null,
      missing: ["storyboard:elem:one"],
      locator: { page: "plan", elementId: "elem:one" },
      dispatchable: true,
    },
    {
      id: "compose:final",
      kind: "compose",
      label: "最终合成",
      status: "gated",
      deps: ["video:elem:one"],
      lane: "compose",
      taskId: null,
      progress: null,
      error: null,
      missing: ["video:elem:one"],
      locator: { page: "plan" },
      dispatchable: false,
    },
  ],
};

describe("WorkGraphPanel", () => {
  beforeEach(() => {
    navigateToLocator.mockClear();
    useWorkGraphStore.setState({
      projectId: "p1",
      graph,
      loading: false,
      error: null,
      dispatching: {},
      refresh: vi.fn(async () => {}),
      dispatchNode: vi.fn(async () => {}),
    } as never);
  });

  it("renders lanes in production order with status markers", () => {
    render(<WorkGraphPanel projectId="p1" />);
    expect(screen.getByTestId("work-graph-panel")).toBeInTheDocument();
    expect(screen.getByText(/制作进度 2\/5/)).toBeInTheDocument();
    expect(screen.getByText(/并行 1/)).toBeInTheDocument();
    const laneHeaders = screen
      .getAllByText(/视觉资产|阵容图|开场|最终合成/)
      .map((node) => node.textContent);
    expect(laneHeaders[0]).toContain("视觉资产");
    expect(screen.getByText(/safety rejected/)).toBeInTheDocument();
    // Both gated nodes (video + compose) report their unmet dependency.
    expect(screen.getAllByText(/等待 1 项依赖/)).toHaveLength(2);
  });

  it("navigates on node click and retries failed nodes", () => {
    render(<WorkGraphPanel projectId="p1" />);
    fireEvent.click(screen.getByText(/开场 · 分镜/));
    expect(navigateToLocator).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ page: "plan", elementId: "elem:one" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(useWorkGraphStore.getState().dispatchNode).toHaveBeenCalledWith(
      "p1",
      "lineup:lineup:trio",
    );
  });
});
