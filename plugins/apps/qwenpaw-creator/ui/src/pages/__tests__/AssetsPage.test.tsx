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

function uploadFile(container: HTMLElement, name: string, type: string) {
  const file = new File(["x"], name, { type });
  fireEvent.change(container.querySelector('input[type="file"]')!, {
    target: { files: [file] },
  });
  return file;
}

function ingestRoutes(post?: {
  json?: unknown;
  status?: number;
  ok?: boolean;
}) {
  const routes: Parameters<typeof installMockFetch>[0] = [
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
  if (post) {
    routes.unshift({
      match: "/projects/p1/assets",
      method: "POST",
      response: post,
    });
  }
  return routes;
}

function intelVersion(
  id: string,
  sourceVersionId: string,
  over: Record<string, unknown> = {},
) {
  return {
    intelligence_version_id: id,
    source_asset_version_id: sourceVersionId,
    file_id: `file:${id}`,
    source_checksum: "sha-source",
    model_run_ids: [],
    coverage: {},
    created_at: "2026-07-20T00:03:00Z",
    ...over,
  };
}

/** Project whose cat video has a built v1 intelligence; optionally select an unbuilt v2. */
function seedMemorySnapshot(selectV2: boolean) {
  const project = cloneProject();
  project.assets.intelligence_versions_by_id["intel-v1"] = intelVersion(
    "intel-v1",
    "cat-video-v1",
    { file_id: "file:source-video" },
  );
  const source = project.sources.sources.items["source:cat-video"];
  source.current_intelligence_version_id = "intel-v1";
  if (selectV2) {
    project.assets.source_versions_by_id["cat-video-v2"] = {
      ...project.assets.source_versions_by_id["cat-video-v1"],
      version_id: "cat-video-v2",
      checksum: "sha-source-v2",
    };
    source.selected_asset_version_id = "cat-video-v2";
  }
  seedProject(project);
  useCreatorTaskViewStore.setState({
    projectId: "p1",
    tasks: [
      {
        id: "task:memory",
        kind: "source_memory_build",
        status: "SUCCEEDED",
        targetRef: "asset:asset:cat-video",
      } as never,
    ],
  });
}

describe("AssetsPage Project projection", () => {
  beforeEach(() => {
    useProjectSnapshotStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    seedProject();
  });

  it("renders source versions, artifact versions and visual entities from one Project snapshot", () => {
    const { container } = renderPage();

    expect(screen.getByText("4 项")).toBeInTheDocument();
    // One card per underlying content: no duplicate media URLs.
    const previewSrcs = Array.from(
      container.querySelectorAll('[data-creator-module="asset-card"] [src]'),
    ).map((element) => element.getAttribute("src"));
    expect(new Set(previewSrcs).size).toBe(previewSrcs.length);

    expect([
      screen.getByLabelText("橘猫原始视频 视频").getAttribute("src"),
      screen.getByLabelText("测试项目最终成片 视频").getAttribute("src"),
      screen.getByRole("img", { name: "圆润大橘猫" }).getAttribute("src"),
    ]).toEqual([
      "/api/qwenpaw-creator/media/assets/cat-video-v1",
      "/api/qwenpaw-creator/media/artifacts/final-v1",
      "/api/qwenpaw-creator/media/artifacts/cat-anchor-v1",
    ]);

    // Selecting exposes the canonical ref; the hand-off button stays removed.
    fireEvent.click(screen.getByText("测试项目最终成片"));
    expect(screen.getByText("artifact-version:final-v1")).toBeInTheDocument();
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "artifact-version:final-v1",
    );
    expect(
      screen.queryByRole("button", { name: "交给 Agent" }),
    ).not.toBeInTheDocument();
  });

  it("filters locally without requiring a separate backend asset projection", () => {
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "来源素材" }));
    expect(screen.getByText("1 项")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "视频" }));
    expect(screen.getByText("3 项")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("搜索名称或 ID"), {
      target: { value: "最终" },
    });
    expect(screen.getByText("1 项")).toBeInTheDocument();
    expect(screen.getByText("测试项目最终成片")).toBeInTheDocument();
  });

  it("ingests uploads and URL/text through the retained ATTACH_SOURCE endpoint and refreshes", async () => {
    const { calls } = installMockFetch(
      ingestRoutes({
        json: { assetId: "asset:new", taskId: "task:new", status: "QUEUED" },
      }),
    );
    const { container } = renderPage();
    const file = uploadFile(container, "new-cat.mp4", "video/mp4");

    // Upload posts the canonical request, then refreshes the Project.
    const posts = () => calls.filter((call) => call.method === "POST");
    await waitFor(() => expect(posts()).toHaveLength(1));
    expect(posts()[0].body).toMatchObject({
      postIngestAction: "ATTACH_SOURCE",
      file,
    });
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("p1/project"))).toBe(true),
    );

    // URL/text ingest submits the same canonical ATTACH_SOURCE shape.
    fireEvent.click(screen.getByRole("button", { name: "添加链接或文本" }));
    fireEvent.change(screen.getByPlaceholderText("素材名称"), {
      target: { value: "参考链接" },
    });
    fireEvent.change(screen.getByPlaceholderText("https://…"), {
      target: { value: "https://example.com/cat.mp4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交入库" }));

    await waitFor(() => expect(posts()).toHaveLength(2));
    expect(posts()[1].body).toMatchObject({
      kind: "url",
      name: "参考链接",
      value: "https://example.com/cat.mp4",
      postIngestAction: "ATTACH_SOURCE",
    });
  });

  it("keeps the rejection reason visible when an unsupported source is uploaded", async () => {
    installMockFetch(
      ingestRoutes({
        ok: false,
        status: 422,
        json: {
          code: "VALIDATION_ERROR",
          message: "不支持的来源素材格式: unsupported.glb（model/gltf-binary）",
          retryable: false,
          details: {},
        },
      }),
    );
    const { container } = renderPage();
    uploadFile(container, "unsupported.glb", "model/gltf-binary");

    // A persistent inline alert outlives the toast (acceptance B6).
    const selector = '[data-creator-module="asset-upload-error"]';
    await waitFor(() =>
      expect(container.querySelector(selector)).not.toBeNull(),
    );
    const banner = container.querySelector(selector)!;
    expect(banner.textContent).toContain("不支持的来源素材格式");
    expect(banner.textContent).toContain("unsupported.glb");
    fireEvent.click(screen.getByRole("button", { name: "关闭错误提示" }));
    expect(container.querySelector(selector)).toBeNull();
  });

  it("scopes the memory badge to the selected, built version of a logical asset", () => {
    // v1 built (SUCCEEDED task + current intelligence points at v1).
    seedMemorySnapshot(false);
    const { container, unmount } = renderPage();
    expect(
      container.querySelector('[data-creator-memory-badge="cat-video-v1"]'),
    ).toBeInTheDocument();
    unmount();

    // v2 selected but unbuilt: the stale SUCCEEDED task and intelligence
    // pointer of the same logical asset must not decorate it.
    seedMemorySnapshot(true);
    const second = renderPage();
    expect(
      second.container.querySelector("[data-creator-memory-badge]"),
    ).not.toBeInTheDocument();
  });

  it("opens a cast lineup card without crashing and edits relative notes", async () => {
    // Regression: lineup cards reuse kind "visual" but have no variants tree;
    // the detail panel used to crash walking variants.order.
    const project = cloneProject();
    (project.visual as Record<string, unknown>).cast_lineups = {
      items: {
        "lineup:duo": {
          lineup_id: "lineup:duo",
          name: "双人组",
          character_refs: ["cat", "cat"],
          relative_notes: "左矮右高",
          generated_artifact_version_ids: [],
          selected_artifact_version_id: null,
        },
      },
      order: ["lineup:duo"],
    };
    seedProject(project);
    installMockFetch(ingestRoutes());
    renderPage();

    fireEvent.click(screen.getByText("双人组"));

    expect(await screen.findByText("相对关系说明")).toBeInTheDocument();
    expect(screen.getAllByText(/左矮右高/).length).toBeGreaterThan(0);
  });
});
