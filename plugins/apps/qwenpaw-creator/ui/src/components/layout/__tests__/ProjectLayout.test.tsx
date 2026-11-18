import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CREATOR_ROUTE_OBJECTS } from "@/app/router";
import type { FileProjectReviewRecord } from "@/contracts/creator";
import ProjectLayout from "@/components/layout/ProjectLayout";
import { NavigationRuntime } from "@/routing/navigation";
import { navigateToLocator } from "@/routing/locators";
import { useNavigationStore } from "@/store/navigationStore";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import { useCreatorSessionStore } from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
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
    {
      match: "/projects/p1/work-graph",
      response: {
        json: {
          projectId: "p1",
          counts: {},
          nodes: [],
          generation: 0,
          mediaCalls: 0,
          mediaCallBudget: 20,
        },
      },
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

/** Mounts ProjectLayout with a stub workspace for all locator destinations. */
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
          { path: "*", element: <div data-testid={testId}>route</div> },
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
    useNavigationStore.getState().clear();
    seedProject();
  });

  it.each(["resolved", "rejected"])(
    "does not pile up authorization polls while a slow request is pending (%s)",
    async (outcome) => {
      installMockFetch(commonRoutes());
      let resolveRequest!: () => void;
      let rejectRequest!: (error: Error) => void;
      const pending = new Promise<void>((resolve, reject) => {
        resolveRequest = resolve;
        rejectRequest = reject;
      });
      const load = vi
        .spyOn(useExecutionAuthorizationStore.getState(), "load")
        .mockReturnValueOnce(pending)
        .mockResolvedValue();
      try {
        vi.useFakeTimers();
        await act(async () => {
          renderShell("slow-authorization-route");
        });
        expect(
          screen.getByTestId("slow-authorization-route"),
        ).toBeInTheDocument();
        await act(() => vi.advanceTimersByTimeAsync(12_000));
        act(() => {
          document.dispatchEvent(new Event("visibilitychange"));
          document.dispatchEvent(new Event("visibilitychange"));
        });
        expect(load).toHaveBeenCalledTimes(1);

        await act(async () => {
          if (outcome === "resolved") resolveRequest();
          else rejectRequest(new Error("temporary failure"));
          await pending.catch(() => undefined);
        });
        // The cadence now follows activity (5 s while nothing is pending), so
        // this waits past the idle interval. What is under test is that a slow
        // request never piles up and polling continues once it lands.
        await act(() => vi.advanceTimersByTimeAsync(6_000));
        expect(load).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
        load.mockRestore();
      }
    },
  );

  it("preserves the 58px shell and default-open 340px left AgentDock beside the Element Plan", async () => {
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
    expect(dock).toHaveAttribute("data-agent-dock-width", "340");

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

  it("settles a stale session after manual production finishes without lifecycle SSE", async () => {
    installMockFetch(commonRoutes());
    renderShell("manual-generation-route");
    await screen.findByTestId("manual-generation-route");
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().session?.status).toBe("IDLE"),
    );
    await waitFor(() =>
      expect(useCreatorTaskViewStore.getState().loading).toBe(false),
    );
    act(() => {
      useCreatorSessionStore.setState({
        session: { ...sessionState, status: "WAITING_RUNTIME" },
      });
    });
    // Returning to a visible tab performs the same production revalidation as
    // its periodic tick; the server has no running tasks and an IDLE session.
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().session?.status).toBe("IDLE"),
    );
    expect(document.querySelector("[data-agent-wait-hint]")).toBeNull();
  });

  it.each([
    "before completion",
    "while polling",
    "navigate away",
    "closed media banner",
  ])(
    "preserves manual navigation %s instead of opening the first Review item",
    async (timing) => {
      const review = elementReview();
      const secondPointer = changedPointer.replace(
        "video_prompt",
        "storyboard_prompt",
      );
      const secondLocator = {
        ...review.operations[0].ui_locator,
        field: secondPointer,
      };
      review.operations.push(
        makeReviewOperation({
          operation_id: "operation-2",
          json_pointer: secondPointer,
          target_ref: "element:r2v-window",
          ui_locator: secondLocator,
        }),
      );
      installMockFetch(commonRoutes(review));
      const router = renderShell("manual-review-route");
      await screen.findByTestId("manual-review-route");
      await waitFor(() =>
        expect(useFileProjectReviewStore.getState().reviews).toHaveLength(1),
      );
      const openSecond = () =>
        navigateToLocator(
          "p1",
          timing === "closed media banner"
            ? { page: "assets", assetId: "character-alice", versionId: "v1" }
            : secondLocator,
          {
            review: true,
            reviewId:
              timing === "closed media banner" ? review.review_id : undefined,
          },
        );
      if (timing === "before completion") act(openSecond);
      if (timing === "closed media banner") {
        act(openSecond);
        // The visible banner's close action clears navigation-stack state,
        // but the chosen media review remains open in the route.
        act(() => useNavigationStore.getState().clear());
      }

      let finishPoll!: () => void;
      const pendingPoll = new Promise<void>((resolve) => {
        finishPoll = resolve;
      });
      const poll = vi
        .spyOn(useFileProjectReviewStore.getState(), "pollOnce")
        .mockReturnValue(pendingPoll);
      try {
        act(() =>
          useCreatorSessionStore.getState().ingestEvents([
            {
              eventId: "run-with-review",
              seq: 1,
              type: "agent.run.completed",
              projectId: "p1",
              creatorSessionId: "s1",
              at: "now",
              data: {
                runId: "run-element-1",
                reviewIds: ["review-element-1"],
              },
            },
          ]),
        );
        await waitFor(() => expect(poll).toHaveBeenCalledTimes(1));
        if (timing === "while polling") act(openSecond);
        if (timing === "navigate away") {
          await act(() => router.navigate("/project/p1/plan?user=selected"));
        }
        const manualSearch = router.state.location.search;
        await act(async () => {
          finishPoll();
          await pendingPoll;
        });
        expect(poll).toHaveBeenCalledTimes(2);
        expect(router.state.location.search).toBe(manualSearch);
        if (timing === "closed media banner") {
          expect(new URLSearchParams(manualSearch).get("reviewId")).toBe(
            review.review_id,
          );
        } else if (timing !== "navigate away") {
          expect(new URLSearchParams(manualSearch).get("field")).toBe(
            secondPointer,
          );
        }
      } finally {
        poll.mockRestore();
      }
    },
  );
});
