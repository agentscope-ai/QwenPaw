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

function installTimelineRect(chart: Element) {
  Object.defineProperty(chart, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 1000,
      bottom: 280,
      width: 1000,
      height: 280,
      toJSON: () => ({}),
    }),
  });
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

  it("renders the canonical Timeline as categorized tracks and a start-sorted Element list", () => {
    const { container } = renderPage("/project/p1/plan?element=r2v-window");

    expect(screen.getByText("创作总纲")).toBeInTheDocument();
    expect(screen.getAllByText("20s").length).toBeGreaterThan(0);
    expect(screen.getByText("16:9")).toBeInTheDocument();
    expect(screen.getByText("6 项内容")).toBeInTheDocument();
    // The transition renders as a junction badge, and both fixture
    // overlays carry copy (styled captions stay captions), so the rows
    // are ai/clip/subtitle/audio = 4 tracks and no vertical scrolling is
    // needed.
    expect(screen.getByText(/4 轨/)).not.toHaveTextContent("可上下滚动");
    // Four lanes fit without the scroll viewport, so the capped
    // max-height wrapper must not be rendered.
    expect(container.querySelector('[class~="max-h-[320px]"]')).toBeNull();
    expect(screen.getAllByText("午饭名场面").length).toBeGreaterThan(0);
    expect(screen.getByText("分镜描述")).toBeInTheDocument();
    expect(screen.getByDisplayValue("暖色餐厅窗外的橘猫")).toBeInTheDocument();

    const chart = container.querySelector(
      "[data-timeline-chart]",
    ) as HTMLElement;
    vi.spyOn(chart, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      left: 0,
      top: 0,
      right: 600,
      bottom: 200,
      width: 600,
      height: 200,
      toJSON: () => ({}),
    });
    fireEvent.pointerDown(chart, { clientX: 100, clientY: 100, pointerId: 1 });
    fireEvent.pointerUp(chart, { clientX: 100, clientY: 100, pointerId: 1 });

    const listItems = [
      ...container.querySelectorAll("[data-element-list-item]"),
    ];
    expect(
      listItems
        .map((item) => item.getAttribute("data-element-list-item"))
        .slice(0, 2),
    ).toEqual(["edit-opening", "audio-bgm"]);
  });

  it("shows visual Variant and artifact coverage for referenced entities", () => {
    renderPage();

    expect(screen.getByText("视觉覆盖 1/1")).toBeInTheDocument();
    fireEvent.click(screen.getByText("视觉覆盖 1/1"));
    expect(screen.getByText("圆润大橘猫")).toBeInTheDocument();
    expect(screen.getByText("覆盖完成")).toBeInTheDocument();
    expect(screen.getByText(/使用中 · 1 个产物/)).toBeInTheDocument();
  });

  it("exposes ambiguous multi-Variant bindings before storyboard admission", () => {
    const project = cloneProject();
    const cat = project.visual.entities.items.cat;
    cat.variants.items["variant:cat:winter"] = {
      variant_id: "variant:cat:winter",
      requirements: "冬季围巾造型",
      prompt: "圆润大橘猫，佩戴红色围巾",
      reference_asset_version_ids: [],
      reference_artifact_version_ids: [],
      generated_artifact_version_ids: [],
      selected_artifact_version_id: null,
    };
    cat.variants.order.push("variant:cat:winter");
    cat.required_variant_ids.push("variant:cat:winter");
    const element =
      project.timelines.items["timeline:main"].elements_by_id["r2v-window"];
    if (element.creation.type !== "r2v") {
      throw new Error("fixture R2V Element missing");
    }
    element.creation.visual_variant_refs = {};
    seedProject(project);
    renderPage();

    expect(screen.getByText("视觉覆盖 0/1")).toBeInTheDocument();
    fireEvent.click(screen.getByText("视觉覆盖 0/1"));
    expect(screen.getByText("Element 未绑定 Variant")).toBeInTheDocument();
    expect(screen.getByText("1 个 Element 未指定 Variant")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "下载 / 导出" }),
    ).toBeInTheDocument();
  });

  it("exposes required Variant states that have not been materialized", () => {
    const project = cloneProject();
    project.visual.entities.items.cat.required_variant_ids.push(
      "variant:cat:winter",
    );
    seedProject(project);
    renderPage();

    expect(screen.getByText("视觉覆盖 0/1")).toBeInTheDocument();
    fireEvent.click(screen.getByText("视觉覆盖 0/1"));
    expect(screen.getByText("必需 Variant 尚未定义")).toBeInTheDocument();
    expect(screen.getByText("必需 Variant 1/2")).toBeInTheDocument();
    expect(screen.getByText("缺少：variant:cat:winter")).toBeInTheDocument();
  });

  it("keeps an empty Timeline guided through the Agent without an add-content button", () => {
    const project = cloneProject();
    project.timelines.items["timeline:main"].elements_by_id = {};
    seedProject(project);
    renderPage();

    expect(screen.getByText("时间轴中还没有内容")).toBeInTheDocument();
    expect(screen.getByText("时间轴还是空的")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "添加内容" }),
    ).not.toBeInTheDocument();
  });

  it("replaces the empty-Timeline hints with a live working state while the Agent runs", () => {
    const project = cloneProject();
    project.timelines.items["timeline:main"].elements_by_id = {};
    seedProject(project);
    useCreatorSessionStore.setState({
      projectId: "p1",
      session: {
        id: "cs-1",
        projectId: "p1",
        status: "RUNNING",
        lastMessageSeq: 0,
        lastConsumedMessageSeq: 0,
        lastEventSeq: 0,
      },
    });
    const { container } = renderPage();

    expect(screen.getByText("Agent 正在规划视频方案")).toBeInTheDocument();
    expect(screen.getByText("正在分析你的创作需求")).toBeInTheDocument();
    expect(
      container.querySelector("[data-timeline-working]"),
    ).toBeInTheDocument();
    expect(screen.queryByText("时间轴还是空的")).not.toBeInTheDocument();
    expect(screen.queryByText("时间轴中还没有内容")).not.toBeInTheDocument();

    // After the agent stops, fall back to the static guide instead of "pretending to work".
    act(() => {
      useCreatorSessionStore.setState((state) => ({
        session: state.session ? { ...state.session, status: "IDLE" } : null,
      }));
    });
    expect(screen.getByText("时间轴还是空的")).toBeInTheDocument();
    expect(
      screen.queryByText("Agent 正在规划视频方案"),
    ).not.toBeInTheDocument();
  });

  it("shows every active Element when a collapsed point is selected and can attach that point to AgentDock", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "收起时间轴" }));
    expect(
      screen.getByRole("button", { name: "展开时间轴" }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("紧凑时间轴概览；点击任意时刻查看同时出现的内容"),
    ).toBeInTheDocument();
    expect(
      container.querySelector("[data-element-block]"),
    ).not.toBeInTheDocument();
    const chart = container.querySelector("[data-timeline-chart]")!;
    installTimelineRect(chart);

    // 7.5s of a 20s Timeline. This point contains five overlapping Elements.
    const x = 80 + ((1000 - 92) * 7.5) / 20;
    fireEvent.pointerDown(chart, { pointerId: 1, clientX: x });
    fireEvent.pointerUp(chart, { pointerId: 1, clientX: x });

    expect(
      container.querySelector("[data-timeline-point-candidates]"),
    ).toBeInTheDocument();
    expect(
      container.querySelector("[data-timeline-point-candidates]")?.textContent,
    ).toContain("项内容");
    expect(
      container.querySelector("[data-timeline-point-candidates]")?.textContent,
    ).toContain("5");
    expect(chart.nextElementSibling).toBe(
      container.querySelector("[data-timeline-point-candidates]"),
    );
    expect(
      screen.getByRole("button", { name: "晨光到午后的转场" }),
    ).toBeInTheDocument();
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

  it("keeps collapsed point candidates clickable and scrolls the Element list to the chosen item", async () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "收起时间轴" }));
    const chart = container.querySelector("[data-timeline-chart]")!;
    installTimelineRect(chart);
    const x = 80 + ((1000 - 92) * 7.5) / 20;
    fireEvent.pointerDown(chart, { pointerId: 3, clientX: x });
    fireEvent.pointerUp(chart, { pointerId: 3, clientX: x });

    const list = container.querySelector(
      "[data-element-list]",
    ) as HTMLDivElement;
    const item = container.querySelector(
      '[data-element-list-item="transition"]',
    ) as HTMLButtonElement;
    Object.defineProperty(list, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        right: 300,
        top: 0,
        bottom: 120,
        width: 300,
        height: 120,
        x: 0,
        y: 0,
        toJSON: () => ({}),
      }),
    });
    Object.defineProperty(item, "getBoundingClientRect", {
      configurable: true,
      value: () => ({
        left: 0,
        right: 300,
        top: 420,
        bottom: 500,
        width: 300,
        height: 80,
        x: 0,
        y: 420,
        toJSON: () => ({}),
      }),
    });

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
    expect(list.scrollTop).toBeGreaterThan(0);
  });

  it("supports a dragged time range, then clears the range UI after adding it to the conversation", () => {
    const { container } = renderPage();
    const chart = container.querySelector("[data-timeline-chart]")!;
    installTimelineRect(chart);
    const x1 = 80 + ((1000 - 92) * 2) / 20;
    const x2 = 80 + ((1000 - 92) * 9) / 20;

    fireEvent.pointerDown(chart, { pointerId: 2, clientX: x1 });
    fireEvent.pointerMove(chart, { pointerId: 2, clientX: x2 });
    fireEvent.pointerUp(chart, { pointerId: 2, clientX: x2 });
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
  });

  it("reuses the shared playhead inside an Element and seeks to the exact start outside it", async () => {
    const { container } = renderPage();
    const chart = container.querySelector("[data-timeline-chart]")!;
    installTimelineRect(chart);
    const x = 80 + ((1000 - 92) * 7.5) / 20;

    fireEvent.pointerDown(chart, { pointerId: 4, clientX: x });
    fireEvent.pointerUp(chart, { pointerId: 4, clientX: x });

    const playhead = container.querySelector(
      "[data-timeline-playhead]",
    ) as HTMLDivElement;
    const playingPosition = playhead.style.left;
    expect(playingPosition).toContain("0.375");
    expect(
      document.querySelector("[data-timeline-selection-toolbar]"),
    ).toBeInTheDocument();

    // 7.5s is already inside r2v-window (5s–15s), so selecting it must not
    // rewind the video or create a second selection line.
    fireEvent.click(
      container.querySelector(
        '[data-element-block="r2v-window"]',
      ) as HTMLButtonElement,
    );
    await waitFor(() => expect(playhead.style.left).toBe(playingPosition));
    await waitFor(() =>
      expect(
        screen.getByRole("heading", { name: "午饭名场面" }),
      ).toBeInTheDocument(),
    );
    expect(
      document.querySelector("[data-timeline-selection-toolbar]"),
    ).not.toBeInTheDocument();

    // 7.5s is outside overlay-title (1s–6s), so the same playhead moves to its
    // exact start, never to a pre-roll position.
    fireEvent.click(
      container.querySelector(
        '[data-element-block="overlay-title"]',
      ) as HTMLButtonElement,
    );
    await waitFor(() =>
      expect(playhead.style.left).toBe("calc(68px + 0.05 * (100% - 68px))"),
    );
  });

  it("opens a large aspect-ratio-aware preview backed by the selected final Timeline artifact", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "视频预览" }));

    const preview = container.querySelector(
      "[data-timeline-video-preview]",
    ) as HTMLElement;
    expect(preview).toBeInTheDocument();
    expect(preview).toHaveClass("h-[clamp(220px,40vh,400px)]");
    expect(preview.closest("[data-timeline-panel]")).toHaveClass(
      "max-h-[66vh]",
    );
    expect(container.querySelector("[data-plan-page]")).toHaveClass(
      "h-full",
      "min-h-0",
      "overflow-y-auto",
    );
    expect(preview.querySelector("video")).toHaveClass("object-contain");
    expect(preview.querySelector("video")).toHaveAttribute(
      "src",
      "/api/qwenpaw-creator/media/artifacts/final-v1",
    );
    expect(screen.queryByText("Timeline 组合预览")).not.toBeInTheDocument();
  });

  it("defaults to the live assembled preview when no final render exists", () => {
    const project = cloneProject();
    delete project.assets.artifact_slots_by_id["timeline:timeline:main:render"];
    delete project.assets.artifact_versions_by_id["final-v1"];
    seedProject(project);
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "视频预览" }));

    expect(
      container.querySelector("[data-timeline-live-preview]"),
    ).toBeInTheDocument();
    expect(screen.queryByText("暂无成片预览")).not.toBeInTheDocument();
    expect(
      container.querySelector('[data-live-layer="edit-opening"]'),
    ).toHaveAttribute("src", "/api/qwenpaw-creator/media/assets/cat-video-v1");
    expect(
      container.querySelector("[data-preview-source-chip]"),
    ).toHaveTextContent("实时预览");
  });

  it("auto-selects the preview source without a user-facing mode toggle", () => {
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "视频预览" }));

    // Fresh final render exists → auto-play it; the source chip is read-only with no toggle button.
    expect(
      container.querySelector("[data-timeline-live-preview]"),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector("[data-timeline-video-preview] video"),
    ).toHaveAttribute("src", "/api/qwenpaw-creator/media/artifacts/final-v1");
    const chip = container.querySelector("[data-preview-source-chip]");
    expect(chip).toHaveTextContent("成片");
    expect(chip?.tagName).not.toBe("BUTTON");
    expect(chip?.querySelector("button")).toBeNull();
  });

  it("falls back to the live preview automatically when the final render is stale", () => {
    const project = cloneProject();
    project.assets.artifact_versions_by_id["final-v1"].stale = true;
    seedProject(project);
    const { container } = renderPage();
    fireEvent.click(screen.getByRole("button", { name: "视频预览" }));

    expect(
      container.querySelector("[data-timeline-live-preview]"),
    ).toBeInTheDocument();
    expect(
      container.querySelector("[data-preview-source-chip]"),
    ).toHaveTextContent("内容已更新 · 实时预览");
  });

  it("marks generating Elements on their timeline blocks", () => {
    const project = cloneProject();
    project.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = null;
    seedProject(project);
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
    const { container } = renderPage();

    const block = container.querySelector(
      '[data-element-block="r2v-window"]',
    ) as HTMLElement;
    expect(block).toHaveAttribute("data-element-block-state", "generating");
    expect(
      block.querySelector(".element-generating-stripes"),
    ).toBeInTheDocument();
    expect(
      container
        .querySelector('[data-element-block="edit-opening"]')
        ?.getAttribute("data-element-block-state"),
    ).toBe("ready");
  });

  it("projects the Element box from its anchor coordinates", () => {
    const { container } = renderPage("/project/p1/plan?element=overlay-os");
    const box = container.querySelector(
      "[data-element-location-box]",
    ) as HTMLElement;

    expect(box.style.left).toBe("51%");
    expect(box.style.top).toBe("61%");
    expect(box.style.width).toBe("42%");
    expect(box.style.height).toBe("18%");
    expect(screen.getByText("水平位置（%）")).toBeInTheDocument();
    expect(screen.getByText("垂直位置（%）")).toBeInTheDocument();
  });

  it("offers download for the fresh final render without triggering a new compose", async () => {
    const { calls } = installMockFetch([]);
    renderPage("/project/p1/plan?element=r2v-window");

    // Plan/continue-production shortcut buttons were removed; the Agent entry lives solely in AgentDock.
    expect(
      screen.queryByRole("button", { name: "Agent 规划" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "继续制作" }),
    ).not.toBeInTheDocument();

    // Fixture already has a fresh final render → no re-compose; the merged
    // entry opens a menu whose download item saves the file directly.
    const trigger = screen.getByRole("button", { name: "下载 / 导出" });
    fireEvent.click(trigger);
    const downloadItem = await screen.findByRole("menuitem", {
      name: /下载成片/,
    });
    expect(downloadItem).not.toHaveAttribute("aria-disabled", "true");
    expect(
      screen.getByRole("menuitem", { name: /导出项目/ }),
    ).toBeInTheDocument();
    const clickSpy = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    fireEvent.click(downloadItem);
    await waitFor(() => expect(clickSpy).toHaveBeenCalledTimes(1));
    clickSpy.mockRestore();
    expect(calls.some((call) => call.url.includes("/render"))).toBe(false);
    expect(calls.some((call) => call.url.includes("/commands"))).toBe(false);
  });

  it("auto-composes the final render once all compose elements are ready", async () => {
    vi.useFakeTimers();
    try {
      const project = cloneProject();
      delete project.assets.artifact_slots_by_id[
        "timeline:timeline:main:render"
      ];
      delete project.assets.artifact_versions_by_id["final-v1"];
      seedProject(project);
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
        {
          match: "/specialist-runs",
          response: { json: { items: [] } },
        },
        {
          match: "/tasks",
          response: { json: { items: [] } },
        },
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
      ]);
      renderPage();

      // All main-track elements ready and no final render → deterministic compose auto-triggers after a short debounce.
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

  it("adopts an existing compose task and shows verified Element counts", async () => {
    const project = cloneProject();
    delete project.assets.artifact_slots_by_id["timeline:timeline:main:render"];
    delete project.assets.artifact_versions_by_id["final-v1"];
    seedProject(project);
    const task = composeTask(0.4, "RUNNING", {
      completed: 4,
      total: 10,
    });
    useCreatorTaskViewStore.setState({
      projectId: "p1",
      tasks: [task],
    });
    const { calls } = installMockFetch([
      {
        match: "/specialist-runs",
        response: { json: { items: [] } },
      },
      {
        match: "/tasks",
        response: { json: { items: [task] } },
      },
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
    ]);
    const { container, unmount } = renderPage();

    expect(
      screen.getByRole("button", { name: "合成中 · 4/10" }),
    ).toBeInTheDocument();
    expect(container.querySelector("[data-compose-progress]")).toHaveStyle({
      width: "40%",
    });
    expect(screen.queryByText(/40%/)).not.toBeInTheDocument();
    expect(
      calls.some(
        (call) =>
          call.method === "POST" &&
          call.url.includes("/timelines/timeline%3Amain/render"),
      ),
    ).toBe(false);

    act(() => {
      useCreatorTaskViewStore.setState({
        tasks: [
          {
            ...task,
            progress: 0.7,
            completedElements: 7,
          },
        ],
      });
    });
    expect(
      screen.getByRole("button", { name: "合成中 · 7/10" }),
    ).toBeInTheDocument();
    expect(container.querySelector("[data-compose-progress]")).toHaveStyle({
      width: "70%",
    });
    expect(screen.queryByText(/70%/)).not.toBeInTheDocument();
    unmount();
  });

  it("shows zero completed Elements without inventing a percentage", () => {
    const project = cloneProject();
    delete project.assets.artifact_slots_by_id["timeline:timeline:main:render"];
    delete project.assets.artifact_versions_by_id["final-v1"];
    seedProject(project);
    const task = composeTask(0, "RUNNING", {
      completed: 0,
      total: 10,
    });
    useCreatorTaskViewStore.setState({
      projectId: "p1",
      tasks: [task],
    });
    installMockFetch([]);
    const { container, unmount } = renderPage();

    expect(
      screen.getByRole("button", { name: "合成中 · 0/10" }),
    ).toBeInTheDocument();
    expect(container.querySelector("[data-compose-progress]")).toHaveStyle({
      width: "0%",
    });
    // The zoom control legitimately shows "100%"; only the compose button must
    // avoid inventing a percentage.
    expect(
      screen.getByRole("button", { name: "合成中 · 0/10" }),
    ).not.toHaveTextContent(/%/);
    unmount();
  });

  it("keeps download disabled while any compose element is still not ready", async () => {
    const project = cloneProject();
    project.assets.artifact_slots_by_id[
      "element:r2v-window:video"
    ].selected_version_id = null;
    delete project.assets.artifact_slots_by_id["timeline:timeline:main:render"];
    delete project.assets.artifact_versions_by_id["final-v1"];
    seedProject(project);
    const { calls } = installMockFetch([]);
    renderPage();

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

  it("keeps the draft actions in the header immediately before the status tag", () => {
    const { container } = renderPage("/project/p1/plan?element=overlay-os");

    const actions = container.querySelector(
      "[data-element-detail-header-actions]",
    )!;
    const apply = screen.getByRole("button", { name: "应用修改" });
    const discard = screen.getByRole("button", { name: "放弃修改" });
    const status = actions.querySelector("[data-element-detail-status]")!;
    expect(
      screen.queryByRole("button", { name: "删除当前内容" }),
    ).not.toBeInTheDocument();
    expect(actions).toContainElement(discard);
    expect(actions).toContainElement(apply);
    expect(actions).toContainElement(
      screen.getByRole("button", { name: "关闭内容详情" }),
    );
    expect(discard).toBeDisabled();
    expect(apply).toBeDisabled();
    expect(
      apply.compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(container.querySelector("[data-element-detail] footer")).toBeNull();
  });

  it("keeps inner-OS text local until Apply and can discard it", () => {
    renderPage("/project/p1/plan?element=overlay-os");

    const copy = screen.getByDisplayValue("午饭在哪里？");
    fireEvent.change(copy, { target: { value: "罐头到底在哪里？" } });

    const authority =
      useProjectSnapshotStore.getState().project?.timelines.items[
        "timeline:main"
      ].elements_by_id["overlay-os"];
    expect(
      authority?.creation.type === "overlay" ? authority.creation.text : null,
    ).toBe("午饭在哪里？");
    expect(screen.getByRole("button", { name: "应用修改（1）" })).toBeEnabled();

    fireEvent.click(screen.getByRole("button", { name: "放弃修改" }));
    expect(screen.getByDisplayValue("午饭在哪里？")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "应用修改" })).toBeDisabled();
  });

  it("commits detail edits through the Project CAS Patch endpoint", async () => {
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
    renderPage("/project/p1/plan?element=r2v-window");

    const name = screen.getByDisplayValue("午饭名场面");
    fireEvent.change(name, { target: { value: "新的午饭名场面" } });
    fireEvent.blur(name);
    expect(calls.some((call) => call.method === "PATCH")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "应用修改（1）" }));
    await waitFor(() =>
      expect(calls.some((call) => call.method === "PATCH")).toBe(true),
    );
    const request = calls.find((call) => call.method === "PATCH")!;
    expect(request.url).toContain("/projects/p1/project");
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

  it("derives the playhead panel content from timeline + playheadTick", async () => {
    seedProject();
    renderPage();
    const header = () =>
      (screen.getByText(/^时间点:/).textContent ?? "").replace(/\s+/g, "");
    // 0s: the opening clip and BGM are active without any click.
    expect(header()).toContain("时间点:0s");
    const atZero = header();
    expect(atZero).not.toContain("0项内容");

    // Keyboard End moves the playhead; the panel must follow (this used to
    // keep showing the stale click-time list).
    fireEvent.keyDown(document.body, { key: "End" });
    await waitFor(() => expect(header()).toContain("时间点:20s"));
    expect(header()).toContain("0项内容");

    fireEvent.keyDown(document.body, { key: "Home" });
    await waitFor(() => expect(header()).toBe(atZero));
    // Rendered once on the track and once in the playhead content list.
    expect(screen.getAllByText("开场 · 晨光中的小猫")).toHaveLength(2);

    // A span edit landing in the snapshot re-derives the same panel: after
    // shrinking the opening clip to 0–3s, the 5s playhead no longer lists it.
    for (let step = 0; step < 5; step += 1) {
      fireEvent.keyDown(document.body, { key: "ArrowRight" });
    }
    await waitFor(() => expect(header()).toContain("时间点:5s"));
    expect(screen.getAllByText("开场 · 晨光中的小猫")).toHaveLength(2);
    act(() => {
      const project = cloneProject();
      project.timelines.items["timeline:main"].elements_by_id[
        "edit-opening"
      ].span.duration_tick = 3000;
      useProjectSnapshotStore.setState({ project });
    });
    // The track block stays; the stale entry leaves the playhead list.
    await waitFor(() =>
      expect(screen.getAllByText("开场 · 晨光中的小猫")).toHaveLength(1),
    );
  });

  it("drops an explicit selection as soon as the playhead moves", async () => {
    seedProject();
    const { container } = renderPage();
    const header = () =>
      (screen.getByText(/^(时间点:|已选择)/).textContent ?? "").replace(
        /\s+/g,
        "",
      );

    // Clicking a clip pins an explicit selection and seeks to its start.
    fireEvent.click(
      container.querySelector(
        '[data-element-block="r2v-window"]',
      ) as HTMLButtonElement,
    );
    await waitFor(() => expect(header()).toContain("已选择"));
    expect(header()).toContain("1项内容");

    // Home must clear the pinned list and re-derive 0s content — the panel
    // can never keep describing the previously clicked clip.
    fireEvent.keyDown(document.body, { key: "Home" });
    await waitFor(() => expect(header()).toContain("时间点:0s"));
    expect(header()).not.toContain("已选择");
    expect(header()).not.toContain("1项内容");
    expect(screen.getAllByText("开场 · 晨光中的小猫").length).toBeGreaterThan(
      1,
    );
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
    // The canvas summary always derives from the playhead (0s here).
    // #90 fixed the badge to one interpolated timeline.itemsCount
    // message, so the derived text is "0s·{count}项内容".
    const derivedAtZero = summary();
    expect(derivedAtZero).toContain("0s·");
    expect(derivedAtZero).toContain("2项内容");

    // Whole-lane click: pinned selection semantics, not "active at 0s".
    fireEvent.click(
      container.querySelector('[title*="点击选取整行"]') as HTMLElement,
    );
    await waitFor(() => expect(header()).toContain("已选择"));
    expect(header()).not.toContain("时间点");
    // The top summary must keep the derived playhead count on the same
    // screen — never adopt the pinned selection count.
    expect(summary()).toBe(derivedAtZero);
    const dot = document.querySelector('[title="已选择"]');
    expect(dot).toBeInTheDocument();
    expect(document.querySelector('[title="当前时刻活跃"]')).toBeNull();

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

    // Any playhead motion falls back to derived playhead content.
    fireEvent.keyDown(document.body, { key: "Home" });
    await waitFor(() => expect(header()).toContain("时间点:0s"));
    expect(summary()).toBe(derivedAtZero);
  });
});
