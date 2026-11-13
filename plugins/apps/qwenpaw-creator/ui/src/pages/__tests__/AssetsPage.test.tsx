import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Modal, message } from "antd";
import AssetsPage, {
  GenerationPromptEditor,
  visualEntityPromptTarget,
  VoiceGenerationModal,
} from "@/pages/AssetsPage";
import BlueprintPrepDrawer from "@/components/blueprint/BlueprintPrepDrawer";
import { navigate, NavigationRuntime } from "@/routing/navigation";
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

/** Snapshot/task/session reads any Project page fires while it renders. */
function projectRoutes(projectId: string) {
  return [
    {
      match: `/projects/${projectId}/project`,
      method: "GET",
      response: {
        json: {
          projectId,
          generation: 3,
          etag: '"sha256:g3"',
          syncStatus: "healthy",
          project: cloneProject(),
        },
      },
    },
    {
      match: `/projects/${projectId}/specialist-runs`,
      response: { json: { items: [] } },
    },
    {
      match: `/projects/${projectId}/tasks`,
      response: { json: { items: [] } },
    },
    {
      match: `/projects/${projectId}/session`,
      response: { json: { session: null } },
    },
  ] as Parameters<typeof installMockFetch>[0];
}

/**
 * Install routes whose DELETE answer is held back until `release()`, so a test
 * can move the user elsewhere while the request is still in flight.
 */
function gateSourceDelete(routes: Parameters<typeof installMockFetch>[0]) {
  let release!: () => void;
  const blocked = new Promise<void>((resolve) => {
    release = resolve;
  });
  const mock = installMockFetch([
    {
      match: "/assets/cat-video-v1",
      method: "DELETE",
      response: { ok: true, status: 204, json: null },
    },
    ...routes,
  ]);
  const inner = mock.fetchMock;
  const attempted: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if ((init?.method ?? "GET").toUpperCase() === "DELETE") {
        // Recorded before the wait: the caller only learns the request left the
        // browser once the answer is released.
        attempted.push(url);
        await blocked;
      }
      return inner(url as never, init as never) as unknown as Response;
    }),
  );
  const deleteLanded = () => attempted.length > 0;
  // Reads only: the gated DELETE is recorded once its answer is released.
  const p1Reads = () =>
    mock.calls.filter(
      (call) => call.method === "GET" && call.url.includes("/projects/p1/"),
    ).length;
  return { release, deleteLanded, p1Reads, calls: mock.calls };
}

type ConfirmOptions = Parameters<typeof Modal.confirm>[0];

/** Replace the confirm dialog with a capturable handler (no portal needed). */
function captureConfirmDialog() {
  let options: ConfirmOptions | undefined;
  vi.spyOn(Modal, "confirm").mockImplementation(((config: ConfirmOptions) => {
    options = config;
    return { destroy: vi.fn(), update: vi.fn() };
  }) as typeof Modal.confirm);
  return {
    open: () => options !== undefined,
    accept: () => void options?.onOk?.(),
  };
}

function LocationProbe() {
  const location = useLocation();
  return (
    <output data-location>{`${location.pathname}${location.search}`}</output>
  );
}

function renderAssetsRoutes(entry: string) {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <NavigationRuntime />
      <Routes>
        <Route path="/project/:id/assets" element={<AssetsPage />} />
        {/* Sibling page of the same Project: leaving it must not be undone. */}
        <Route path="/project/:id/plan" element={<div data-plan-page />} />
      </Routes>
      <LocationProbe />
    </MemoryRouter>,
  );
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

    // Selecting exposes the canonical ref (the raw ref text is no longer a
    // visible field per the updated design); the hand-off button stays removed.
    fireEvent.click(screen.getByText("测试项目最终成片"));
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "artifact-version:final-v1",
    );
    expect(
      screen.queryByRole("button", { name: "交给 Agent" }),
    ).not.toBeInTheDocument();
  });

  it("filters locally without requiring a separate backend asset projection", () => {
    const { container } = renderPage();
    // 来源下拉（设计 84:78645）：只看上传的来源素材。
    const openOrigin = () =>
      fireEvent.mouseDown(
        container.querySelector('[data-assets-origin] [role="combobox"]')!
          .parentElement!.parentElement!,
      );
    openOrigin();
    fireEvent.click(
      document.querySelector('.ant-select-item-option[title="来源素材"]')!,
    );
    expect(screen.getAllByText("1 项").length).toBeGreaterThan(0);

    openOrigin();
    fireEvent.click(
      document.querySelector('.ant-select-item-option[title="全部来源"]')!,
    );
    fireEvent.click(screen.getByRole("button", { name: "视频" }));
    expect(screen.getAllByText("3 项").length).toBeGreaterThan(0);
    fireEvent.change(screen.getByPlaceholderText("搜索名称或 ID"), {
      target: { value: "最终" },
    });
    expect(screen.getAllByText("1 项").length).toBeGreaterThan(0);
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

    // The default 按归属 view shows the lineup card's ownership card name.
    fireEvent.click(screen.getByText("双人组（阵容图）"));

    expect(await screen.findByText("相对关系说明")).toBeInTheDocument();
    expect(screen.getAllByText(/左矮右高/).length).toBeGreaterThan(0);
  });

  it("keeps the ungenerated variant selected during background updates and dispatches that variant", async () => {
    const project = cloneProject();
    const entity = project.visual.entities.items.cat;
    entity.required_variant_ids.push("variant:cat:wet");
    entity.variants.order.push("variant:cat:wet");
    entity.variants.items["variant:cat:wet"] = {
      ...entity.variants.items["variant:cat:default"],
      variant_id: "variant:cat:wet",
      requirements: "淋湿后的造型",
      prompt: "以主图为参考，仅把毛发改为淋湿状态",
      reference_artifact_version_ids: ["cat-anchor-v1"],
      generated_artifact_version_ids: [],
      selected_artifact_version_id: null,
    };
    seedProject(project);
    const { calls } = installMockFetch([
      {
        match: "/dispatch",
        method: "POST",
        response: { json: { dispatched: true } },
      },
      ...ingestRoutes(),
    ]);
    const drawer = (snapshot: ProjectDocument) => (
      <MemoryRouter>
        <BlueprintPrepDrawer
          project={snapshot}
          projectId="p1"
          open
          tab="visual"
          focus={null}
          onClose={() => {}}
          onTabChange={() => {}}
        />
      </MemoryRouter>
    );
    const { container, rerender } = render(drawer(project));
    fireEvent.click(screen.getByRole("button", { name: /^圆润大橘猫/ }));
    fireEvent.click(screen.getByRole("button", { name: "淋湿后的造型" }));
    expect(screen.getByText("设计图待生成")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /v1/ }),
    ).not.toBeInTheDocument();

    rerender(drawer({ ...structuredClone(project), generation: 4 }));
    expect(
      screen.getByRole("button", { name: "淋湿后的造型" }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText("以主图为参考，仅把毛发改为淋湿状态"),
    ).toBeInTheDocument();
    expect(container.querySelector("[data-prompt-edit]")).toHaveAttribute(
      "data-prompt-edit",
      "/visual/entities/items/cat/variants/items/variant:cat:wet/prompt",
    );
    fireEvent.click(screen.getByRole("button", { name: "重新生成图片" }));
    await waitFor(() =>
      expect(
        calls.filter((call) => call.method === "POST").map((call) => call.url),
      ).toEqual([
        "/api/qwenpaw-creator/projects/p1/work-graph/nodes/visual%3Acat%3Avariant%3Acat%3Awet/dispatch",
      ]),
    );
  });

  it("keeps an anchor's selected image out of the reference picker", () => {
    const project = cloneProject();
    const entity = project.visual.entities.items.cat;
    entity.variants.items["derived"] = {
      ...entity.variants.items["variant:cat:default"],
      variant_id: "derived",
      prompt: "保持 [Image 1] 的角色身份",
      reference_artifact_version_ids: ["visual:cat:variant:cat:default"],
      generated_artifact_version_ids: [],
      selected_artifact_version_id: null,
    };
    entity.variants.order.push("derived");
    project.assets.artifact_versions_by_id["another-image"] = {
      ...project.assets.artifact_versions_by_id["cat-anchor-v1"],
      version_id: "another-image",
    };
    render(
      <GenerationPromptEditor
        target={visualEntityPromptTarget(project, entity, null, "derived")!}
        onSave={vi.fn()}
        saving={false}
        regenerateLabel="重新生成图片"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    expect(
      document.querySelector('[data-prompt-reference-row="1"] img'),
    ).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/cat-anchor-v1",
    );
    fireEvent.click(document.querySelector("[data-prompt-add-reference]")!);
    expect(
      document.querySelector('[data-picker-asset="cat-anchor-v1"]'),
    ).toBeNull();
    expect(
      document.querySelector('[data-picker-asset="another-image"]'),
    ).toBeInTheDocument();
  });
});

it("uses the uploaded audio picked by the user even after entering a voice description", async () => {
  const project = cloneProject();
  project.assets.source_versions_by_id["uploaded-voice"] = {
    ...project.assets.source_versions_by_id["cat-video-v1"],
    version_id: "uploaded-voice",
    logical_asset_id: "user-audio",
    name: "我的参考音频.wav",
    media_kind: "audio",
    media_type: "audio/wav",
  };
  seedProject(project);
  const { calls } = installMockFetch([
    {
      match: "/voice-capabilities",
      response: {
        json: { configured: true, supportsDesign: true, model: "test" },
      },
    },
    {
      match: "/character-voice",
      method: "POST",
      response: { json: { ok: true } },
    },
    ...ingestRoutes(),
  ]);
  const { baseElement } = render(
    <VoiceGenerationModal
      open
      projectId="p1"
      entity={project.visual.entities.items.cat}
      onClose={() => {}}
    />,
  );
  const prompt = await screen.findByPlaceholderText(/描述想要的音色/);
  fireEvent.change(prompt, { target: { value: "温柔的声音" } });
  fireEvent.click(screen.getByRole("button", { name: /选择一段.*音频素材/ }));
  fireEvent.click(
    baseElement.querySelector('[data-picker-asset="uploaded-voice"]')!,
  );
  expect(
    baseElement.querySelector('audio[aria-label="我的参考音频.wav"]'),
  ).toHaveAttribute("src", expect.stringContaining("uploaded-voice"));
  fireEvent.click(baseElement.querySelector("[data-picker-confirm]")!);
  expect(prompt).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: /^生\s*成$/ }));
  await waitFor(() =>
    expect(
      calls.find((call) => call.url.endsWith("/character-voice"))?.body,
    ).toEqual({
      characterRef: "asset:cat",
      sampleSourceVersionId: "uploaded-voice",
      preferredName: project.visual.entities.items.cat.name,
    }),
  );
});

describe("AssetsPage delete callback ownership", () => {
  beforeEach(() => {
    message.destroy();
    useProjectSnapshotStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    seedProject();
  });
  afterEach(() => {
    // antd's message API is a module singleton; leftover toasts would make the
    // "delete landed" text ambiguous in the next test.
    message.destroy();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  const locationPath = () =>
    document.querySelector("[data-location]")?.textContent ?? "";
  // antd's message list is a module singleton, so count the success toasts
  // instead of querying their text: the count grows exactly when the delete
  // callback resumes after the gated response.
  const successToasts = () =>
    document.querySelectorAll(".ant-message-notice-success").length;

  it("does not rebind stores when the delete lands after the user switched Project", async () => {
    const gate = gateSourceDelete([
      ...projectRoutes("p1"),
      ...projectRoutes("p2"),
    ]);
    const dialog = captureConfirmDialog();
    renderAssetsRoutes("/project/p1/assets?asset=cat-video-v1");

    fireEvent.click(
      document.querySelector('[data-asset-delete="cat-video-v1"]')!,
    );
    expect(dialog.open()).toBe(true);
    dialog.accept();
    await waitFor(() => expect(gate.deleteLanded()).toBe(true));

    act(() => navigate("/project/p2/plan"));
    await waitFor(() => expect(locationPath()).toBe("/project/p2/plan"));
    useProjectSnapshotStore.setState({
      projectId: "p2",
      project: cloneProject(),
      generation: 3,
      etag: '"sha256:g3"',
      syncStatus: "healthy",
    });
    useCreatorTaskViewStore.setState({ projectId: "p2", tasks: [] });
    const readsBefore = gate.p1Reads();
    const toastsBefore = successToasts();

    act(() => gate.release());
    await waitFor(() => expect(successToasts()).toBeGreaterThan(toastsBefore));

    expect(gate.p1Reads()).toBe(readsBefore);
    expect(useProjectSnapshotStore.getState().projectId).toBe("p2");
    expect(useCreatorTaskViewStore.getState().projectId).toBe("p2");
    expect(locationPath()).toBe("/project/p2/plan");
  });

  it("does not pull the user back to the assets page after leaving it", async () => {
    const gate = gateSourceDelete(projectRoutes("p1"));
    const dialog = captureConfirmDialog();
    renderAssetsRoutes("/project/p1/assets?asset=cat-video-v1");

    fireEvent.click(
      document.querySelector('[data-asset-delete="cat-video-v1"]')!,
    );
    dialog.accept();
    await waitFor(() => expect(gate.deleteLanded()).toBe(true));

    act(() => navigate("/project/p1/plan"));
    await waitFor(() => expect(locationPath()).toBe("/project/p1/plan"));
    const readsBefore = gate.p1Reads();
    const toastsBefore = successToasts();

    act(() => gate.release());
    await waitFor(() => expect(successToasts()).toBeGreaterThan(toastsBefore));

    // The selection cleanup navigates, and the deleted asset was selected when
    // the request started, so the late callback used to yank this page away.
    expect(locationPath()).toBe("/project/p1/plan");
    expect(gate.p1Reads()).toBe(readsBefore);
  });

  it("keeps the asset selected while the delete was in flight", async () => {
    const gate = gateSourceDelete(projectRoutes("p1"));
    const dialog = captureConfirmDialog();
    renderAssetsRoutes("/project/p1/assets?asset=cat-video-v1");

    fireEvent.click(
      document.querySelector('[data-asset-delete="cat-video-v1"]')!,
    );
    dialog.accept();
    await waitFor(() => expect(gate.deleteLanded()).toBe(true));

    fireEvent.click(screen.getByText("测试项目最终成片"));
    await waitFor(() => expect(locationPath()).toContain("asset="));
    const selectedPath = locationPath();
    const toastsBefore = successToasts();

    act(() => gate.release());
    await waitFor(() => expect(successToasts()).toBeGreaterThan(toastsBefore));
    // The stale closure over the pre-delete selection used to clear this.
    expect(locationPath()).toBe(selectedPath);
  });

  it("refreshes and drops the deleted selection when the user stayed", async () => {
    const gate = gateSourceDelete(projectRoutes("p1"));
    const dialog = captureConfirmDialog();
    renderAssetsRoutes("/project/p1/assets?asset=cat-video-v1");

    fireEvent.click(
      document.querySelector('[data-asset-delete="cat-video-v1"]')!,
    );
    dialog.accept();
    await waitFor(() => expect(gate.deleteLanded()).toBe(true));
    const readsBefore = gate.p1Reads();
    const toastsBefore = successToasts();

    act(() => gate.release());
    await waitFor(() => expect(successToasts()).toBeGreaterThan(toastsBefore));
    await waitFor(() => expect(gate.p1Reads()).toBeGreaterThan(readsBefore));
    expect(locationPath()).toBe("/project/p1/assets");
  });

  it("still owns the page when the assets URL carries a trailing slash", async () => {
    // Router matches "/project/p1/assets/" too and keeps that slash in
    // location.pathname. Comparing it strictly made every post-delete step
    // look like the user had left, so the deleted asset stayed in the list,
    // in the detail pane and in the URL.
    const gate = gateSourceDelete(projectRoutes("p1"));
    const dialog = captureConfirmDialog();
    renderAssetsRoutes("/project/p1/assets/?asset=cat-video-v1");

    fireEvent.click(
      document.querySelector('[data-asset-delete="cat-video-v1"]')!,
    );
    expect(dialog.open()).toBe(true);
    dialog.accept();
    await waitFor(() => expect(gate.deleteLanded()).toBe(true));
    const readsBefore = gate.p1Reads();
    const toastsBefore = successToasts();

    act(() => gate.release());
    await waitFor(() => expect(successToasts()).toBeGreaterThan(toastsBefore));
    await waitFor(() => expect(gate.p1Reads()).toBeGreaterThan(readsBefore));
    expect(locationPath()).toBe("/project/p1/assets");
  });
});

/**
 * One 409 ASSET_IN_USE body: the backend names every Element that still
 * points at the asset, plus whether a force delete may clear it.
 */
function inUseBody(references: Array<Record<string, unknown>>) {
  return {
    code: "ASSET_IN_USE",
    message:
      "Cannot delete source asset version cat-video-v1: actively used in " +
      "timeline by ['i2v-first-frame:elem:shot-1']",
    retryable: false,
    details: { versionId: "cat-video-v1", timelineReferences: references },
  };
}

const DETACHABLE_REFERENCES = [
  {
    timelineId: "timeline:main",
    timelineName: "主时间线",
    isSnapshot: false,
    elementId: "elem:shot-1",
    elementLabel: "镜头一｜风雪定场",
    creationType: "i2v",
    refKind: "i2v-first-frame",
    detachable: true,
    pointer: "i2v-first-frame:elem:shot-1",
  },
  {
    timelineId: "snapshot:timeline:main:1",
    timelineName: "快照 · 主时间线",
    isSnapshot: true,
    elementId: "snapshot:timeline:main:1:elem:shot-1",
    elementLabel: "镜头一｜风雪定场",
    creationType: "i2v",
    refKind: "i2v-first-frame",
    detachable: true,
    pointer: "snapshot:timeline:main:1/i2v-first-frame:elem:shot-1",
  },
];

const BLOCKING_REFERENCES = [
  {
    timelineId: "timeline:main",
    timelineName: "主时间线",
    isSnapshot: false,
    elementId: "elem:vo-1",
    elementLabel: "旁白",
    creationType: "audio",
    refKind: "audio-source",
    detachable: false,
    pointer: "audio-source:elem:vo-1",
  },
];

/** Capture both dialog flavours without their portals, like captureConfirmDialog. */
function captureDialogs() {
  const confirms: ConfirmOptions[] = [];
  const warnings: Array<Parameters<typeof Modal.warning>[0]> = [];
  vi.spyOn(Modal, "confirm").mockImplementation(((config: ConfirmOptions) => {
    confirms.push(config);
    return { destroy: vi.fn(), update: vi.fn() };
  }) as typeof Modal.confirm);
  vi.spyOn(Modal, "warning").mockImplementation(((
    config: Parameters<typeof Modal.warning>[0],
  ) => {
    warnings.push(config);
    return { destroy: vi.fn(), update: vi.fn() };
  }) as typeof Modal.warning);
  return {
    confirms,
    warnings,
    accept: (index: number) => void confirms[index]?.onOk?.(),
  };
}

describe("AssetsPage delete of an asset the timeline still uses", () => {
  beforeEach(() => {
    message.destroy();
    useProjectSnapshotStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    seedProject();
  });
  afterEach(() => {
    message.destroy();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  const startDelete = () => {
    fireEvent.click(
      document.querySelector('[data-asset-delete="cat-video-v1"]')!,
    );
  };
  const deleteUrls = (calls: Array<{ method: string; url: string }>) =>
    calls.filter((call) => call.method === "DELETE").map((call) => call.url);
  const toasts = (kind: "success" | "error") =>
    document.querySelectorAll(`.ant-message-notice-${kind}`).length;
  // antd's message list is a module singleton shared with the other suites in
  // this file, so only the growth of each kind says anything about this delete.
  const toastCount = () => ({
    success: toasts("success"),
    error: toasts("error"),
  });

  it("names the shot, then retries once the user insists", async () => {
    const mock = installMockFetch([
      {
        match: "/assets/cat-video-v1?force=true",
        method: "DELETE",
        response: { ok: true, status: 204, json: null },
      },
      {
        match: "/assets/cat-video-v1",
        method: "DELETE",
        response: {
          ok: false,
          status: 409,
          json: inUseBody(DETACHABLE_REFERENCES),
        },
      },
      ...projectRoutes("p1"),
    ]);
    const dialogs = captureDialogs();
    renderAssetsRoutes("/project/p1/assets");
    const before = toastCount();

    startDelete();
    dialogs.accept(0);
    await waitFor(() => expect(dialogs.confirms).toHaveLength(2));
    expect(dialogs.warnings).toHaveLength(0);
    expect(dialogs.confirms[1].okText).toBe("仍要删除");

    // The dialog is what the user judges the risk on: named shots in Chinese,
    // not the internal ids the backend sentence used to expose.
    const dialog = render(dialogs.confirms[1].content as ReactElement);
    expect(dialog.getAllByText(/镜头一｜风雪定场/)).toHaveLength(2);
    expect(dialog.getAllByText(/首帧/)).toHaveLength(2);
    expect(
      dialog.getByText(/历史快照中的引用也会一并解除/),
    ).toBeInTheDocument();
    dialog.unmount();

    dialogs.accept(1);
    await waitFor(() =>
      expect(deleteUrls(mock.calls)).toEqual([
        expect.stringContaining("/assets/cat-video-v1"),
        expect.stringContaining("/assets/cat-video-v1?force=true"),
      ]),
    );
    await waitFor(() =>
      expect(toasts("success")).toBeGreaterThan(before.success),
    );
    expect(toasts("error")).toBe(before.error);
  });

  it("refuses to retry when a reference cannot detach", async () => {
    const mock = installMockFetch([
      {
        match: "/assets/cat-video-v1",
        method: "DELETE",
        response: {
          ok: false,
          status: 409,
          json: inUseBody(BLOCKING_REFERENCES),
        },
      },
      ...projectRoutes("p1"),
    ]);
    const dialogs = captureDialogs();
    renderAssetsRoutes("/project/p1/assets");
    const before = toastCount();

    startDelete();
    dialogs.accept(0);
    await waitFor(() => expect(dialogs.warnings).toHaveLength(1));

    const dialog = render(dialogs.warnings[0].content as ReactElement);
    expect(dialog.getByText(/旁白/)).toBeInTheDocument();
    expect(dialog.getByText(/音轨元素的源素材不可为空/)).toBeInTheDocument();
    dialog.unmount();

    // A force retry over an audio Element would fail the same way, so the UI
    // must send exactly one DELETE and point at the Element to remove.
    expect(deleteUrls(mock.calls)).toHaveLength(1);
    expect(dialogs.confirms).toHaveLength(1);
    expect(toasts("success")).toBe(before.success);
    expect(toasts("error")).toBe(before.error);
  });

  it("re-reads the conflict when the library changed mid-dialog", async () => {
    // Someone attached an audio Element while the confirm dialog was open, so
    // the force retry comes back refused. That late 409 must still name the
    // Element instead of dumping the backend's internal sentence in a toast.
    const mock = installMockFetch([
      {
        match: "/assets/cat-video-v1?force=true",
        method: "DELETE",
        response: {
          ok: false,
          status: 409,
          json: inUseBody(BLOCKING_REFERENCES),
        },
      },
      {
        match: "/assets/cat-video-v1",
        method: "DELETE",
        response: {
          ok: false,
          status: 409,
          json: inUseBody(DETACHABLE_REFERENCES),
        },
      },
      ...projectRoutes("p1"),
    ]);
    const dialogs = captureDialogs();
    renderAssetsRoutes("/project/p1/assets");
    const before = toastCount();

    startDelete();
    dialogs.accept(0);
    await waitFor(() => expect(dialogs.confirms).toHaveLength(2));
    dialogs.accept(1);

    await waitFor(() => expect(dialogs.warnings).toHaveLength(1));
    const dialog = render(dialogs.warnings[0].content as ReactElement);
    expect(dialog.getByText(/旁白/)).toBeInTheDocument();
    dialog.unmount();

    // No third attempt and no success claim: the bytes are still held.
    expect(deleteUrls(mock.calls)).toHaveLength(2);
    expect(dialogs.confirms).toHaveLength(2);
    expect(toasts("success")).toBe(before.success);
    expect(toasts("error")).toBe(before.error);
  });

  it("keeps the plain failure toast for other errors", async () => {
    const mock = installMockFetch([
      {
        match: "/assets/cat-video-v1",
        method: "DELETE",
        response: {
          ok: false,
          status: 500,
          json: { code: "STORAGE_INTEGRITY_ERROR", message: "素材库读取失败" },
        },
      },
      ...projectRoutes("p1"),
    ]);
    const dialogs = captureDialogs();
    renderAssetsRoutes("/project/p1/assets");
    const toastBaseline = toastCount();

    startDelete();
    dialogs.accept(0);
    await waitFor(() =>
      expect(toasts("error")).toBeGreaterThan(toastBaseline.error),
    );

    expect(deleteUrls(mock.calls)).toHaveLength(1);
    expect(dialogs.confirms).toHaveLength(1);
    expect(dialogs.warnings).toHaveLength(0);
    expect(screen.queryByText(/仍要删除/)).not.toBeInTheDocument();
  });
});

describe("AssetsPage upload of a file the Project already holds", () => {
  beforeEach(() => {
    message.destroy();
    useProjectSnapshotStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    seedProject();
  });
  afterEach(() => {
    message.destroy();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  // antd's message list is a module singleton and its nodes outlive a test, so
  // every assertion here compares each kind against a per-test baseline.
  const toastCounts = () => ({
    success: document.querySelectorAll(".ant-message-notice-success").length,
    info: document.querySelectorAll(".ant-message-notice-info").length,
  });

  it("reports the reuse instead of congratulating a second upload", async () => {
    // The backend folded these bytes into the Asset it already had, so the
    // page must not promise a card that never arrived.
    const { calls } = installMockFetch(
      ingestRoutes({
        json: {
          assetId: "asset:existing",
          taskId: "task:existing",
          status: "SUCCEEDED",
          assetVersionId: "cat-video-v1",
          reused: true,
        },
      }),
    );
    const { container } = renderPage();
    const before = toastCounts();

    uploadFile(container, "同一张图.png", "image/png");

    expect(
      await screen.findByText(/同一张图\.png 与已有素材内容相同/),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.some((call) => call.url.endsWith("p1/project"))).toBe(true),
    );
    await waitFor(() =>
      expect(toastCounts().info).toBeGreaterThan(before.info),
    );
    expect(toastCounts().success).toBe(before.success);
  });

  it("names the stored asset when the reused bytes came from a rename", async () => {
    // The card in the library keeps the first name, so the toast has to point
    // at that one or the user looks for a card that never existed.
    installMockFetch(
      ingestRoutes({
        json: {
          assetId: "asset:existing",
          taskId: "task:existing",
          status: "SUCCEEDED",
          assetVersionId: "cat-video-v1",
          reused: true,
          reusedName: "开场图.png",
        },
      }),
    );
    const { container } = renderPage();

    uploadFile(container, "later-name.png", "image/png");

    expect(
      await screen.findByText(/开场图\.png 与已有素材内容相同/),
    ).toBeInTheDocument();
  });

  it("keeps the success toast for a genuinely new asset", async () => {
    installMockFetch(
      ingestRoutes({
        json: {
          assetId: "asset:new",
          taskId: "task:new",
          status: "QUEUED",
          assetVersionId: "cat-video-v2",
          reused: false,
        },
      }),
    );
    const { container } = renderPage();
    const before = toastCounts();

    uploadFile(container, "fresh.png", "image/png");

    await waitFor(() =>
      expect(toastCounts().success).toBeGreaterThan(before.success),
    );
    expect(toastCounts().info).toBe(before.info);
  });
});
