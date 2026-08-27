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

    expect(screen.getByText("创作总纲")).toBeInTheDocument();
    expect(screen.getByText("6 项内容")).toBeInTheDocument();
    expect(screen.getByText(/4 轨/)).not.toHaveTextContent("可上下滚动");
    expect(screen.getAllByText("午饭名场面").length).toBeGreaterThan(0);
    expect(screen.getByText("分镜描述")).toBeInTheDocument();
    expect(screen.getByDisplayValue("暖色餐厅窗外的橘猫")).toBeInTheDocument();

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

  it("shows every active Element at a collapsed point, attaches it to AgentDock and keeps candidates clickable", async () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "收起时间轴" }));
    expect(
      container.querySelector("[data-element-block]"),
    ).not.toBeInTheDocument();
    const chart = container.querySelector("[data-timeline-chart]")!;
    installTimelineRect(chart);

    // 7.5s of a 20s Timeline. This point contains five overlapping Elements.
    const x = 80 + ((1000 - 92) * 7.5) / 20;
    fireEvent.pointerDown(chart, { pointerId: 1, clientX: x });
    fireEvent.pointerUp(chart, { pointerId: 1, clientX: x });

    const candidates = container.querySelector(
      "[data-timeline-point-candidates]",
    );
    expect(candidates).toBeInTheDocument();
    expect(candidates?.textContent).toContain("5");
    expect(
      screen.getByRole("button", { name: "晨光到午后的转场" }),
    ).toBeInTheDocument();

    // Candidates stay clickable and select the Element.
    const candidate = screen
      .getAllByRole("button", { name: "晨光到午后的转场" })
      .find((button) => !button.hasAttribute("data-element-block"))!;
    fireEvent.mouseDown(candidate);
    fireEvent.click(candidate);
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "晨光到午后的转场" }),
      ).toBeInTheDocument(),
    );

    // Re-selecting the point attaches it to AgentDock and clears the button.
    fireEvent.pointerDown(chart, { pointerId: 2, clientX: x });
    fireEvent.pointerUp(chart, { pointerId: 2, clientX: x });
    fireEvent.click(screen.getByRole("button", { name: "添加到对话" }));
    expect(useAgentDockUiStore.getState().selection).toMatchObject({
      kind: "timeline_point",
      timelineId: "timeline:main",
      startTick: 7500,
      endTick: 7500,
    });
    expect(useAgentDockUiStore.getState().selection?.elementIds).toHaveLength(
      5,
    );
    expect(
      screen.queryByRole("button", { name: "添加到对话" }),
    ).not.toBeInTheDocument();
  });

  it("auto-plays a fresh final render in an aspect-ratio-aware preview and downloads it without a new compose", async () => {
    const { calls } = installMockFetch([]);
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "视频预览" }));

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

    // The fresh render also downloads directly — no re-compose command fires.
    fireEvent.click(screen.getByRole("button", { name: "下载 / 导出" }));
    const downloadItem = await screen.findByRole("menuitem", {
      name: /下载成片/,
    });
    expect(downloadItem).not.toHaveAttribute("aria-disabled", "true");
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    fireEvent.click(downloadItem);
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    clickSpy.mockRestore();
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
    fireEvent.click(screen.getByRole("button", { name: "视频预览" }));

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
      expect(
        screen.getByRole("button", { name: "下载 / 导出" }),
      ).toHaveAttribute("title", "等待成片合成");
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

  it("marks generating Elements and keeps download disabled while any compose element is not ready", async () => {
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

    const trigger = screen.getByRole("button", { name: "下载 / 导出" });
    expect(trigger).toHaveAttribute(
      "title",
      expect.stringContaining("项内容生成中"),
    );
    // Only the download menu item is gated; export stays available.
    fireEvent.click(trigger);
    const downloadItem = await screen.findByRole("menuitem", {
      name: /下载成片/,
    });
    expect(downloadItem).toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByRole("menuitem", { name: /导出项目/ }),
    ).not.toHaveAttribute("aria-disabled", "true");
    expect(calls.some((call) => call.url.includes("/render"))).toBe(false);
  });

  it("derives the playhead panel content from timeline + playheadTick", async () => {
    seedProject();
    renderPage();
    const header = () =>
      (screen.getByText(/^时间点:/).textContent ?? "").replace(/\s+/g, "");
    expect(header()).toContain("时间点:0s");
    const atZero = header();
    expect(atZero).not.toContain("0项内容");

    // Keyboard End moves the playhead; the panel must follow (regression:
    // it used to keep showing the stale click-time list).
    fireEvent.keyDown(document.body, { key: "End" });
    await waitFor(() => expect(header()).toContain("时间点:20s"));
    expect(header()).toContain("0项内容");

    fireEvent.keyDown(document.body, { key: "Home" });
    await waitFor(() => expect(header()).toBe(atZero));
    // Rendered once on the track and once in the playhead content list.
    expect(screen.getAllByText("开场 · 晨光中的小猫")).toHaveLength(2);
  });

  it("labels lane and range selections as selections, never as playhead content", async () => {
    seedProject();
    const { container } = renderPage();
    const header = () =>
      (screen.getByText(/^(时间点:|已选择)/).textContent ?? "").replace(
        /\s+/g,
        "",
      );
    const summary = () =>
      (
        container.querySelector("[data-timeline-playhead-summary]")
          ?.textContent ?? ""
      ).replace(/\s+/g, "");
    // The canvas summary always derives from the playhead (0s here); #90
    // fixed the badge to one interpolated "0s·{count}项内容" message.
    const derivedAtZero = summary();
    expect(derivedAtZero).toContain("0s·");
    expect(derivedAtZero).toContain("2项内容");

    // Whole-lane click: pinned selection semantics, not "active at 0s".
    fireEvent.click(
      container.querySelector('[title*="点击选取整行"]') as HTMLElement,
    );
    await waitFor(() => expect(header()).toContain("已选择"));
    expect(header()).not.toContain("时间点");
    // The top summary must keep the derived playhead count — never adopt
    // the pinned selection count.
    expect(summary()).toBe(derivedAtZero);
    expect(document.querySelector('[title="已选择"]')).toBeInTheDocument();

    // Shift range selection keeps the same selection semantics.
    const chart = container.querySelector("[data-timeline-chart]")!;
    installTimelineRect(chart);
    const x1 = 80 + ((1000 - 92) * 2) / 20;
    const x2 = 80 + ((1000 - 92) * 9) / 20;
    fireEvent.pointerDown(chart, { pointerId: 9, clientX: x1, shiftKey: true });
    fireEvent.pointerMove(chart, { pointerId: 9, clientX: x2 });
    fireEvent.pointerUp(chart, { pointerId: 9, clientX: x2 });
    await waitFor(() => expect(header()).toContain("已选择"));
    expect(header()).not.toContain("时间点");
    expect(summary()).toBe(derivedAtZero);

    // The dragged range attaches to AgentDock and clears the range UI.
    fireEvent.click(screen.getByRole("button", { name: "添加到对话" }));
    expect(useAgentDockUiStore.getState().selection).toMatchObject({
      kind: "timeline_range",
      timelineId: "timeline:main",
      startTick: 2000,
      endTick: 9000,
    });
    expect(
      screen.queryByRole("button", { name: "添加到对话" }),
    ).not.toBeInTheDocument();

    // Any playhead motion falls back to derived playhead content.
    fireEvent.keyDown(document.body, { key: "Home" });
    await waitFor(() => expect(header()).toContain("时间点:0s"));
    expect(summary()).toBe(derivedAtZero);
  });
});
