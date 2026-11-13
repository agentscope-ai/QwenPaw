import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { ConfigProvider, message } from "antd";

import WorkGraphPanel, {
  WorkGraphManualHoldNotice,
} from "@/components/agent/WorkGraphPanel";
import AgentProgressOverview from "@/components/agent/AgentProgressOverview";
import type { WorkGraphView } from "@/contracts/creator/workGraph";
import { useWorkGraphStore } from "@/store/workGraphStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { installMockFetch } from "@/test/mockFetch";
import i18n from "@/i18n";

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
    expect(screen.getByText("三人组 阵容图")).toBeInTheDocument();
    expect(screen.getByText(/50%/)).toBeInTheDocument();
    expect(screen.getByText("等待前置内容")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("safety rejected");
    expect(document.body).not.toHaveTextContent("storyboard:elem:one");
    expect(document.querySelector('[title="safety rejected"]')).toBeNull();

    fireEvent.click(screen.getByText(/开场 · 分镜/));
    expect(navigateToLocator).toHaveBeenCalledWith(
      "p1",
      expect.objectContaining({ page: "plan", elementId: "elem:one" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "重新生成阵容图 · 三人组 阵容图" }),
    );
    expect(useWorkGraphStore.getState().dispatchNode).toHaveBeenCalledWith(
      "p1",
      "lineup:lineup:trio",
    );
    expect(screen.queryByRole("button", { name: "恢复自动制作" })).toBeNull();
  });
});

const heldGraph: WorkGraphView = {
  ...graph,
  manualHold: { revision: 12, nodeIds: ["video:elem:one"] },
  nodes: [{ ...graph.nodes[3], manuallyHeld: true, promptSyncRequired: true }],
};
const resumedGraph: WorkGraphView = {
  ...heldGraph,
  manualHold: { revision: 13, nodeIds: [] },
  nodes: heldGraph.nodes.map((item) => ({ ...item, manuallyHeld: false })),
};
const pauseText = "手动重生成已暂停后续自动制作。";
const resumeText = "恢复自动制作";

function graphFetch(status = 200) {
  const graphResponse = { json: heldGraph, ok: true, status: 200 };
  const resumeResponse = { json: { ok: true }, ok: status === 200, status };
  const mock = installMockFetch([
    { match: "/work-graph/resume", method: "POST", response: resumeResponse },
    { match: "/work-graph", method: "GET", response: graphResponse },
  ]);
  return { ...mock, graphResponse, resumeResponse };
}

async function renderHeldPanel() {
  const view = render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <WorkGraphManualHoldNotice projectId="p1" />
      <WorkGraphPanel projectId="p1" />
    </ConfigProvider>,
  );
  await screen.findByText(pauseText);
  return view;
}

async function openResumeConfirmation() {
  fireEvent.click(screen.getByRole("button", { name: resumeText }));
  const dialog = await screen.findByRole("dialog");
  expect(dialog).toHaveTextContent("下游自动生成");
  expect(dialog).toHaveTextContent("可能产生媒体生成费用");
  return within(dialog).getByRole("button", { name: resumeText });
}

describe("manual work-graph holds", () => {
  beforeEach(() => {
    useWorkGraphStore.setState(useWorkGraphStore.getInitialState(), true);
    useWorkGraphStore.getState().reset();
    useProjectSnapshotStore.getState().reset();
    vi.spyOn(message, "error").mockImplementation(() => undefined as never);
    vi.spyOn(message, "warning").mockImplementation(() => undefined as never);
  });

  afterEach(async () => {
    cleanup();
    useWorkGraphStore.getState().reset();
    vi.unstubAllGlobals();
    await i18n.changeLanguage("zh");
  });

  it("shows manual pause instead of waiting and survives remount/refetch", async () => {
    const { calls } = graphFetch();
    const first = await renderHeldPanel();
    expect(screen.getByText("手动暂停")).toBeInTheDocument();
    expect(screen.queryByText("等待前置内容")).toBeNull();
    first.unmount();
    await renderHeldPanel();
    await waitFor(() =>
      expect(calls.filter((call) => call.method === "GET")).toHaveLength(2),
    );
    expect(screen.getByText(pauseText)).toBeInTheDocument();
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("keeps the notice in the collapsed overview and held nodes out of preparing/running", () => {
    useWorkGraphStore.setState({
      projectId: "p1",
      graph: {
        ...heldGraph,
        nodes: [{ ...heldGraph.nodes[0], preparationState: "running" }],
      },
    });
    const { container } = render(<AgentProgressOverview projectId="p1" />);
    expect(screen.getByText("手动暂停")).toBeInTheDocument();
    expect(container.querySelector("[data-node-id]")).toHaveAttribute(
      "data-phase",
      "attention",
    );
    expect(container.querySelector("[data-agent-active-work]")).toBeNull();
    fireEvent.click(container.querySelector(".agent-progress-header")!);
    expect(screen.getByText(pauseText)).toBeVisible();
    expect(screen.getByRole("button", { name: resumeText })).toBeEnabled();
  });

  it("shows holds even without visible nodes, but not an empty hold", async () => {
    const { graphResponse } = graphFetch();
    graphResponse.json = { ...heldGraph, nodes: [] };
    await renderHeldPanel();
    graphResponse.json = {
      ...heldGraph,
      manualHold: { revision: 12, nodeIds: [] },
    };
    await act(() => useWorkGraphStore.getState().refresh("p1"));
    expect(screen.queryByText(pauseText)).toBeNull();
    expect(screen.queryByRole("button", { name: resumeText })).toBeNull();
  });

  it("does not resume without explicit confirmation", async () => {
    const { calls } = graphFetch();
    await renderHeldPanel();
    await openResumeConfirmation();
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: /取\s*消/,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(calls.every((call) => call.method === "GET")).toBe(true);
    expect(screen.getByText(pauseText)).toBeInTheDocument();
  });

  it("posts the observed revision once and only clears the notice after a successful graph refetch", async () => {
    const { fetchMock, graphResponse } = graphFetch();
    await renderHeldPanel();
    const confirm = await openResumeConfirmation();
    let finish!: (response: Response) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    );
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    await useWorkGraphStore.getState().resume("p1", 12);
    expect(useWorkGraphStore.getState().resuming).toBe(true);
    expect(
      within(screen.getByRole("status")).getByRole("button", {
        name: resumeText,
      }),
    ).toBeDisabled();
    expect(screen.getByText(pauseText)).toBeInTheDocument();
    const posts = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "POST",
    );
    expect(posts).toHaveLength(1);
    expect(posts[0][0]).toBe(
      "/api/qwenpaw-creator/projects/p1/work-graph/resume",
    );
    expect(JSON.parse(posts[0][1]!.body as string)).toEqual({ revision: 12 });
    graphResponse.json = resumedGraph;
    await act(async () =>
      finish(new Response(JSON.stringify({ ok: true }), { status: 200 })),
    );
    await waitFor(() => expect(screen.queryByText(pauseText)).toBeNull());
    expect(
      fetchMock.mock.calls.filter(([, init]) => !init?.method),
    ).toHaveLength(2);
    expect(useWorkGraphStore.getState().resuming).toBe(false);
    expect(useWorkGraphStore.getState().graph?.manualHold?.nodeIds).toEqual([]);
  });

  it("preserves the pause on failed resume and allows an explicit retry", async () => {
    const { calls } = graphFetch(500);
    await renderHeldPanel();
    fireEvent.click(await openResumeConfirmation());
    await waitFor(() =>
      expect(message.error).toHaveBeenCalledWith("恢复自动制作失败，请重试。"),
    );
    expect(screen.getByText(pauseText)).toBeInTheDocument();
    expect(screen.getByText("手动暂停")).toBeInTheDocument();
    expect(useWorkGraphStore.getState().graph?.manualHold).toEqual(
      heldGraph.manualHold,
    );
    expect(screen.getByRole("button", { name: resumeText })).toBeEnabled();
    expect(calls.map((call) => call.method)).toEqual(["GET", "POST"]);
  });

  it("refetches on 409 without retrying or clearing a newer hold, even if it arrived during confirmation", async () => {
    const { calls, graphResponse } = graphFetch(409);
    await renderHeldPanel();
    const confirm = await openResumeConfirmation();
    const newerGraph = {
      ...heldGraph,
      manualHold: { revision: 14, nodeIds: ["video:elem:one", "compose:main"] },
    };
    graphResponse.json = newerGraph;
    act(() => useWorkGraphStore.setState({ graph: newerGraph }));
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(message.warning).toHaveBeenCalledWith(
        "暂停状态已更新，请查看最新状态后重新确认恢复。",
      ),
    );
    expect(calls.map((call) => call.method)).toEqual(["GET", "POST", "GET"]);
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({
      revision: 12,
    });
    expect(useWorkGraphStore.getState().graph?.manualHold).toEqual(
      newerGraph.manualHold,
    );
    expect(screen.getByText(pauseText)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: resumeText })).toBeEnabled();
    // Another attempt requires a new confirmation of the new revision.
    fireEvent.click(await openResumeConfirmation());
    await waitFor(() =>
      expect(calls.filter((call) => call.method === "POST")).toHaveLength(2),
    );
    expect(calls.filter((call) => call.method === "POST")[1].body).toEqual({
      revision: 14,
    });
    await waitFor(() =>
      expect(useWorkGraphStore.getState().resuming).toBe(false),
    );
  });

  it.each([200, 409])(
    "retains the last known pause when the refetch after resume status %s fails",
    async (status) => {
      const { graphResponse } = graphFetch(status);
      await renderHeldPanel();
      graphResponse.ok = false;
      graphResponse.status = 503;
      fireEvent.click(await openResumeConfirmation());
      await waitFor(() =>
        expect(useWorkGraphStore.getState().error).not.toBeNull(),
      );
      expect(screen.getByText(pauseText)).toBeInTheDocument();
      expect(useWorkGraphStore.getState().graph?.manualHold).toEqual(
        heldGraph.manualHold,
      );
      await waitFor(() =>
        expect(screen.getByRole("button", { name: resumeText })).toBeEnabled(),
      );
    },
  );

  it("localizes the pause and cost-aware resume action in English", async () => {
    graphFetch();
    await i18n.changeLanguage("en");
    render(
      <>
        <WorkGraphManualHoldNotice projectId="p1" />
        <WorkGraphPanel projectId="p1" />
      </>,
    );
    expect(await screen.findByText("Manually paused")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Resume automatic production" }),
    );
    expect(await screen.findByRole("dialog")).toHaveTextContent(
      "may incur media generation costs",
    );
  });
});
