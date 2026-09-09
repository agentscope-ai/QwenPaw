import { fireEvent, render, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { ConfigProvider } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import AgentProgressOverview from "@/components/agent/AgentProgressOverview";
import R2VWorkbenchPage from "@/pages/R2VWorkbenchPage";
import AssetsPage from "@/pages/AssetsPage";
import PlanPage from "@/pages/PlanPage";
import { NavigationRuntime } from "@/routing/navigation";
import { findCreatorFieldElement } from "@/routing/reviewFocus";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useWorkGraphStore } from "@/store/workGraphStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useNavigationStore } from "@/store/navigationStore";
import { projectDocument } from "@/test/creatorFixtures";
import { installMockFetch } from "@/test/mockFetch";
import type { WorkGraphNode } from "@/contracts/creator";

const timelineId = "timeline:second";
const elementId = "r2v-window";
const base = `/timelines/items/${timelineId}/elements_by_id/${elementId}/creation`;
function LocationProbe() {
  const location = useLocation();
  return (
    <output data-location>
      {location.pathname}
      {location.search}
    </output>
  );
}
function operation(
  kind: WorkGraphNode["kind"],
  id = `${kind}:${elementId}`,
): WorkGraphNode {
  return {
    id,
    kind,
    timelineId,
    label: "private label",
    lane: "private lane",
    status: "done",
    deps: [],
    missing: [],
    taskId: null,
    progress: null,
    error: null,
    dispatchable: false,
    locator: { page: "plan", elementId },
  };
}

describe("overview operation clicks reach the actual generation field", () => {
  beforeEach(() => {
    useProjectSnapshotStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useFileProjectReviewStore.getState().reset();
    useWorkGraphStore.getState().reset();
    useExecutionAuthorizationStore.getState().reset();
    useNavigationStore.getState().clear();
    Element.prototype.scrollIntoView = vi.fn();
    const project = structuredClone(projectDocument);
    const timeline = structuredClone(project.timelines.items["timeline:main"]);
    timeline.timeline_id = timelineId;
    timeline.title = "第二集";
    const creation = timeline.elements_by_id[elementId].creation;
    if (creation.type === "r2v") {
      creation.storyboard_prompt = "第二集专用分镜提示词";
      creation.video_prompt = "第二集专用视频提示词";
    }
    project.timelines.items[timelineId] = timeline;
    project.timelines.order.push(timelineId);
    useProjectSnapshotStore.setState({
      projectId: "p1",
      project,
      generation: project.generation,
      syncStatus: "healthy",
      etag: "test",
    });
    useWorkGraphStore.setState({
      projectId: "p1",
      graph: {
        projectId: "p1",
        generation: project.generation,
        nodes: [operation("storyboard"), operation("video")],
        counts: { done: 2 },
        mediaCalls: 0,
        mediaCallBudget: 10,
      },
    });
    installMockFetch([
      {
        match: "/models/resolved",
        response: {
          json: { video: { provider: "wan", model: "wan3.0-video-prime" } },
        },
      },
    ]);
  });

  function renderOverview(entry = "/project/p1/assets") {
    return render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <MemoryRouter initialEntries={[entry]}>
          <NavigationRuntime />
          <LocationProbe />
          <aside>
            <AgentProgressOverview projectId="p1" />
          </aside>
          <main data-creator-workspace-root>
            <Routes>
              <Route path="/project/:id/assets" element={<AssetsPage />} />
              <Route
                path="/project/:id/t/:timelineId/plan"
                element={<PlanPage />}
              />
              <Route
                path="/project/:id/t/:timelineId/plan/element/:elementId"
                element={<R2VWorkbenchPage />}
              />
            </Routes>
          </main>
        </MemoryRouter>
      </ConfigProvider>,
    );
  }

  function clickOperation(container: HTMLElement, kind: string) {
    const row = Array.from(
      container.querySelectorAll<HTMLElement>("[data-node-id]"),
    ).find((item) => item.dataset.nodeId === `${kind}:${elementId}`)!;
    fireEvent.click(within(row).getByRole("button"));
  }

  it("clicks storyboard/video/storyboard on the second episode, switches the real tab and scrolls its exact prompt without entering review", async () => {
    const { container } = renderOverview();
    for (const kind of ["storyboard", "video", "storyboard"]) {
      clickOperation(container, kind);
      const field = `${base}/${kind}_prompt`;
      await waitFor(() => {
        const target = findCreatorFieldElement(
          field,
          container.querySelector("main")!,
        );
        expect(target).not.toBeNull();
        expect(target).toHaveClass("review-flash");
        expect(target).toHaveTextContent(
          kind === "storyboard"
            ? "第二集专用分镜提示词"
            : "第二集专用视频提示词",
        );
      });
      const location = container.querySelector("[data-location]")!.textContent!;
      expect(location).toContain(
        `/t/${encodeURIComponent(timelineId)}/plan/element/${elementId}`,
      );
      const query = new URLSearchParams(location.split("?")[1]);
      expect(query.get("field")).toBe(field);
      expect(query.get("focusField")).toBe("1");
      expect(query.has("review")).toBe(false);
      expect(useCreatorInteractionStore.getState().selectedRef).toBe(
        `element:${elementId}`,
      );
    }
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });
});
