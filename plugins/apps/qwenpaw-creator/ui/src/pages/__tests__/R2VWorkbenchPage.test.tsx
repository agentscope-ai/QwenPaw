import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it } from "vitest";
import R2VWorkbenchPage from "@/pages/R2VWorkbenchPage";
import PlanPage from "@/pages/PlanPage";
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

function withSecondVideoVersion(project = cloneProject()): ProjectDocument {
  project.assets.files_by_id["file:r2v-video2"] = {
    file_id: "file:r2v-video2",
    kind: "artifact",
    relative_uri: "artifacts/window-2.mp4",
    sha256: "sha-r2v-2",
    size_bytes: 2048,
    media_type: "video/mp4",
    created_at: "2026-07-20T00:01:30Z",
  };
  project.assets.artifact_versions_by_id["r2v-window-v2"] = {
    ...project.assets.artifact_versions_by_id["r2v-window-v1"],
    version_id: "r2v-window-v2",
    name: "午饭名场面视频 v2",
    file_id: "file:r2v-video2",
    checksum: "sha-r2v-2",
    created_at: "2026-07-20T00:01:30Z",
  };
  project.assets.artifact_slots_by_id[
    "element:r2v-window:video"
  ].version_ids.push("r2v-window-v2");
  return project;
}

function modelRoutes(model: string): Parameters<typeof installMockFetch>[0] {
  return [
    {
      match: "/models/resolved",
      response: { json: { video: { provider: "wan", model } } },
    },
  ];
}

/** PATCH endpoint answering with the given next-generation Project. */
function patchRoutes(updated: ProjectDocument) {
  updated.generation = 4;
  const { calls } = installMockFetch([
    {
      match: "/projects/p1/project",
      method: "PATCH",
      response: {
        json: {
          projectId: "p1",
          generation: 4,
          etag: '"sha256:g4"',
          changedPointers: [],
          project: updated,
        },
      },
    },
  ]);
  return calls;
}

async function expectPatch(
  calls: ReturnType<typeof installMockFetch>["calls"],
  path: string,
  value: string,
) {
  await waitFor(() =>
    expect(calls.some((call) => call.method === "PATCH")).toBe(true),
  );
  expect(calls.find((call) => call.method === "PATCH")!.body).toMatchObject({
    operations: [{ op: "replace", path, value }],
  });
}

function renderWorkbench(entry = "/project/p1/plan/element/r2v-window") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <NavigationRuntime />
      <Routes>
        <Route path="/project/:id/plan" element={<PlanPage />} />
        <Route
          path="/project/:id/plan/element/:elementId"
          element={<R2VWorkbenchPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("R2V Workbench page", () => {
  beforeEach(() => {
    useProjectSnapshotStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    seedProject();
    // Default resolved-models mock so rendering never issues a real call.
    installMockFetch(modelRoutes("wan2.7-r2v"));
  });

  it("renders the origin/main workbench surfaces for an R2V Element", () => {
    const { container } = renderWorkbench();

    expect(
      screen.getByText(/视频方案 \/ 午饭名场面 \/ 制作工作台/),
    ).toBeInTheDocument();
    // No generation_mode in the legacy fixture → historical r2v default.
    expect(
      container.querySelector('[data-generation-mode="r2v"]'),
    ).toHaveTextContent("参考生视频");
    expect(screen.getByDisplayValue("橘猫隔窗看向午饭")).toBeInTheDocument();
    expect(
      container.querySelector('[data-artifact-version="r2v-window-v1"]'),
    ).toBeInTheDocument();
    expect(container.querySelector("video")).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/r2v-window-v1",
    );
    // 设计 84:38986 右栏只保留生成结果与元信息：引用素材/资产绑定不再渲染。
    expect(screen.queryByText(/引用素材/)).toBeNull();
    expect(screen.queryByText("资产绑定")).toBeNull();
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "element:r2v-window",
    );
  });

  it("round-trips between the Plan detail CTA and the workbench", async () => {
    renderWorkbench("/project/p1/plan?element=r2v-window");

    fireEvent.click(screen.getByRole("button", { name: /去制作台编辑/ }));
    // 制作台以工作区整页视图打开（片段编辑层设计，不再跳转独立路由）。
    await waitFor(() =>
      expect(
        screen.getByText(/视频方案 \/ 午饭名场面 \/ 制作工作台/),
      ).toBeInTheDocument(),
    );
    expect(
      document.querySelector("[data-workbench-modal='r2v-window']"),
    ).toBeInTheDocument();

    // 整页制作台通过页头「返回视频方案」箭头关闭。
    fireEvent.click(screen.getByRole("button", { name: "返回视频方案" }));
    await waitFor(() =>
      expect(
        document.querySelector("[data-workbench-modal='r2v-window']"),
      ).not.toBeInTheDocument(),
    );
    // The creative brief moved to the blueprint page; episode switching
    // lives in the workspace sidebar, so the plan page greets with the
    // timeline-title heading.
    expect(
      screen.getByRole("heading", { name: "第1集 · 晨光出发" }),
    ).toBeInTheDocument();
    // Prompt 编辑已迁往制作台；详情回落为关键信息总览。
    expect(screen.getByText("创作意图")).toBeInTheDocument();
  });

  it("keeps non-R2V Elements out of the workbench with a way back", () => {
    renderWorkbench("/project/p1/plan/element/edit-opening");

    expect(
      screen.getByText("该时间线内容不是 AI 生成画面，没有独立工作台"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "返回方案" }),
    ).toBeInTheDocument();
  });

  it.each<[string, string, string, string]>([
    [
      "prompt",
      "镜头缓慢推近，橘猫眨眼",
      "镜头快速拉远",
      "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/video_prompt",
    ],
    [
      "shot",
      "橘猫隔窗看向午饭",
      "橘猫扒着窗台",
      "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/shots/items/shot:window/description",
    ],
  ])(
    "auto-saves %s edits through the Project CAS Patch endpoint on blur",
    async (_field, current, next, path) => {
      const calls = patchRoutes(cloneProject());
      renderWorkbench();

      const input = screen.getByDisplayValue(current);
      fireEvent.change(input, { target: { value: next } });
      // Typing alone never commits; leaving the field is the save boundary.
      expect(calls.some((call) => call.method === "PATCH")).toBe(false);
      fireEvent.blur(input);
      await expectPatch(calls, path, next);
    },
  );

  it("dispatches the video node from the prompt-card regenerate button", async () => {
    const { calls } = installMockFetch([
      ...modelRoutes("wan2.7-r2v"),
      { match: "/specialist-runs", response: { json: { items: [] } } },
      { match: "/projects/p1/tasks", response: { json: { items: [] } } },
      {
        match: "/work-graph/nodes/video%3Ar2v-window/dispatch",
        method: "POST",
        response: {
          json: { ok: true, nodeId: "video:r2v-window", dispatched: true },
        },
      },
    ]);
    const { container } = renderWorkbench();

    fireEvent.click(container.querySelector('[data-stage-tab="vd"]')!);
    fireEvent.click(
      container.querySelector(
        '[data-prompt-regenerate="element:r2v-window/creation/video_prompt"]',
      )!,
    );
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === "POST" &&
            call.url.includes("/work-graph/nodes/video%3Ar2v-window/dispatch"),
        ),
      ).toBe(true),
    );
    // Clean draft: regenerate must not fire a project PATCH.
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
  });

  it("applies a dirty prompt draft before dispatching regeneration", async () => {
    const updated = cloneProject();
    updated.generation = 4;
    const { calls } = installMockFetch([
      ...modelRoutes("wan2.7-r2v"),
      { match: "/specialist-runs", response: { json: { items: [] } } },
      { match: "/projects/p1/tasks", response: { json: { items: [] } } },
      {
        match: "/projects/p1/project",
        method: "PATCH",
        response: {
          json: {
            projectId: "p1",
            generation: 4,
            etag: '"sha256:g4"',
            changedPointers: [],
            project: updated,
          },
        },
      },
      {
        match: "/work-graph/nodes/storyboard%3Ar2v-window/dispatch",
        method: "POST",
        response: {
          json: { ok: true, nodeId: "storyboard:r2v-window", dispatched: true },
        },
      },
    ]);
    const { container } = renderWorkbench();

    const sbPanel = container.querySelector('[data-stage-panel="sb"]')!;
    fireEvent.change(sbPanel.querySelector("textarea")!, {
      target: { value: "新的分镜 Prompt" },
    });
    fireEvent.click(
      container.querySelector(
        '[data-prompt-regenerate="element:r2v-window/creation/storyboard_prompt"]',
      )!,
    );
    await waitFor(() =>
      expect(
        calls.some(
          (call) =>
            call.method === "POST" &&
            call.url.includes(
              "/work-graph/nodes/storyboard%3Ar2v-window/dispatch",
            ),
        ),
      ).toBe(true),
    );
    // The new prompt must be persisted before the node is dispatched.
    const patchIndex = calls.findIndex((call) => call.method === "PATCH");
    const dispatchIndex = calls.findIndex(
      (call) => call.method === "POST" && call.url.includes("/dispatch"),
    );
    expect(patchIndex).toBeGreaterThanOrEqual(0);
    expect(patchIndex).toBeLessThan(dispatchIndex);
    expect(calls[patchIndex].body).toMatchObject({
      operations: [
        {
          op: "replace",
          path: "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/storyboard_prompt",
          value: "新的分镜 Prompt",
        },
      ],
    });
  });

  it("switches the current video version through a slot selection patch", async () => {
    seedProject(withSecondVideoVersion());
    const updated = withSecondVideoVersion();
    updated.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = "r2v-window-v2";
    const calls = patchRoutes(updated);
    const { container } = renderWorkbench();

    fireEvent.click(
      container.querySelector('[data-artifact-version="r2v-window-v2"]')!,
    );
    expect(container.querySelector("video")).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/r2v-window-v2",
    );
    fireEvent.click(screen.getByRole("button", { name: "设为当前" }));
    await expectPatch(
      calls,
      "/assets/artifact_slots_by_id/element:r2v-window:video/selected_version_id",
      "r2v-window-v2",
    );
  });

  it("keeps the right rail to result and meta per the segment-editor design", async () => {
    installMockFetch([
      {
        match: "/models/resolved",
        response: {
          json: { video: { provider: "wan", model: "wan2.7-r2v" } },
        },
      },
      {
        match: "/r2v-references",
        response: {
          json: {
            elementId: "r2v-window",
            storyboardSelected: true,
            references: [
              {
                index: 1,
                versionId: "sb-window-v1",
                kind: "storyboard",
                name: "分镜图",
              },
              {
                index: 2,
                versionId: "cat-video-v1",
                kind: "source",
                name: "橘猫原始视频",
              },
            ],
          },
        },
      },
    ]);
    // 绑定一个还没生成设计图的道具：卡片必须以虚线占位形态出现。
    const project = cloneProject();
    project.visual.entities.order.push("lantern");
    project.visual.entities.items["lantern"] = {
      entity_id: "lantern",
      kind: "prop",
      name: "旧灯笼",
      description: "",
      continuity: "",
      required_variant_ids: [],
      variants: { order: [], items: {} },
      selected_artifact_version_id: null,
    };
    const r2vDraft =
      project.timelines.items["timeline:main"].elements_by_id["r2v-window"];
    if (r2vDraft.creation.type === "r2v")
      r2vDraft.creation.prop_refs = ["lantern"];
    seedProject(project);
    const { container } = renderWorkbench();

    // 右栏 = 生成结果 + 相关资产分组；阶段状态不再展示，旧的
    // 引用素材列表/资产绑定下拉也不回归（权威 [Image N] 只服务 prompt 胶囊）。
    expect(await screen.findByText("相关资产")).toBeInTheDocument();
    expect(screen.getByText("视频生成结果")).toBeInTheDocument();
    expect(screen.getByText("分镜图生成结果")).toBeInTheDocument();
    expect(screen.queryByText("阶段状态")).toBeNull();
    expect(screen.queryByText(/引用素材/)).toBeNull();
    expect(screen.queryByText("资产绑定")).toBeNull();
    // 添加入口只有标题行一个 +；空分类（场景/素材）不渲染分组。
    expect(container.querySelectorAll("[data-add-asset]")).toHaveLength(1);
    expect(container.querySelectorAll("[data-add-entity]")).toHaveLength(0);
    const rail = container.querySelector("[data-r2v-workbench] aside")!;
    expect(rail.textContent).not.toContain("场景");
    expect(rail.textContent).not.toContain("素材");
    // 已绑定的橘猫与灯笼卡可移除；未生成的灯笼是虚线占位卡（渲染「未生成」），
    // 已生成的卡不再标注「设计已完成」。
    expect(screen.getByText("圆润大橘猫")).toBeInTheDocument();
    expect(screen.getAllByLabelText("移除引用")).toHaveLength(2);
    expect(screen.getByText("旧灯笼")).toBeInTheDocument();
    expect(screen.getByText("未生成")).toBeInTheDocument();
    expect(screen.queryByText("设计已完成")).toBeNull();
    // 提示词卡固定引用预览（无原文切换），编辑胶囊在重新生成左侧。
    expect(screen.queryByText("编辑原文")).toBeNull();
    expect(screen.queryByText("引用预览")).toBeNull();
    const editPill = container.querySelector(
      '[data-prompt-edit="element:r2v-window/creation/storyboard_prompt"]',
    )!;
    expect(editPill.nextElementSibling).toHaveAttribute(
      "data-prompt-regenerate",
      "element:r2v-window/creation/storyboard_prompt",
    );
    expect(
      container.querySelectorAll(
        "[data-r2v-workbench] aside [role='combobox']",
      ),
    ).toHaveLength(0);
  });

  it("adds assets through the thumbnail asset picker", async () => {
    const calls = patchRoutes(cloneProject());
    const { container } = renderWorkbench();

    // 单一 + 打开缩略版资产库：分类筛选 + 已绑定项预选中。
    fireEvent.click(container.querySelector("[data-add-asset]")!);
    expect(await screen.findByText("添加相关资产")).toBeInTheDocument();
    expect(
      document.querySelector('[data-picker-asset="cat"]'),
    ).toBeInTheDocument();
    // 未做任何更改的确认必须是零改动：不产生 PATCH（顺序也不得被重排）。
    fireEvent.click(document.querySelector("[data-picker-confirm]")!);
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);

    // 点选素材候选（橘猫原始视频）并确认 → 一次性静默落盘。
    fireEvent.click(container.querySelector("[data-add-asset]")!);
    fireEvent.click(
      document.querySelector('[data-picker-asset="cat-video-v1"]')!,
    );
    fireEvent.click(document.querySelector("[data-picker-confirm]")!);
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PATCH")).toBe(true),
    );
    const operations = (
      calls.find((call) => call.method === "PATCH")!.body as {
        operations: Array<{ path: string; value?: unknown }>;
      }
    ).operations;
    expect(
      operations.some(
        (op) =>
          op.path ===
            "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/video_reference_version_ids" &&
          Array.isArray(op.value) &&
          (op.value as string[]).includes("cat-video-v1"),
      ),
    ).toBe(true);
  });

  it("removes a bound character from the rail and persists via CAS patch", async () => {
    const updated = cloneProject();
    const r2vElement =
      updated.timelines.items["timeline:main"].elements_by_id["r2v-window"];
    if (r2vElement.creation.type === "r2v") {
      r2vElement.creation.character_refs = [];
      r2vElement.creation.visual_variant_refs = {};
    }
    const calls = patchRoutes(updated);
    renderWorkbench();

    // 移除引用是离散动作 = 语义边界：点击后草稿直接静默落盘。
    fireEvent.click(screen.getByLabelText("移除引用"));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PATCH")).toBe(true),
    );
    const operations = (
      calls.find((call) => call.method === "PATCH")!.body as {
        operations: Array<{ path: string; value?: unknown }>;
      }
    ).operations;
    expect(
      operations.some(
        (op) =>
          op.path ===
            "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/character_refs" &&
          Array.isArray(op.value) &&
          op.value.length === 0,
      ),
    ).toBe(true);
  });
});
