import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import WorkGraphPanel from "@/components/agent/WorkGraphPanel";
import type { WorkGraphView } from "@/contracts/creator/workGraph";
import { useWorkGraphStore } from "@/store/workGraphStore";

const navigateToLocator = vi.fn();
vi.mock("@/routing/locators", () => ({
  navigateToLocator: (...args: unknown[]) => navigateToLocator(...args),
}));

type GraphNode = WorkGraphView["nodes"][number];

const node = (overrides: Partial<GraphNode> & { id: string }) =>
  ({
    kind: overrides.id.split(":")[0],
    deps: [],
    taskId: null,
    progress: null,
    error: null,
    missing: [],
    dispatchable: true,
    ...overrides,
  }) as GraphNode;

const graph: WorkGraphView = {
  projectId: "p1",
  generation: 7,
  counts: { total: 4, done: 1, running: 1, failed: 1, gated: 1 },
  mediaCalls: 12,
  mediaCallBudget: 200,
  nodes: [
    node({
      id: "visual:char:a:var:x",
      label: "梅西 · x",
      status: "done",
      lane: "visual",
      locator: { page: "assets", assetId: "char:a" },
    }),
    node({
      id: "lineup:lineup:trio",
      label: "三人组 阵容图",
      status: "failed",
      deps: ["visual:char:a:var:x"],
      lane: "lineup",
      error: "safety rejected",
      locator: { page: "assets" },
    }),
    node({
      id: "storyboard:elem:one",
      label: "开场 · 分镜",
      status: "running",
      lane: "element:elem:one",
      taskId: "task-1",
      progress: 0.5,
      locator: { page: "plan", elementId: "elem:one" },
    }),
    node({
      id: "video:elem:one",
      label: "开场 · 视频",
      status: "gated",
      deps: ["storyboard:elem:one"],
      lane: "element:elem:one",
      missing: ["storyboard:elem:one"],
      locator: { page: "plan", elementId: "elem:one" },
    }),
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

  it("renders lanes in order, navigates on click and retries failures", () => {
    render(<WorkGraphPanel projectId="p1" />);
    expect(screen.getByTestId("work-graph-panel")).toBeInTheDocument();
    expect(screen.getByText(/制作进度 1\/4/)).toBeInTheDocument();
    expect(screen.getByText(/并行 1/)).toBeInTheDocument();
    expect(
      screen.getAllByText(/视觉资产|阵容图|开场/)[0].textContent,
    ).toContain("视觉资产");
    expect(screen.getByText(/safety rejected/)).toBeInTheDocument();
    // The gated video node reports its unmet storyboard dependency.
    expect(screen.getByText(/等待 1 项依赖/)).toBeInTheDocument();

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
