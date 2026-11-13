import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { agentsApi } from "../../api/modules/agents";
import MemoryGraphView from "./MemoryGraphView";

type GraphMethodMock = ReturnType<typeof vi.fn>;

interface MockGraphInstance {
  cameraPosition: GraphMethodMock;
  controlsState: {
    autoRotate: boolean;
    maxDistance: number;
    minDistance: number;
    target: { x: number; y: number; z: number };
    graphFitDistance?: number;
  };
  graphData: GraphMethodMock;
  linkColor: GraphMethodMock;
  linkDirectionalParticles: GraphMethodMock;
  nodeColor: GraphMethodMock;
  nodeLabel: GraphMethodMock;
  nodeThreeObject: GraphMethodMock;
  triggerEngineStop: () => void;
  triggerNodeHover: (node: { id: string } | null) => void;
  zoomToFit: GraphMethodMock;
}

const graphMock = vi.hoisted(() => ({
  instances: [] as unknown[],
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${JSON.stringify(values)}` : key,
  }),
}));

vi.mock("../../api/modules/agents", () => ({
  agentsApi: { getMemoryGraph: vi.fn() },
}));

vi.mock("3d-force-graph", () => ({
  default: function MockForceGraph3D(element: HTMLElement) {
    const canvas = document.createElement("canvas");
    element.append(canvas);
    const controlsState = {
      autoRotate: false,
      autoRotateSpeed: 0,
      dampingFactor: 0,
      enableDamping: false,
      maxDistance: 0,
      minDistance: 0,
      target: { x: 0, y: 0, z: 0 },
    };
    const renderer = {
      domElement: canvas,
      outputColorSpace: "",
      setPixelRatio: vi.fn(),
      toneMapping: 0,
      toneMappingExposure: 1,
    };
    const cameraState = {
      far: 2000,
      fov: 50,
      near: 0.1,
      updateProjectionMatrix: vi.fn(),
    };
    const sceneState = { fog: null };
    let camera = { x: 0, y: 0, z: 360 };
    let engineStop: () => void = () => undefined;
    let nodeHover: (node: { id: string } | null) => void = () => undefined;
    const api: Record<string, unknown> = { controlsState };
    const chainMethods = [
      "_destructor",
      "backgroundColor",
      "cooldownTicks",
      "d3AlphaDecay",
      "d3VelocityDecay",
      "enableNavigationControls",
      "enableNodeDrag",
      "graphData",
      "height",
      "linkColor",
      "linkCurvature",
      "linkDirectionalArrowColor",
      "linkDirectionalArrowLength",
      "linkDirectionalArrowRelPos",
      "linkDirectionalArrowResolution",
      "linkDirectionalParticleColor",
      "linkDirectionalParticleResolution",
      "linkDirectionalParticles",
      "linkDirectionalParticleSpeed",
      "linkDirectionalParticleWidth",
      "linkOpacity",
      "linkResolution",
      "linkWidth",
      "nodeColor",
      "nodeId",
      "nodeLabel",
      "nodeOpacity",
      "nodeRelSize",
      "nodeResolution",
      "nodeThreeObject",
      "nodeThreeObjectExtend",
      "nodeVal",
      "numDimensions",
      "onBackgroundClick",
      "onNodeClick",
      "onNodeHover",
      "showNavInfo",
      "warmupTicks",
      "width",
      "zoomToFit",
      "lights",
    ];
    chainMethods.forEach((method) => {
      api[method] = vi.fn(() => api);
    });
    api.controls = vi.fn(() => controlsState);
    api.camera = vi.fn(() => cameraState);
    api.d3Force = vi.fn(() => ({
      distance: vi.fn(),
      strength: vi.fn(),
    }));
    api.renderer = vi.fn(() => renderer);
    api.scene = vi.fn(() => sceneState);
    api.cameraPosition = vi.fn(
      (
        position?: { x: number; y: number; z: number },
        target?: { x: number; y: number; z: number },
      ) => {
        if (!position) return camera;
        camera = position;
        if (target) controlsState.target = target;
        return api;
      },
    );
    api.onEngineStop = vi.fn((callback: () => void) => {
      engineStop = callback;
      return api;
    });
    api.triggerEngineStop = () => engineStop();
    api.onNodeHover = vi.fn(
      (callback: (node: { id: string } | null) => void) => {
        nodeHover = callback;
        return api;
      },
    );
    api.triggerNodeHover = (node: { id: string } | null) => nodeHover(node);
    graphMock.instances.push(api);
    return api;
  },
}));

const openFile = vi.fn();

const defaultSnapshot = {
  version: 1 as const,
  nodes: [
    {
      id: "virtual:wiki",
      path: "digest/wiki",
      name: "wiki",
      description: "",
      indexed: false,
      virtual: true,
    },
    {
      id: "memory/a.md",
      path: "memory/a.md",
      name: "Alpha",
      description: "Root note",
      indexed: true,
      section: "daily" as const,
      relative_path: "a.md",
    },
    {
      id: "missing.md",
      path: "missing.md",
      name: "",
      description: "",
      indexed: false,
    },
    {
      id: "virtual:personal",
      path: "digest/personal",
      name: "personal",
      description: "",
      indexed: false,
      virtual: true,
    },
    {
      id: "digest/personal/private.md",
      path: "digest/personal/private.md",
      name: "Private",
      description: "",
      indexed: true,
    },
  ],
  edges: [
    {
      source: "virtual:wiki",
      target: "memory/a.md",
      target_anchor: null,
    },
    {
      source: "memory/a.md",
      target: "missing.md",
      target_anchor: "details",
    },
    {
      source: "virtual:personal",
      target: "digest/personal/private.md",
      target_anchor: null,
    },
  ],
};

describe("MemoryGraphView", () => {
  beforeEach(() => {
    graphMock.instances.length = 0;
    openFile.mockClear();
    vi.mocked(agentsApi.getMemoryGraph).mockReset();
    vi.mocked(agentsApi.getMemoryGraph).mockResolvedValue(defaultSnapshot);
  });

  it("loads the selected root into an accessible 3D graph", async () => {
    const { container } = render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );

    await waitFor(() =>
      expect(agentsApi.getMemoryGraph).toHaveBeenCalledWith("agent-a"),
    );
    await waitFor(() => expect(graphMock.instances).toHaveLength(1));
    const graph = graphMock.instances[0] as MockGraphInstance;
    const graphDataCall =
      graph.graphData.mock.calls[graph.graphData.mock.calls.length - 1];
    const graphData = graphDataCall?.[0] as {
      nodes: Array<{
        id: string;
        isRoot: boolean;
        isRootDirect: boolean;
      }>;
      links: unknown[];
    };

    expect(graphData.nodes.map((node) => node.id)).toEqual([
      "virtual:wiki",
      "memory/a.md",
      "missing.md",
    ]);
    expect(
      graphData.nodes.find((node) => node.id === "virtual:wiki"),
    ).toMatchObject({
      isRoot: true,
      isRootDirect: false,
    });
    expect(
      graphData.nodes.find((node) => node.id === "memory/a.md"),
    ).toMatchObject({
      isRoot: false,
      isRootDirect: true,
    });
    expect(
      graphData.nodes.find((node) => node.id === "missing.md"),
    ).toMatchObject({
      isRoot: false,
      isRootDirect: false,
    });
    expect(graphData.links).toHaveLength(2);
    expect(graph.nodeThreeObject).toHaveBeenCalledWith(expect.any(Function));
    const nodeLabelAccessor = graph.nodeLabel.mock.calls[
      graph.nodeLabel.mock.calls.length - 1
    ]?.[0] as ((node: { id: string }) => string) | undefined;
    expect(nodeLabelAccessor).toEqual(expect.any(Function));
    expect(nodeLabelAccessor?.({ id: "memory/a.md" })).toBe("");
    await waitFor(() =>
      expect(graph.linkDirectionalParticles).toHaveBeenCalled(),
    );
    expect(screen.getByRole("button", { name: "wiki" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Alpha" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "missing" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Private" })).toBeNull();
    expect(container.querySelector("canvas")).toHaveAttribute(
      "aria-label",
      "files.memoryGraphCanvasLabel",
    );
  });

  it("focuses nodes, shows details, and opens an indexed file", async () => {
    render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    await waitFor(() => expect(graphMock.instances).toHaveLength(1));

    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
    expect(screen.getAllByText("memory/a.md")).not.toHaveLength(0);
    expect(screen.getByText("Root note")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "files.memoryGraphOpenFile" }),
    );
    expect(openFile).toHaveBeenCalledWith("daily", "a.md");

    fireEvent.click(screen.getByRole("button", { name: "missing" }));
    expect(screen.getAllByText("missing.md")).not.toHaveLength(0);
    expect(screen.getAllByText("files.memoryGraphUnresolved")).not.toHaveLength(
      0,
    );
    const graph = graphMock.instances[0] as MockGraphInstance;
    expect(graph.cameraPosition).toHaveBeenCalled();
    expect(graph.linkDirectionalParticles).toHaveBeenCalled();
  });

  it("opens conventional digest paths from legacy graph snapshots", async () => {
    vi.mocked(agentsApi.getMemoryGraph).mockResolvedValueOnce({
      version: 1,
      nodes: [
        {
          id: "virtual:wiki",
          path: "digest/wiki",
          name: "wiki",
          description: "",
          indexed: false,
          virtual: true,
        },
        {
          id: "digest/wiki/legacy.md",
          path: "digest/wiki/legacy.md",
          name: "Legacy",
          description: "",
          indexed: true,
        },
      ],
      edges: [
        {
          source: "virtual:wiki",
          target: "digest/wiki/legacy.md",
          target_anchor: null,
        },
      ],
    });

    render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Legacy" }));
    fireEvent.click(
      screen.getByRole("button", { name: "files.memoryGraphOpenFile" }),
    );

    expect(openFile).toHaveBeenCalledWith("digest", "wiki/legacy.md");
  });

  it("toggles 3D auto rotation without rebuilding the graph", async () => {
    render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    await waitFor(() => expect(graphMock.instances).toHaveLength(1));
    const graph = graphMock.instances[0] as MockGraphInstance;
    expect(graph.controlsState.autoRotate).toBe(true);

    fireEvent.click(
      screen.getByRole("button", { name: "files.memoryGraphAutoRotate" }),
    );

    await waitFor(() => expect(graph.controlsState.autoRotate).toBe(false));
    expect(graphMock.instances).toHaveLength(1);
  });

  it("does not redraw graph visuals while hovering nodes", async () => {
    render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    await waitFor(() => expect(graphMock.instances).toHaveLength(1));
    const graph = graphMock.instances[0] as MockGraphInstance;
    const cameraCalls = graph.cameraPosition.mock.calls.length;
    const linkColorCalls = graph.linkColor.mock.calls.length;
    const particleCalls = graph.linkDirectionalParticles.mock.calls.length;

    act(() => graph.triggerNodeHover({ id: "memory/a.md" }));

    expect(graphMock.instances).toHaveLength(1);
    expect(graph.cameraPosition.mock.calls.length).toBe(cameraCalls);
    expect(graph.linkColor.mock.calls.length).toBe(linkColorCalls);
    expect(graph.linkDirectionalParticles.mock.calls.length).toBe(
      particleCalls,
    );
  });

  it("limits toolbar zoom based on the fitted graph size", async () => {
    render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    await waitFor(() => expect(graphMock.instances).toHaveLength(1));
    const graph = graphMock.instances[0] as MockGraphInstance;
    const graphData = graph.graphData.mock.calls[0][0] as {
      nodes: Array<{ x?: number; y?: number; z?: number }>;
    };
    graphData.nodes.forEach((node, index) => {
      node.x = (index - 1) * 200;
      node.y = 0;
      node.z = 0;
    });

    act(() => graph.triggerEngineStop());

    expect(graph.controlsState.minDistance).toBeGreaterThan(78);
    expect(graph.controlsState.maxDistance).toBeGreaterThan(420);
    const fittedMinDistance = graph.controlsState.minDistance;

    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
    expect(graph.controlsState.minDistance).toBe(118);
    fireEvent.click(
      screen.getByRole("button", { name: "files.memoryGraphCloseDetails" }),
    );
    await waitFor(() =>
      expect(graph.controlsState.minDistance).toBe(fittedMinDistance),
    );

    const zoomOut = screen.getByRole("button", {
      name: "files.memoryGraphZoomOut",
    });
    const zoomIn = screen.getByRole("button", {
      name: "files.memoryGraphZoomIn",
    });
    for (let index = 0; index < 20; index += 1) fireEvent.click(zoomOut);
    const readCamera = graph.cameraPosition as unknown as () => {
      x: number;
      y: number;
      z: number;
    };
    const farCamera = readCamera();
    expect(Math.hypot(farCamera.x, farCamera.y, farCamera.z)).toBeCloseTo(
      graph.controlsState.maxDistance,
    );

    for (let index = 0; index < 40; index += 1) fireEvent.click(zoomIn);
    const nearCamera = readCamera();
    expect(Math.hypot(nearCamera.x, nearCamera.y, nearCamera.z)).toBeCloseTo(
      graph.controlsState.minDistance,
    );
  });

  it("refits the camera when the browser viewport changes", async () => {
    render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    await waitFor(() => expect(graphMock.instances).toHaveLength(1));
    const graph = graphMock.instances[0] as MockGraphInstance;
    await waitFor(() => expect(graph.zoomToFit).toHaveBeenCalled());
    const fitCount = graph.zoomToFit.mock.calls.length;

    fireEvent(window, new Event("resize"));

    await waitFor(() =>
      expect(graph.zoomToFit.mock.calls.length).toBeGreaterThan(fitCount),
    );
    expect(graphMock.instances).toHaveLength(1);
  });

  it("refreshes graph data and resets the selected node", async () => {
    render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "Alpha" }));
    expect(screen.getByText("Root note")).toBeInTheDocument();
    const initialRequestCount = vi.mocked(agentsApi.getMemoryGraph).mock.calls
      .length;

    fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));

    await waitFor(() =>
      expect(agentsApi.getMemoryGraph).toHaveBeenCalledTimes(
        initialRequestCount + 1,
      ),
    );
    expect(screen.queryByText("Root note")).toBeNull();
  });

  it("discards an older agent request that resolves after the current one", async () => {
    const resolvers = new Map<
      string,
      (snapshot: Awaited<ReturnType<typeof agentsApi.getMemoryGraph>>) => void
    >();
    vi.mocked(agentsApi.getMemoryGraph).mockImplementation(
      (requestedAgentId) =>
        new Promise((resolve) => {
          resolvers.set(requestedAgentId, resolve);
        }),
    );
    const snapshotFor = (requestedAgentId: string) => ({
      version: 1 as const,
      nodes: [
        {
          id: "virtual:wiki",
          path: "digest/wiki",
          name: "wiki",
          description: "",
          indexed: false,
          virtual: true,
        },
        {
          id: `${requestedAgentId}.md`,
          path: `memory/${requestedAgentId}.md`,
          name: requestedAgentId,
          description: "",
          indexed: true,
          section: "daily" as const,
          relative_path: `${requestedAgentId}.md`,
        },
      ],
      edges: [
        {
          source: "virtual:wiki",
          target: `${requestedAgentId}.md`,
          target_anchor: null,
        },
      ],
    });

    const { rerender } = render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    await waitFor(() => expect(resolvers.has("agent-a")).toBe(true));
    rerender(
      <MemoryGraphView agentId="agent-b" root="wiki" onOpenFile={openFile} />,
    );
    await waitFor(() => expect(resolvers.has("agent-b")).toBe(true));

    await act(async () => resolvers.get("agent-b")?.(snapshotFor("agent-b")));
    expect(
      await screen.findByRole("button", { name: "agent-b" }),
    ).toBeVisible();
    await act(async () => resolvers.get("agent-a")?.(snapshotFor("agent-a")));
    expect(screen.queryByRole("button", { name: "agent-a" })).toBeNull();
    expect(screen.getByRole("button", { name: "agent-b" })).toBeVisible();
  });

  it("clears the previous graph and reports an agent load failure", async () => {
    const { rerender } = render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    expect(await screen.findByRole("button", { name: "Alpha" })).toBeVisible();
    vi.mocked(agentsApi.getMemoryGraph).mockRejectedValueOnce(
      new Error("boom"),
    );

    rerender(
      <MemoryGraphView agentId="agent-b" root="wiki" onOpenFile={openFile} />,
    );
    expect(screen.queryByRole("button", { name: "Alpha" })).toBeNull();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "files.memoryGraphLoadFailed",
    );
  });
});
