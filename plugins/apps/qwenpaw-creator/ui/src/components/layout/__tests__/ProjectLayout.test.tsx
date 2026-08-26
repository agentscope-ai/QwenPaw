import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { CREATOR_ROUTE_OBJECTS } from "@/app/router";
import type { FileProjectReviewRecord } from "@/contracts/creator";
import ProjectLayout from "@/components/layout/ProjectLayout";
import { NavigationRuntime } from "@/routing/navigation";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import {
  configuredModelConfig,
  makeReviewOperation,
  makeReviewRecord,
} from "@/test/agentFixtures";
import { projectDocument, status } from "@/test/creatorFixtures";
import { installMockFetch } from "@/test/mockFetch";

const cloneProject = () => structuredClone(projectDocument);

function seedProject() {
  useProjectSnapshotStore.getState().reset("p1");
  useProjectSnapshotStore.setState({
    projectId: "p1",
    project: cloneProject(),
    generation: 3,
    etag: '"sha256:g3"',
    syncStatus: "healthy",
    syncError: null,
  });
}

const sessionState = {
  id: "s1",
  projectId: "p1",
  status: "IDLE",
  lastMessageSeq: 0,
  lastConsumedMessageSeq: 0,
  lastEventSeq: 0,
} as const;

function commonRoutes(review?: FileProjectReviewRecord) {
  return [
    {
      match: "/projects/p1/runtime/reviews/active",
      response: review
        ? { json: [review], headers: { ETag: `"${review.decision_token}"` } }
        : { status: 204 },
    },
    {
      match: "/projects/p1/project",
      response: {
        json: {
          projectId: "p1",
          generation: 3,
          etag: '"sha256:g3"',
          syncStatus: "healthy",
          project: cloneProject(),
        },
        headers: { ETag: '"sha256:g3"' },
      },
    },
    ...["conversations/c1/messages", "specialist-runs", "tasks"].map((p) => ({
      match: `/projects/p1/${p}`,
      response: { json: { items: [] } },
    })),
    {
      match: "/projects/p1/conversations",
      response: {
        json: {
          items: [
            {
              conversationId: "c1",
              title: "默认对话",
              isDefault: true,
              createdAt: "now",
            },
          ],
        },
      },
    },
    {
      match: "/projects/p1/session",
      response: { json: { session: sessionState, agentStatusBar: status } },
    },
    { match: "/models/config", response: { json: configuredModelConfig } },
  ];
}

const changedPointer =
  "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/video_prompt";

function elementReview() {
  return makeReviewRecord({
    review_id: "review-element-1",
    interrupted_run_id: "run-element-1",
    baseline_generation: 3,
    candidate_generation: 4,
    decision_token: "review-token-1",
    operations: [
      makeReviewOperation({
        json_pointer: changedPointer,
        target_ref: "element:r2v-window",
        ui_locator: {
          page: "plan",
          mediaType: "text",
          elementId: "r2v-window",
          field: changedPointer,
        },
      }),
    ],
  });
}

/** Mounts ProjectLayout with a stub /plan child route. */
function renderShell(testId: string) {
  const router = createMemoryRouter(
    [
      {
        path: "/project/:id",
        element: (
          <>
            <NavigationRuntime />
            <ProjectLayout />
          </>
        ),
        children: [
          { path: "plan", element: <div data-testid={testId}>route</div> },
        ],
      },
    ],
    { initialEntries: ["/project/p1/plan"] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

describe("ProjectLayout visible shell", () => {
  beforeEach(() => {
    useCreatorSessionStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    useCreatorInteractionStore.getState().reset();
    useProjectSnapshotStore.getState().reset();
    useFileProjectReviewStore.getState().reset();
    seedProject();
  });

  it("preserves the 58px shell and default-open 440px AgentDock beside the Element Plan", async () => {
    const { calls } = installMockFetch(commonRoutes());
    const router = createMemoryRouter(CREATOR_ROUTE_OBJECTS, {
      initialEntries: ["/project/p1/plan"],
    });
    const rendered = render(<RouterProvider router={router} />);

    expect(await screen.findByText("测试项目")).toBeInTheDocument();
    await waitFor(() =>
      expect(calls.filter((c) => c.url.endsWith("p1/project"))).toHaveLength(1),
    );
    for (const path of ["p1/header", "/transactions/"]) {
      expect(calls.some((call) => call.url.includes(path))).toBe(false);
    }

    const shell = document.querySelector("[data-project-shell]")!;
    expect(shell).toHaveAttribute("data-top-nav-height", "58");
    expect(shell).not.toHaveAttribute("data-agent-status-bar-height");
    const dock = document.querySelector("[data-agent-dock]")!;
    expect(useAgentDockUiStore.getState().open).toBe(true);
    expect(dock).toHaveAttribute("data-agent-dock-width", "440");

    rendered.unmount();
    expect(useFileProjectReviewStore.getState().projectId).toBeNull();
    expect(useFileProjectReviewStore.getState().polling).toBe(false);
  });

  it("navigates a completed file Review to the exact changed Element on the Plan page", async () => {
    installMockFetch(commonRoutes(elementReview()));
    const router = renderShell("review-plan-route");
    expect(await screen.findByTestId("review-plan-route")).toBeInTheDocument();

    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        {
          eventId: "run-with-review",
          seq: 1,
          type: "agent.run.completed",
          projectId: "p1",
          creatorSessionId: "s1",
          at: "now",
          data: { runId: "run-element-1", reviewIds: ["review-element-1"] },
        },
      ]),
    );

    await waitFor(() =>
      expect(router.state.location.search).toContain("element=r2v-window"),
    );
    expect(router.state.location.search).toContain("review=1");
    expect(router.state.location.search).toContain("field=");
    expect(useCreatorInteractionStore.getState().selectedRef).toBe(
      "element:r2v-window",
    );
  });
});
