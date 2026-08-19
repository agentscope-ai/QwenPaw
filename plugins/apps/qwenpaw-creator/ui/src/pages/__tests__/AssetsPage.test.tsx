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
    response: { json?: unknown; status?: number; ok?: boolean };
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

  it("groups visual settings by entity and keeps active versus historical state in flat artifact views", () => {
    const project = cloneProject();
    project.assets.files_by_id["file:cat-history"] = {
      file_id: "file:cat-history",
      kind: "artifact",
      relative_uri: "artifacts/cat-history.png",
      sha256: "sha-cat-history",
      size_bytes: 500,
      media_type: "image/png",
      created_at: "2026-07-19T00:00:00Z",
    };
    project.assets.artifact_slots_by_id[
      "visual:cat:anchor"
    ].version_ids.unshift("cat-anchor-history");
    project.assets.artifact_versions_by_id["cat-anchor-history"] = {
      ...project.assets.artifact_versions_by_id["cat-anchor-v1"],
      version_id: "cat-anchor-history",
      name: "橘猫角色锚点旧版",
      file_id: "file:cat-history",
      checksum: "sha-cat-history",
      created_at: "2026-07-19T00:00:00Z",
      metadata: { variantId: "variant:cat:default" },
    };
    project.visual.entities.items.cat.variants.items[
      "variant:cat:default"
    ].generated_artifact_version_ids.unshift("cat-anchor-history");
    seedProject(project);
    const { container } = renderPage();

    fireEvent.click(screen.getByRole("button", { name: "视觉设定" }));
    expect(screen.getByText("圆润大橘猫")).toBeInTheDocument();
    expect(screen.getByText("1 个造型")).toBeInTheDocument();
    expect(screen.getByText("使用中")).toBeInTheDocument();
    expect(screen.queryByText("历史")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "生成产物" }));
    expect(screen.getByText("使用中")).toBeInTheDocument();
    expect(screen.getByText("历史")).toBeInTheDocument();
    expect(screen.getByText("橘猫角色锚点旧版")).toBeInTheDocument();
    expect(container.querySelectorAll("[data-asset-group]")).toHaveLength(0);
  });

  it("keeps character Variants under one entity and separates ungenerated scenes and props", () => {
    const project = cloneProject();
    project.visual.entities.items.cat.variants.order.push("variant:cat:night");
    project.visual.entities.items.cat.required_variant_ids.push(
      "variant:cat:night",
    );
    project.visual.entities.items.cat.variants.items["variant:cat:night"] = {
      variant_id: "variant:cat:night",
      requirements: "Pixar 3D风格。夜间造型：蓝色围巾、红色项圈",
      prompt: "夜间的圆润大橘猫",
      reference_asset_version_ids: [],
      reference_artifact_version_ids: [],
      generated_artifact_version_ids: [],
      selected_artifact_version_id: null,
    };
    project.visual.entities.order.push("scene:alley", "prop:bell");
    project.visual.entities.items["scene:alley"] = {
      entity_id: "scene:alley",
      kind: "scene",
      name: "雨夜小巷",
      description: "湿润路面与暖色路灯",
      continuity: "保持同一街区结构",
      required_variant_ids: ["variant:scene:default"],
      variants: {
        order: ["variant:scene:default"],
        items: {
          "variant:scene:default": {
            variant_id: "variant:scene:default",
            requirements: "Pixar 3D风格。雨夜街区环境设定",
            prompt: "雨夜小巷",
            reference_asset_version_ids: [],
            reference_artifact_version_ids: [],
            generated_artifact_version_ids: [],
            selected_artifact_version_id: null,
          },
        },
      },
      selected_artifact_version_id: null,
    };
    project.visual.entities.items["prop:bell"] = {
      entity_id: "prop:bell",
      kind: "prop",
      name: "红色铃铛",
      description: "主角项圈上的铃铛",
      continuity: "所有画面保持红色",
      required_variant_ids: ["variant:prop:default"],
      variants: {
        order: ["variant:prop:default"],
        items: {
          "variant:prop:default": {
            variant_id: "variant:prop:default",
            requirements: "Pixar 3D风格。红色铃铛道具设定",
            prompt: "红色铃铛",
            reference_asset_version_ids: [],
            reference_artifact_version_ids: [],
            generated_artifact_version_ids: [],
            selected_artifact_version_id: null,
          },
        },
      },
      selected_artifact_version_id: null,
    };
    seedProject(project);
    const { container } = renderPage();

    fireEvent.click(screen.getByRole("button", { name: "视觉设定" }));

    const groupLabels = Array.from(
      container.querySelectorAll<HTMLElement>("[data-asset-group]"),
    ).map((node) => node.textContent);
    expect(groupLabels).toEqual([
      expect.stringContaining("圆润大橘猫"),
      expect.stringContaining("场景"),
      expect.stringContaining("道具"),
    ]);
    expect(groupLabels[0]).toContain("2 个造型");
    expect(screen.getByRole("heading", { name: "Night" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "雨夜小巷" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "红色铃铛" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("待生成")).toHaveLength(3);

    fireEvent.click(screen.getByRole("button", { name: "图片" }));
    expect(container.querySelectorAll("[data-asset-group]")).toHaveLength(0);
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

  it("keeps the rejection reason visible when an unsupported source is uploaded", async () => {
    installMockFetch(
      ingestRoutes([
        {
          match: "/projects/p1/assets",
          method: "POST",
          response: {
            ok: false,
            status: 422,
            json: {
              code: "VALIDATION_ERROR",
              message:
                "不支持的来源素材格式: unsupported.glb（model/gltf-binary）。" +
                "支持图片、视频、音频，以及 PDF/Office/表格/字幕/纯文本等可读文档。",
              retryable: false,
              details: {},
            },
          },
        },
      ]),
    );
    const { container } = renderPage();
    const file = new File(["glb"], "unsupported.glb", {
      type: "model/gltf-binary",
    });
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });

    // A persistent inline alert keeps the readable reason on screen even
    // after the transient toast disappears (acceptance B6).
    const banner = await waitFor(() => {
      const found = container.querySelector(
        '[data-creator-module="asset-upload-error"]',
      );
      expect(found).not.toBeNull();
      return found!;
    });
    expect(banner.textContent).toContain("不支持的来源素材格式");
    expect(banner.textContent).toContain("unsupported.glb");
    fireEvent.click(screen.getByRole("button", { name: "关闭错误提示" }));
    expect(
      container.querySelector('[data-creator-module="asset-upload-error"]'),
    ).toBeNull();
  });

  it("binds document understanding to the selected source version", async () => {
    const project = cloneProject();
    const documentVersion = (
      versionId: string,
      name: string,
      checksum: string,
    ) => ({
      version_id: versionId,
      logical_asset_id: "asset:script",
      name,
      file_id: "file:source-video",
      checksum,
      media_kind: "document" as const,
      media_type: "application/pdf",
      provenance_refs: [],
      thumbnail_file_id: null,
      duration_seconds: null,
      native_model_file_id: null,
      created_at: "2026-07-21T00:00:00Z",
      metadata: {},
    });
    project.assets.source_versions_by_id["script-v1"] = documentVersion(
      "script-v1",
      "剧本旧版",
      "sha-script-v1",
    );
    project.assets.source_versions_by_id["script-v2"] = documentVersion(
      "script-v2",
      "剧本新版",
      "sha-script-v2",
    );
    project.assets.intelligence_versions_by_id["intel-v1"] = {
      intelligence_version_id: "intel-v1",
      source_asset_version_id: "script-v1",
      file_id: "file:intel-v1",
      source_checksum: "sha-script-v1",
      model_run_ids: [],
      coverage: {},
      created_at: "2026-07-21T01:00:00Z",
    };
    // A repeated analysis of the same source version: the Source's current
    // pointer references the newer record, which must win over the older
    // one that happens to appear first in the map.
    project.assets.intelligence_versions_by_id["intel-v1b"] = {
      intelligence_version_id: "intel-v1b",
      source_asset_version_id: "script-v1",
      file_id: "file:intel-v1b",
      source_checksum: "sha-script-v1",
      model_run_ids: [],
      coverage: {},
      created_at: "2026-07-21T02:00:00Z",
    };
    project.sources.sources.items["src-script"] = {
      source_id: "src-script",
      display_name: "剧本",
      logical_asset_id: "asset:script",
      selected_asset_version_id: "script-v1",
      current_intelligence_version_id: "intel-v1b",
      user_notes: "",
    };
    project.sources.sources.order.push("src-script");
    seedProject(project);
    const understanding = (summary: string) => ({
      media: {
        mediaKind: "document",
        mediaType: "application/pdf",
        document: { format: "pdf", pageCount: 2 },
      },
      summary,
      shots: [],
      semanticEntries: [],
    });
    const { calls } = installMockFetch(
      ingestRoutes([
        {
          match: "understanding/intel-v1b",
          response: { json: understanding("重分析后的理解摘要") },
        },
      ]),
    );
    renderPage();

    // The analyzed version loads the current (newest) analysis of that
    // exact source version, not the first record in the map.
    fireEvent.click(screen.getByText("剧本旧版"));
    expect(
      (await screen.findByText("重分析后的理解摘要")).textContent,
    ).toContain("重分析");
    expect(
      calls.some((call) => call.url.includes("understanding/intel-v1b")),
    ).toBe(true);
    expect(
      calls.some((call) => call.url.endsWith("understanding/intel-v1")),
    ).toBe(false);

    // The unanalyzed new version must not fall back to another version's
    // understanding: no request fires and an empty state renders.
    fireEvent.click(screen.getByText("剧本新版"));
    expect(
      await screen.findByText(/该版本尚未完成素材理解/),
    ).toBeInTheDocument();
    expect(
      calls.some(
        (call) =>
          call.url.includes("/understanding") &&
          !call.url.includes("understanding/intel-v1b"),
      ),
    ).toBe(false);
  });

  it("scopes the memory badge to the selected, built version of a logical asset", () => {
    // v1 built (SUCCEEDED task + current intelligence points at v1).
    const built = cloneProject();
    built.assets.intelligence_versions_by_id["intel-v1"] = {
      intelligence_version_id: "intel-v1",
      source_asset_version_id: "cat-video-v1",
      file_id: "file:source-video",
      source_checksum: "sha-source",
      model_run_ids: [],
      coverage: {},
      created_at: "2026-07-20T00:03:00Z",
    };
    built.sources.sources.items[
      "source:cat-video"
    ].current_intelligence_version_id = "intel-v1";
    seedProject(built);
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
    const { container, unmount } = renderPage();
    expect(
      container.querySelector('[data-creator-memory-badge="cat-video-v1"]'),
    ).toBeInTheDocument();
    unmount();

    // Same logical asset replaced by v2: selected but unbuilt. The old
    // SUCCEEDED task must not decorate the new version.
    const replaced = cloneProject();
    replaced.assets.source_versions_by_id["cat-video-v2"] = {
      ...replaced.assets.source_versions_by_id["cat-video-v1"],
      version_id: "cat-video-v2",
      checksum: "sha-source-v2",
      created_at: "2026-07-21T00:00:00Z",
    };
    replaced.assets.intelligence_versions_by_id["intel-v1"] = {
      intelligence_version_id: "intel-v1",
      source_asset_version_id: "cat-video-v1",
      file_id: "file:source-video",
      source_checksum: "sha-source",
      model_run_ids: [],
      coverage: {},
      created_at: "2026-07-20T00:03:00Z",
    };
    const source = replaced.sources.sources.items["source:cat-video"];
    source.selected_asset_version_id = "cat-video-v2";
    // Stale pointer still referencing the v1 intelligence.
    source.current_intelligence_version_id = "intel-v1";
    seedProject(replaced);
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
    const second = renderPage();
    expect(
      second.container.querySelector("[data-creator-memory-badge]"),
    ).not.toBeInTheDocument();
  });

  it("opens a cast lineup card without crashing and edits relative notes", async () => {
    // Regression: lineup cards reuse kind "visual", but their raw document
    // has no variants tree — the detail panel used to walk variants.order
    // and crash with "Cannot read properties of undefined".
    const project = cloneProject();
    (project.visual as Record<string, unknown>).cast_lineups = {
      items: {
        "lineup:duo": {
          lineup_id: "lineup:duo",
          name: "双人组",
          description: "两只猫并排",
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

    await waitFor(() =>
      expect(screen.getByText("相对关系说明")).toBeInTheDocument(),
    );
    expect(screen.getAllByText(/左矮右高/).length).toBeGreaterThan(0);
  });
});
