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
    expect(screen.getByText("@圆润大橘猫")).toBeInTheDocument();
    // Images owned by an already-referenced visual entity must not be
    // duplicated as "materials".
    expect(screen.queryByText("@橘猫角色锚点")).toBeNull();
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "element:r2v-window",
    );
  });

  it("shows the runtime-resolved video model instead of creation.recipe.model", async () => {
    installMockFetch(modelRoutes("happyhorse-1.1-r2v"));
    renderWorkbench();

    expect(await screen.findByText("happyhorse-1.1-r2v")).toBeInTheDocument();
  });

  it("round-trips between the Plan detail CTA and the workbench", async () => {
    renderWorkbench("/project/p1/plan?element=r2v-window");

    fireEvent.click(
      screen.getByRole("button", { name: /进入制作工作台（参考生视频）/ }),
    );
    await waitFor(() =>
      expect(
        screen.getByText(/视频方案 \/ 午饭名场面 \/ 制作工作台/),
      ).toBeInTheDocument(),
    );

    fireEvent.click(screen.getByRole("button", { name: "返回视频方案" }));
    await waitFor(() =>
      expect(screen.getByText("创作总纲")).toBeInTheDocument(),
    );
    expect(screen.getByDisplayValue("暖色餐厅窗外的橘猫")).toBeInTheDocument();
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
    "commits %s edits through the Project CAS Patch endpoint",
    async (_field, current, next, path) => {
      const calls = patchRoutes(cloneProject());
      renderWorkbench();

      const input = screen.getByDisplayValue(current);
      fireEvent.change(input, { target: { value: next } });
      fireEvent.blur(input);
      // Blur alone stages the edit; only the explicit apply commits it.
      expect(calls.some((call) => call.method === "PATCH")).toBe(false);
      fireEvent.click(screen.getByRole("button", { name: "应用修改（1）" }));
      await expectPatch(calls, path, next);
    },
  );

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

  it("numbers references authoritatively, refs by kind, and drops stale numbering on dirty drafts", async () => {
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
    renderWorkbench();

    // The [Image N] badges follow the backend preview, and clicking a row
    // selects the kind-correct ref (sources are asset versions).
    await screen.findByText("[Image 1]");
    fireEvent.click(screen.getByText("@橘猫原始视频").closest("button")!);
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "asset-version:cat-video-v1",
    );
    fireEvent.click(screen.getByText("@分镜图").closest("button")!);
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "artifact-version:sb-window-v1",
    );

    // A dirty draft invalidates the committed numbering until Apply: the
    // stale badges disappear and the pending-apply notice takes over.
    fireEvent.change(screen.getByDisplayValue("镜头缓慢推近，橘猫眨眼"), {
      target: { value: "镜头快速推近" },
    });
    await waitFor(() => expect(screen.queryByText("[Image 1]")).toBeNull());
    expect(screen.getByText(/权威序号将在应用更改后更新/)).toBeInTheDocument();
  });
});
