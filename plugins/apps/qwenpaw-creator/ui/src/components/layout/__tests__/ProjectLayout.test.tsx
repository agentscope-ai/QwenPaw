import { RouterProvider, createMemoryRouter } from "react-router-dom";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { CREATOR_ROUTE_OBJECTS } from "@/app/router";
import type {
  FileProjectReviewRecord,
  ProjectDocument,
} from "@/contracts/creator";
import ProjectLayout from "@/components/layout/ProjectLayout";
import { NavigationRuntime } from "@/routing/navigation";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { projectDocument, status } from "@/test/creatorFixtures";
import { installMockFetch } from "@/test/mockFetch";

function cloneProject(): ProjectDocument {
  return structuredClone(projectDocument);
}

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

function commonRoutes(review?: FileProjectReviewRecord) {
  return [
    {
      match: "/projects/p1/runtime/reviews/active",
      response: review
        ? {
            json: [review],
            headers: { ETag: `"${review.decision_token}"` },
          }
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
    {
      match: "/projects/p1/conversations/c1/messages",
      response: { json: { items: [] } },
    },
    {
      match: "/projects/p1/specialist-runs",
      response: { json: { items: [] } },
    },
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
      response: {
        json: {
          session: {
            id: "s1",
            projectId: "p1",
            status: "IDLE",
            lastMessageSeq: 0,
            lastConsumedMessageSeq: 0,
            lastEventSeq: 0,
          },
          agentStatusBar: status,
        },
      },
    },
    { match: "/projects/p1/tasks", response: { json: { items: [] } } },
    {
      match: "/models/config",
      response: {
        json: {
          llm: { enabled: true, model_name: "qwen3.7-plus" },
          vlm: { enabled: true, model_name: "qwen3.7-plus", use_llm: true },
          image: { enabled: true, model_name: "qwen-image-2.0-pro" },
          video: { enabled: true, model_name: "wan2.7-r2v" },
        },
      },
    },
  ];
}

function elementReview(): FileProjectReviewRecord {
  return {
    review_id: "review-element-1",
    round_id: "round-element-1",
    request_id: "request-element-1",
    request_message_seq: 2,
    interrupted_run_id: "run-element-1",
    baseline_generation: 3,
    baseline_etag: "base-3",
    candidate_generation: 4,
    candidate_etag: "candidate-4",
    decision_token: "review-token-1",
    status: "PENDING",
    operations: [
      {
        kind: "update",
        json_pointer:
          "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/video_prompt",
        file_id: null,
        target_ref: "element:r2v-window",
        before_hash: "before",
        after_hash: "after",
        before: "旧 prompt",
        after: "新 prompt",
        operation_id: "operation-element-1",
        ui_locator: {
          page: "plan",
          mediaType: "text",
          elementId: "r2v-window",
          field:
            "/timelines/items/timeline:main/elements_by_id/r2v-window/creation/video_prompt",
        },
        decision: "PENDING",
      },
    ],
    created_at: "2026-07-20T00:00:00Z",
    updated_at: "2026-07-20T00:00:01Z",
  };
}

describe("ProjectLayout schema-v2 visible shell", () => {
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
    expect(screen.getAllByText("视频方案").length).toBeGreaterThanOrEqual(2);
    await waitFor(() =>
      expect(
        calls.filter((call) => call.url.endsWith("/projects/p1/project")),
      ).toHaveLength(1),
    );
    expect(calls.some((call) => call.url.endsWith("/projects/p1/header"))).toBe(
      false,
    );
    expect(calls.some((call) => call.url.endsWith("/projects/p1/plan"))).toBe(
      false,
    );
    expect(calls.some((call) => call.url.includes("/transactions/"))).toBe(
      false,
    );

    const shell = document.querySelector("[data-project-shell]")!;
    expect(shell).toHaveAttribute("data-top-nav-height", "58");
    // The Agent status bar was removed entirely; the shell no longer reserves
    // the 42px row.
    expect(shell).not.toHaveAttribute("data-agent-status-bar-height");
    expect(
      document.querySelector("[data-agent-status-bar]"),
    ).not.toBeInTheDocument();
    const dock = document.querySelector("[data-agent-dock]")!;
    expect(useAgentDockUiStore.getState().open).toBe(true);
    expect(dock).toHaveAttribute("data-agent-dock-width", "440");
    expect(dock).toHaveClass("relative", "h-full", "border-l");
    expect(dock).not.toHaveClass("fixed", "rounded-2xl");

    fireEvent.click(screen.getByRole("link", { name: "资产库" }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/project/p1/assets"),
    );

    rendered.unmount();
    expect(useFileProjectReviewStore.getState().projectId).toBeNull();
    expect(useFileProjectReviewStore.getState().polling).toBe(false);
  });

  it("keeps the active Outlet and AgentDock mounted during background snapshot sync and degradation", async () => {
    installMockFetch(commonRoutes());
    const router = createMemoryRouter(
      [
        {
          path: "/project/:id",
          element: <ProjectLayout />,
          children: [
            {
              path: "plan",
              element: (
                <div data-testid="active-project-route">Active route</div>
              ),
            },
          ],
        },
      ],
      { initialEntries: ["/project/p1/plan"] },
    );
    render(<RouterProvider router={router} />);

    expect(
      await screen.findByTestId("active-project-route"),
    ).toBeInTheDocument();
    const dock = document.querySelector("[data-agent-dock]");
    act(() =>
      useProjectSnapshotStore.setState({
        requestInFlight: true,
        syncStatus: "syncing",
      }),
    );
    expect(screen.getByTestId("active-project-route")).toBeInTheDocument();
    expect(document.querySelector("[data-agent-dock]")).toBe(dock);
    act(() =>
      useProjectSnapshotStore.setState({
        requestInFlight: false,
        syncStatus: "degraded",
        syncError: "瞬时重校验失败",
      }),
    );
    expect(screen.getByTestId("active-project-route")).toBeInTheDocument();
    expect(document.querySelector("[data-agent-dock]")).toBe(dock);
  });

  it("does not reset an already-open AgentDock when the same project shell mounts", async () => {
    useCreatorSessionStore.setState({
      projectId: "p1",
      session: {
        id: "s1",
        projectId: "p1",
        status: "IDLE",
        lastMessageSeq: 0,
        lastConsumedMessageSeq: 0,
        lastEventSeq: 0,
      },
      activeConversationId: "c1",
    });
    useAgentDockUiStore.getState().setOpen(true);
    useAgentDockUiStore.getState().setDraft("保留的输入");
    installMockFetch(commonRoutes());
    const router = createMemoryRouter(
      [
        {
          path: "/project/:id",
          element: <ProjectLayout />,
          children: [
            {
              path: "plan",
              element: <div data-testid="same-project-route">Same project</div>,
            },
          ],
        },
      ],
      { initialEntries: ["/project/p1/plan"] },
    );
    render(<RouterProvider router={router} />);

    expect(await screen.findByTestId("same-project-route")).toBeInTheDocument();
    expect(useAgentDockUiStore.getState().open).toBe(true);
    expect(useAgentDockUiStore.getState().draft).toBe("保留的输入");
  });

  it("navigates a completed file Review to the exact changed Element on the Plan page", async () => {
    const review = elementReview();
    installMockFetch(commonRoutes(review));
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
            {
              path: "plan",
              element: <div data-testid="review-plan-route">Plan</div>,
            },
          ],
        },
      ],
      { initialEntries: ["/project/p1/plan"] },
    );
    render(<RouterProvider router={router} />);
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
