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
    lastGoodAt: "2026-07-20T00:02:00Z",
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
    // Default resolved-models mock so rendering the workbench never issues a
    // real network call; tests that assert on the value override this.
    installMockFetch([
      {
        match: "/models/resolved",
        response: {
          json: { video: { provider: "wan", model: "wan2.7-r2v" } },
        },
      },
    ]);
  });

  it("renders the origin/main workbench surfaces for an R2V Element", () => {
    const { container } = renderWorkbench();

    expect(
      screen.getByText("视频方案 / 午饭名场面 / 制作工作台"),
    ).toBeInTheDocument();
    expect(screen.getByText("Shot 列表（1）")).toBeInTheDocument();
    expect(screen.getByDisplayValue("橘猫隔窗看向午饭")).toBeInTheDocument();
    expect(screen.getByDisplayValue("暖色餐厅窗外的橘猫")).toBeInTheDocument();
    expect(
      screen.getByDisplayValue("镜头缓慢推近，橘猫眨眼"),
    ).toBeInTheDocument();
    expect(screen.getByText("视频结果")).toBeInTheDocument();
    expect(
      container.querySelector('[data-artifact-version="r2v-window-v1"]'),
    ).toBeInTheDocument();
    expect(container.querySelector("video")).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/r2v-window-v1",
    );
    expect(screen.getByText("@圆润大橘猫")).toBeInTheDocument();
    // Generated images owned by an already-referenced visual entity are no
    // longer duplicated as "materials", avoiding the semantic overlap between
    // "character" and "character anchor image".
    expect(screen.queryByText("@橘猫角色锚点")).toBeNull();
    expect(screen.getByText("资产绑定")).toBeInTheDocument();
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "element:r2v-window",
    );
  });

  it("shows the runtime-resolved video model instead of creation.recipe.model", async () => {
    installMockFetch([
      {
        match: "/models/resolved",
        response: {
          json: {
            video: { provider: "wan", model: "happyhorse-1.1-r2v" },
          },
        },
      },
    ]);
    renderWorkbench();

    await waitFor(() =>
      expect(screen.getByText("happyhorse-1.1-r2v")).toBeInTheDocument(),
    );
  });

  it("returns to the Plan page with the Element selected", async () => {
    renderWorkbench();

    fireEvent.click(screen.getByRole("button", { name: "返回视频方案" }));
    await waitFor(() =>
      expect(screen.getByText("创作总纲")).toBeInTheDocument(),
    );
    expect(screen.getByText("分镜描述")).toBeInTheDocument();
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

  it("opens the workbench from the Plan detail CTA of an R2V Element", async () => {
    render(
      <MemoryRouter initialEntries={["/project/p1/plan?element=r2v-window"]}>
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

    fireEvent.click(screen.getByRole("button", { name: "进入 R2V 工作台" }));
    await waitFor(() =>
      expect(
        screen.getByText("视频方案 / 午饭名场面 / 制作工作台"),
      ).toBeInTheDocument(),
    );
  });

  it("commits prompt edits through the schema-v2 Project CAS Patch endpoint", async () => {
    const updated = cloneProject();
    updated.generation = 4;
    const creation =
      updated.timelines.items["timeline:main"].elements_by_id["r2v-window"]
        .creation;
    if (creation.type === "r2v") creation.video_prompt = "镜头快速拉远";
    const { calls } = installMockFetch([
      {
        match: "/projects/p1/project",
        method: "PATCH",
        response: {
          json: {
            projectId: "p1",
            generation: 4,
            etag: '"sha256:g4"',
            changedPointers: [
              "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/video_prompt",
            ],
            project: updated,
          },
        },
      },
    ]);
    renderWorkbench();

    const prompt = screen.getByDisplayValue("镜头缓慢推近，橘猫眨眼");
    fireEvent.change(prompt, { target: { value: "镜头快速拉远" } });
    fireEvent.blur(prompt);
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "应用修改（1）" }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PATCH")).toBe(true),
    );
    const request = calls.find((call) => call.method === "PATCH")!;
    expect(request.body).toMatchObject({
      operations: [
        {
          op: "replace",
          path: "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/video_prompt",
          value: "镜头快速拉远",
        },
      ],
    });
  });

  it("commits shot edits through the schema-v2 Project CAS Patch endpoint", async () => {
    const updated = cloneProject();
    updated.generation = 4;
    const creation =
      updated.timelines.items["timeline:main"].elements_by_id["r2v-window"]
        .creation;
    if (creation.type === "r2v")
      creation.shots.items["shot:window"].description = "橘猫扒着窗台";
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
    renderWorkbench();

    const description = screen.getByDisplayValue("橘猫隔窗看向午饭");
    fireEvent.change(description, { target: { value: "橘猫扒着窗台" } });
    fireEvent.blur(description);
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "应用修改（1）" }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PATCH")).toBe(true),
    );
    const request = calls.find((call) => call.method === "PATCH")!;
    expect(request.body).toMatchObject({
      operations: [
        {
          op: "replace",
          path: "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/shots/items/shot:window/description",
          value: "橘猫扒着窗台",
        },
      ],
    });
  });

  it("switches the current video version through a slot selection patch", async () => {
    seedProject(withSecondVideoVersion());
    const updated = withSecondVideoVersion();
    updated.generation = 4;
    updated.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = "r2v-window-v2";
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
    const { container } = renderWorkbench();

    fireEvent.click(
      container.querySelector('[data-artifact-version="r2v-window-v2"]')!,
    );
    expect(container.querySelector("video")).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/r2v-window-v2",
    );
    expect(screen.getByText("可切换为当前视频版本")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "设为当前" }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PATCH")).toBe(true),
    );
    const request = calls.find((call) => call.method === "PATCH")!;
    expect(request.body).toMatchObject({
      operations: [
        {
          op: "replace",
          path: "/assets/artifact_slots_by_id/element:r2v-window:video/selected_version_id",
          value: "r2v-window-v2",
        },
      ],
    });
  });
});
