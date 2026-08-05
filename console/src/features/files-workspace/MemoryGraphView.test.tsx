import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { agentsApi } from "../../api/modules/agents";
import MemoryGraphView from "./MemoryGraphView";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${JSON.stringify(values)}` : key,
  }),
}));

vi.mock("../../api/modules/agents", () => ({
  agentsApi: { getMemoryGraph: vi.fn() },
}));

const openFile = vi.fn();

describe("MemoryGraphView", () => {
  beforeEach(() => {
    openFile.mockClear();
    vi.mocked(agentsApi.getMemoryGraph).mockResolvedValue({
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
          id: "memory/a.md",
          path: "memory/a.md",
          name: "Alpha",
          description: "Root note",
          indexed: true,
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
    });
  });

  it("loads and displays directed memory graph nodes", async () => {
    const { container } = render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );

    await waitFor(() =>
      expect(agentsApi.getMemoryGraph).toHaveBeenCalledWith("agent-a"),
    );
    expect(screen.getByRole("button", { name: "wiki" })).toHaveStyle({
      transform: "translate(540px, 340px)",
    });
    expect(await screen.findAllByText("Alpha")).not.toHaveLength(0);
    expect(screen.getByRole("button", { name: "Alpha" })).not.toHaveStyle({
      transform: "translate(540px, 340px)",
    });
    expect(
      container.querySelectorAll('[data-testid="memory-graph-orbits"] circle'),
    ).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "missing" }).style.transform,
    ).not.toBe(screen.getByRole("button", { name: "Alpha" }).style.transform);
    expect(
      screen.queryByRole("button", { name: "Private" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Alpha" }));
    expect(screen.getAllByText("memory/a.md")).not.toHaveLength(0);
    expect(screen.getByText("Root note")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "files.memoryGraphOpenFile" }),
    );
    expect(openFile).toHaveBeenCalledWith("memory/a.md", "digest/wiki");

    fireEvent.click(screen.getByRole("button", { name: "missing" }));
    expect(screen.getAllByText("missing.md")).not.toHaveLength(0);
    expect(screen.getAllByText("files.memoryGraphUnresolved")).not.toHaveLength(
      0,
    );
  });

  it("keeps dense graphs readable by limiting persistent labels", async () => {
    const nodes = Array.from({ length: 27 }, (_, index) => ({
      id: `memory/node-${index}.md`,
      path: `memory/node-${index}.md`,
      name: `A very long memory node title number ${index}`,
      description: "",
      indexed: true,
    }));
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
        ...nodes,
      ],
      edges: [
        ...nodes.map((node) => ({
          source: "virtual:wiki",
          target: node.id,
          target_anchor: null,
        })),
        ...nodes.map((node, index) => ({
          source: node.id,
          target: nodes[(index + 1) % nodes.length].id,
          target_anchor: null,
        })),
      ],
    });

    const { container } = render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );

    await waitFor(() =>
      expect(
        screen.getAllByRole("button", { name: /memory node title/i }),
      ).toHaveLength(27),
    );
    expect(container.querySelectorAll("svg text").length).toBeLessThanOrEqual(
      10,
    );
  });

  it("drags downstream nodes and resets their positions on refresh", async () => {
    render(
      <MemoryGraphView agentId="agent-a" root="wiki" onOpenFile={openFile} />,
    );
    const parent = await screen.findByRole("button", { name: "Alpha" });
    const child = screen.getByRole("button", { name: "missing" });
    const initialRequestCount = vi.mocked(agentsApi.getMemoryGraph).mock.calls
      .length;
    const parentStart = parent.style.transform;
    const childStart = child.style.transform;
    Object.defineProperties(parent, {
      setPointerCapture: { value: vi.fn() },
      hasPointerCapture: { value: vi.fn(() => false) },
      releasePointerCapture: { value: vi.fn() },
    });

    fireEvent.pointerDown(parent, {
      button: 0,
      clientX: 100,
      clientY: 100,
      pointerId: 1,
    });
    fireEvent.pointerMove(parent, {
      clientX: 160,
      clientY: 130,
      pointerId: 1,
    });
    fireEvent.pointerUp(parent, { pointerId: 1 });

    expect(parent.style.transform).not.toBe(parentStart);
    expect(child.style.transform).not.toBe(childStart);

    fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
    await waitFor(() =>
      expect(agentsApi.getMemoryGraph).toHaveBeenCalledTimes(
        initialRequestCount + 1,
      ),
    );
    expect(parent.style.transform).toBe(parentStart);
    expect(child.style.transform).toBe(childStart);
  });
});
