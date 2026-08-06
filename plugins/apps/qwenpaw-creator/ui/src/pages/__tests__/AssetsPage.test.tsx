import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import AssetsPage from "@/pages/AssetsPage";
import { NavigationRuntime } from "@/routing/navigation";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { projectDocument } from "@/test/creatorFixtures";
import { installMockFetch } from "@/test/mockFetch";
import type { ProjectDocument } from "@/contracts/creator";

function cloneProject(): ProjectDocument {
  return structuredClone(projectDocument);
}

function seedProject(project = cloneProject()) {
  useProjectSnapshotStore.getState().reset("p1");
  useProjectSnapshotStore.setState({
    projectId: "p1",
    project,
    generation: project.generation,
    etag: '"sha256:g3"',
    syncStatus: "healthy",
    syncError: null,
  });
}

function renderPage(entry = "/project/p1/assets") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <NavigationRuntime />
      <Routes>
        <Route path="/project/:id/assets" element={<AssetsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function ingestRoutes(
  extra: Array<{
    match: string;
    method?: string;
    response: { json?: unknown; status?: number };
  }> = [],
) {
  return [
    ...extra,
    {
      match: "/projects/p1/project",
      method: "GET",
      response: {
        json: {
          projectId: "p1",
          generation: 3,
          etag: '"sha256:g3"',
          syncStatus: "healthy",
          project: cloneProject(),
        },
      },
    },
    {
      match: "/projects/p1/specialist-runs",
      response: { json: { items: [] } },
    },
    { match: "/projects/p1/tasks", response: { json: { items: [] } } },
  ];
}

describe("AssetsPage schema-v2 Project projection", () => {
  beforeEach(() => {
    useProjectSnapshotStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    seedProject();
  });

  it("renders source versions, artifact versions and visual entities from one Project snapshot", () => {
    const { container } = renderPage();

    expect(screen.getByText("素材与产物")).toBeInTheDocument();
    expect(screen.getByText("圆润大橘猫")).toBeInTheDocument();
    expect(screen.getByText("橘猫原始视频")).toBeInTheDocument();
    expect(screen.getByText("测试项目最终成片")).toBeInTheDocument();
    expect(screen.getByText("4 项")).toBeInTheDocument();
    // Only one card per underlying content: no two cards render the same media URL.
    const previewSrcs = Array.from(
      container.querySelectorAll('[data-creator-module="asset-card"] [src]'),
    ).map((element) => element.getAttribute("src"));
    expect(new Set(previewSrcs).size).toBe(previewSrcs.length);
    expect(
      container.querySelector('[data-creator-module="asset-card"]'),
    ).toBeInTheDocument();

    const sourceVideo = screen.getByLabelText("橘猫原始视频 视频");
    expect(sourceVideo).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/assets/cat-video-v1",
    );
    const finalVideo = screen.getByLabelText("测试项目最终成片 视频");
    expect(finalVideo).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/final-v1",
    );
    const visualImage = screen.getByRole("img", { name: "圆润大橘猫" });
    expect(visualImage).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/cat-anchor-v1",
    );
  });

  it("filters locally without requiring a separate backend asset projection", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "来源素材" }));
    expect(screen.getByText("1 项")).toBeInTheDocument();
    expect(screen.getByText("橘猫原始视频")).toBeInTheDocument();
    expect(screen.queryByText("测试项目最终成片")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "视频" }));
    expect(screen.getByText("3 项")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("搜索名称或 ID"), {
      target: { value: "最终" },
    });
    expect(screen.getByText("1 项")).toBeInTheDocument();
    expect(screen.getByText("测试项目最终成片")).toBeInTheDocument();
  });

  it("selects an immutable version and shows its canonical ref", () => {
    renderPage();
    fireEvent.click(screen.getByText("测试项目最终成片"));

    expect(screen.getByText("artifact-version:final-v1")).toBeInTheDocument();
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "artifact-version:final-v1",
    );
    // The hand-off button was removed; the detail keeps read-only actions only.
    expect(
      screen.queryByRole("button", { name: "交给 Agent" }),
    ).not.toBeInTheDocument();
  });

  it("uploads a file through the retained ingest endpoint and refreshes Project plus durable Tasks", async () => {
    const { calls } = installMockFetch(
      ingestRoutes([
        {
          match: "/projects/p1/assets",
          method: "POST",
          response: {
            json: {
              assetId: "asset:new",
              taskId: "task:new",
              status: "QUEUED",
            },
          },
        },
      ]),
    );
    const { container } = renderPage();
    const file = new File(["video"], "new-cat.mp4", { type: "video/mp4" });
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(calls.some((call) => call.method === "POST")).toBe(true),
    );
    const request = calls.find((call) => call.method === "POST")!;
    expect(request.url).toContain("/projects/p1/assets");
    expect(request.body).toMatchObject({
      postIngestAction: "ATTACH_SOURCE",
      file,
    });
    await waitFor(() =>
      expect(
        calls.some((call) => call.url.endsWith("/projects/p1/project")),
      ).toBe(true),
    );
    expect(calls.some((call) => call.url.endsWith("/projects/p1/tasks"))).toBe(
      true,
    );
  });

  it("retains URL/text ingest and submits the canonical ATTACH_SOURCE request", async () => {
    const { calls } = installMockFetch(
      ingestRoutes([
        {
          match: "/projects/p1/assets",
          method: "POST",
          response: {
            json: {
              assetId: "asset:url",
              taskId: "task:url",
              status: "QUEUED",
            },
          },
        },
      ]),
    );
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "添加链接或文本" }));
    fireEvent.change(screen.getByPlaceholderText("素材名称"), {
      target: { value: "参考链接" },
    });
    fireEvent.change(screen.getByPlaceholderText("https://…"), {
      target: { value: "https://example.com/cat.mp4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交入库" }));

    await waitFor(() =>
      expect(calls.some((call) => call.method === "POST")).toBe(true),
    );
    expect(calls.find((call) => call.method === "POST")?.body).toMatchObject({
      kind: "url",
      name: "参考链接",
      value: "https://example.com/cat.mp4",
      postIngestAction: "ATTACH_SOURCE",
    });
  });
});
