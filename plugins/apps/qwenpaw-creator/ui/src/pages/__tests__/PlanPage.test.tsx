import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { act } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import PlanPage from "@/pages/PlanPage";
import { NavigationRuntime } from "@/routing/navigation";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { projectDocument } from "@/test/creatorFixtures";
import { installMockFetch } from "@/test/mockFetch";
import type { ProjectDocument, TaskView } from "@/contracts/creator";
import i18n from "@/i18n";

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

function seedWithoutFinal(project = cloneProject()) {
  delete project.assets.artifact_slots_by_id["timeline:timeline:main:render"];
  delete project.assets.artifact_versions_by_id["final-v1"];
  seedProject(project);
  return project;
}

function composeTask(
  progress: number,
  status: TaskView["status"] = "RUNNING",
  elementProgress?: { completed: number; total: number },
) {
  return {
    id: "task-compose",
    projectId: "p1",
    transactionId: null,
    specialistRunId: null,
    kind: "compose" as const,
    targetRef: "timeline:timeline:main",
    status,
    progress,
    completedElements: elementProgress?.completed ?? null,
    totalElements: elementProgress?.total ?? null,
    resultRefs: [],
    createdAt: "2026-07-20T00:00:00Z",
  } satisfies TaskView;
}

function pollRoutes(tasks: TaskView[] = []) {
  return [
    { match: "/specialist-runs", response: { json: { items: [] } } },
    { match: "/tasks", response: { json: { items: tasks } } },
    {
      match: "/projects/p1/project",
      response: {
        status: 304,
        headers: {
          ETag: '"sha256:g3"',
          "X-Project-Generation": "3",
          "X-Project-Sync-Status": "healthy",
        },
      },
    },
  ];
}

function renderPage(entry = "/project/p1/plan") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <NavigationRuntime />
      <Routes>
        <Route path="/project/:id/plan" element={<PlanPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const rectKeys = [
  "x",
  "y",
  "left",
  "top",
  "right",
  "bottom",
  "width",
  "height",
];
const baseRect = Object.fromEntries(rectKeys.map((key) => [key, 0]));

function stubRect(el: Element, rect: Record<string, number>) {
  Object.defineProperty(el, "getBoundingClientRect", {
    configurable: true,
    value: () => ({ ...baseRect, toJSON: () => ({}), ...rect }),
  });
}

function installTimelineRect(chart: Element) {
  stubRect(chart, { right: 1000, bottom: 280, width: 1000, height: 280 });
}

describe("PlanPage Timeline/Element frontend", () => {
  beforeEach(() => {
    useProjectSnapshotStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    useCreatorSessionStore.getState().reset();
    seedProject();
  });

  it("renders the canonical Timeline and commits detail edits through the Project CAS Patch endpoint", async () => {
    const updated = cloneProject();
    updated.generation = 4;
    updated.timelines.items["timeline:main"].elements_by_id[
      "r2v-window"
    ].label = "新的午饭名场面";
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
              "/timelines/items/timeline:main/elements_by_id/r2v-window/label",
            ],
            project: updated,
          },
        },
      },
    ]);
    const { container } = renderPage("/project/p1/plan?element=r2v-window");

    // The creative brief moved to the blueprint page; episode switching
    // lives in the workspace sidebar now, so the page itself shows the
    // timeline-title heading only.
    expect(screen.getAllByText("第1集 · 晨光出发").length).toBeGreaterThan(0);
    expect(screen.queryByText("创作总纲")).not.toBeInTheDocument();
    expect(screen.getByText("6 项内容")).toBeInTheDocument();
    expect(screen.getAllByText("午饭名场面").length).toBeGreaterThan(0);
    // 总览层：分镜/视频 Prompt 的全量编辑迁往制作台悬浮窗，详情保留创作语境字段。
    expect(screen.getByText("创作意图")).toBeInTheDocument();
    expect(screen.queryByText("分镜描述")).not.toBeInTheDocument();

    // Detail edits stay local on blur and commit via CAS Patch on Apply.
    const name = screen.getByDisplayValue("午饭名场面");
    fireEvent.change(name, { target: { value: "新的午饭名场面" } });
    fireEvent.blur(name);
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "应用修改（1）" }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PATCH")).toBe(true),
    );
    const request = calls.find((call) => call.method === "PATCH")!;
    expect(request.body).toMatchObject({
      baseGeneration: 3,
      baseEtag: '"sha256:g3"',
      editSessionId: "frontend:p1",
      operations: [
        {
          op: "replace",
          path: "/timelines/items/timeline:main/elements_by_id/r2v-window/label",
          value: "新的午饭名场面",
        },
      ],
    });
    expect(
      useProjectSnapshotStore.getState().project?.timelines.items[
        "timeline:main"
      ].elements_by_id["r2v-window"].label,
    ).toBe("新的午饭名场面");
  });

  it("moves the playhead from a chart click and opens a block's overview in the rail", async () => {
    const { container } = renderPage();
    const chart = container.querySelector("[data-timeline-chart]")!;
    installTimelineRect(chart);

    // 7.5s of a 20s Timeline: the transport timecode follows the click.
    const x = 80 + ((1000 - 92) * 7.5) / 20;
    fireEvent.pointerDown(chart, { pointerId: 1, clientX: x });
    fireEvent.pointerUp(chart, { pointerId: 1, clientX: x });
    await waitFor(() =>
      expect(
        container.querySelector("[data-timeline-timecode]")?.textContent,
      ).toContain("00:07.5"),
    );

    // Clicking a track block selects the element; its overview fills the
    // right rail (the element list panel no longer exists).
    const block = container.querySelector(
      '[data-element-block="edit-opening"]',
    ) as HTMLElement;
    fireEvent.click(block);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "开场 · 晨光中的小猫" }),
      ).toBeInTheDocument(),
    );
  });

  it("auto-plays a fresh final render in an aspect-ratio-aware preview and hosts the download/export entry", async () => {
    const { calls } = installMockFetch([]);
    const { container } = renderPage();

    const preview = container.querySelector(
      "[data-timeline-video-preview]",
    ) as HTMLElement;
    expect(preview.querySelector("video")).toHaveClass("object-contain");
    expect(preview.querySelector("video")).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/final-v1",
    );
    // Fresh final render → no live preview; the source chip is read-only.
    expect(
      container.querySelector("[data-timeline-live-preview]"),
    ).not.toBeInTheDocument();
    const chip = container.querySelector("[data-preview-source-chip]");
    expect(chip).toHaveTextContent("成片");
    expect(chip?.tagName).not.toBe("BUTTON");

    // The export home moved to the blueprint header (design 84:30317); the
    // plan header hosts 脚本方案 (drill-up) and 合成成片 instead, and rendering
    // never re-composes on mount.
    expect(
      screen.queryByRole("button", { name: "下载 / 导出" }),
    ).not.toBeInTheDocument();
    expect(container.querySelector("[data-open-blueprint]")).toHaveTextContent(
      "脚本方案",
    );
    expect(
      screen.getByRole("button", { name: "合成成片" }),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.url.includes("/render"))).toBe(false);
    expect(calls.some((call) => call.url.includes("/commands"))).toBe(false);
  });

  it.each<[string, () => void, string]>([
    ["no final render exists", () => void seedWithoutFinal(), "实时预览"],
    [
      "the final render is stale",
      () => {
        const project = cloneProject();
        project.assets.artifact_versions_by_id["final-v1"].stale = true;
        seedProject(project);
      },
      "内容已更新 · 实时预览",
    ],
  ])("falls back to the live preview when %s", (_name, seed, chip) => {
    seed();
    const { container } = renderPage();

    expect(
      container.querySelector("[data-timeline-live-preview]"),
    ).toBeInTheDocument();
    expect(
      container.querySelector('[data-live-layer="edit-opening"]'),
    ).toHaveAttribute("src", "/api/qwenpaw-creator/media/assets/cat-video-v1");
    expect(
      container.querySelector("[data-preview-source-chip]"),
    ).toHaveTextContent(chip);
  });

  it("auto-composes the final render once all compose elements are ready", async () => {
    vi.useFakeTimers();
    try {
      seedWithoutFinal();
      const { calls } = installMockFetch([
        {
          match: "/timelines/timeline%3Amain/render",
          method: "POST",
          response: {
            json: {
              ok: true,
              taskId: "task-render",
              artifactVersionId: "final-v2",
              generation: 4,
              etag: '"sha256:g4"',
              replayed: false,
            },
          },
        },
        ...pollRoutes(),
      ]);
      renderPage();

      // All main-track elements ready and no final render → auto-compose.
      expect(screen.getByRole("button", { name: "合成成片" })).toHaveAttribute(
        "title",
        "点击合成成片",
      );
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1600);
      });
      expect(
        calls.some(
          (call) =>
            call.method === "POST" &&
            call.url.includes("/timelines/timeline%3Amain/render"),
        ),
      ).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("adopts an existing compose task and shows verified Element counts without inventing a percentage", async () => {
    seedWithoutFinal();
    const task = composeTask(0, "RUNNING", { completed: 0, total: 10 });
    useCreatorTaskViewStore.setState({ projectId: "p1", tasks: [task] });
    const { calls } = installMockFetch(pollRoutes([task]));
    const { container, unmount } = renderPage();

    expect(
      screen.getByRole("button", { name: "合成中 · 0/10" }),
    ).toBeInTheDocument();
    expect(container.querySelector("[data-compose-progress]")).toHaveStyle({
      width: "0%",
    });
    expect(
      screen.getByRole("button", { name: "合成中 · 0/10" }),
    ).not.toHaveTextContent(/%/);
    expect(
      calls.some(
        (call) =>
          call.method === "POST" &&
          call.url.includes("/timelines/timeline%3Amain/render"),
      ),
    ).toBe(false);
    unmount();
  });

  it("marks generating Elements and keeps the export entry inert while content generates", async () => {
    const project = cloneProject();
    project.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = null;
    seedWithoutFinal(project);
    useCreatorTaskViewStore.setState({
      tasks: [
        {
          id: "task-r2v",
          projectId: "p1",
          transactionId: null,
          specialistRunId: null,
          kind: "r2v_generation",
          targetRef: "element:r2v-window",
          status: "RUNNING",
          progress: null,
          resultRefs: [],
          createdAt: "2026-07-20T00:00:00Z",
        },
      ],
    });
    const { calls } = installMockFetch([]);
    const { container } = renderPage();

    const block = container.querySelector(
      '[data-element-block="r2v-window"]',
    ) as HTMLElement;
    expect(block).toHaveAttribute("data-element-block-state", "generating");
    expect(
      block.querySelector(".element-generating-stripes"),
    ).toBeInTheDocument();

    // The plan header hosts 脚本方案 + 合成成片 (design 84:36801); the export
    // home moved to the blueprint, and nothing auto-fires while content is
    // still generating.
    expect(
      screen.queryByRole("button", { name: "下载 / 导出" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /脚本方案/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "合成成片" }),
    ).toBeInTheDocument();
    expect(calls.some((call) => call.url.includes("/render"))).toBe(false);
  });

  // The playhead content panel (ElementList) was removed by the redesign:
  // elements are selected directly on the bottom tracks (design 83:13383).
  it("attaches a dragged range selection to AgentDock", async () => {
    seedProject();
    const { container } = renderPage();
    const chart = container.querySelector("[data-timeline-chart]")!;
    installTimelineRect(chart);

    const x1 = 80 + ((1000 - 92) * 2) / 20;
    const x2 = 80 + ((1000 - 92) * 9) / 20;
    fireEvent.pointerDown(chart, { pointerId: 9, clientX: x1, shiftKey: true });
    fireEvent.pointerMove(chart, { pointerId: 9, clientX: x2 });
    fireEvent.pointerUp(chart, { pointerId: 9, clientX: x2 });

    // The dragged range attaches to AgentDock and clears the range UI.
    fireEvent.click(await screen.findByRole("button", { name: "添加到对话" }));
    expect(useAgentDockUiStore.getState().selection).toMatchObject({
      kind: "timeline_range",
      timelineId: "timeline:main",
      startTick: 2000,
      endTick: 9000,
    });
    expect(
      screen.queryByRole("button", { name: "添加到对话" }),
    ).not.toBeInTheDocument();
  });
});
