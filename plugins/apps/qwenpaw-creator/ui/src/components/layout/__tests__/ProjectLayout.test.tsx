import { RouterProvider, createMemoryRouter } from "react-router-dom";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CREATOR_ROUTE_OBJECTS } from "@/app/router";
import type { FileProjectReviewRecord } from "@/contracts/creator";
import { ev } from "@/test/sessionEventBuilders";
import ProjectLayout from "@/components/layout/ProjectLayout";
import { navigateToLocator } from "@/routing/locators";
import { useNavigationStore } from "@/store/navigationStore";
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
  seedCreatorSession,
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

function commonRoutes(review?: FileProjectReviewRecord, projectId = "p1") {
  return [
    {
      match: `/projects/${projectId}/runtime/reviews/active`,
      response: review
        ? { json: [review], headers: { ETag: `"${review.decision_token}"` } }
        : { status: 204 },
    },
    {
      match: `/projects/${projectId}/project`,
      response: {
        json: {
          projectId,
          generation: 3,
          etag: '"sha256:g3"',
          syncStatus: "healthy",
          project: { ...cloneProject(), project_id: projectId },
        },
        headers: { ETag: '"sha256:g3"' },
      },
    },
    ...["conversations/c1/messages", "specialist-runs", "tasks"].map((p) => ({
      match: `/projects/${projectId}/${p}`,
      response: { json: { items: [] } },
    })),
    {
      match: `/projects/${projectId}/conversations`,
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
      match: `/projects/${projectId}/session`,
      response: {
        json: {
          session: { ...sessionState, projectId },
          agentStatusBar: status,
        },
      },
    },
    {
      match: `/projects/${projectId}/work-graph`,
      response: {
        json: {
          projectId,
          counts: {},
          nodes: [],
          generation: 0,
          mediaCalls: 0,
          mediaCallBudget: 0,
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

/** Mounts the real ProjectLayout shell, whose WorkspaceSidebar owns AgentDock. */
function renderShellWithDock() {
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
          { path: "plan", element: <div data-testid="dock-plan-route" /> },
        ],
      },
    ],
    { initialEntries: ["/project/p1/plan"] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

const composerBox = () =>
  screen.getByRole("textbox", { name: "输入修改意图，@ 可引用对象…" });

describe("ProjectLayout visible shell", () => {
  beforeEach(() => {
    useCreatorSessionStore.getState().reset();
    useCreatorTaskViewStore.getState().reset();
    useAgentDockUiStore.getState().reset();
    useAgentDockUiStore.getState().clearUnsentDrafts();
    useCreatorInteractionStore.getState().reset();
    useProjectSnapshotStore.getState().reset();
    useFileProjectReviewStore.getState().reset();
    useNavigationStore.getState().clear();
    seedProject();
  });

  it("keeps the current project's reviews when a previous completion poll returns", async () => {
    const p2Review = {
      ...elementReview(),
      project_id: "p2",
      review_id: "p2-review",
    };
    const { fetchMock } = installMockFetch([
      ...commonRoutes(elementReview()),
      ...commonRoutes(p2Review, "p2"),
    ]);
    const router = renderShell("project-review-owner");
    await waitFor(() =>
      expect(useFileProjectReviewStore.getState().syncStatus).toBe("healthy"),
    );
    const fetch = fetchMock.getMockImplementation()!;
    let release!: () => void;
    const pending = new Promise<void>((resolve) => {
      release = resolve;
    });
    let p1Reads = 0;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/projects/p1/runtime/reviews/active")) {
        p1Reads++;
        await pending;
      }
      return fetch(input, init);
    });
    act(() =>
      useCreatorSessionStore.getState().ingestEvents([
        ev(1, "agent.run.completed", {
          runId: "finished",
          reviewIds: ["review-element-1"],
        }),
      ]),
    );
    await waitFor(() => expect(p1Reads).toBe(1));
    await act(() => router.navigate("/project/p2/plan"));
    await waitFor(() =>
      expect(useFileProjectReviewStore.getState().reviews[0]?.review_id).toBe(
        "p2-review",
      ),
    );
    await act(async () => {
      release();
      await pending;
    });
    expect(p1Reads).toBe(1);
    expect(useFileProjectReviewStore.getState().projectId).toBe("p2");
    expect(useFileProjectReviewStore.getState().reviews[0]?.review_id).toBe(
      "p2-review",
    );
    expect(router.state.location.pathname).toBe("/project/p2/plan");
    expect(router.state.location.search).toBe("");
  });

  it("ignores the replay tail for navigation and still handles a live completion", async () => {
    installMockFetch([
      {
        match: "/projects/p1/session",
        response: {
          json: {
            session: { ...sessionState, lastEventSeq: 5 },
            agentStatusBar: status,
          },
        },
      },
      ...commonRoutes(elementReview()),
    ]);
    const router = renderShell("replay-navigation");
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().replayUntilSeq).toBe(5),
    );
    await waitFor(() =>
      expect(useFileProjectReviewStore.getState().reviews).toHaveLength(1),
    );
    const completion = (seq: number) =>
      ev(seq, "agent.run.completed", {
        runId: "run-element-1",
        reviewIds: ["review-element-1"],
      });
    await act(async () =>
      useCreatorSessionStore.getState().ingestEvents([completion(5)]),
    );
    expect(useCreatorSessionStore.getState().isReplaying).toBe(false);
    expect(router.state.location.search).toBe("");
    await act(async () =>
      useCreatorSessionStore.getState().ingestEvents([completion(6)]),
    );
    await waitFor(() =>
      expect(router.state.location.search).toContain("review=1"),
    );
  });

  it("keeps discovering tasks while a graph poll is pending", async () => {
    const { calls, fetchMock } = installMockFetch(commonRoutes());
    renderShell("slow-graph");
    await waitFor(() =>
      expect(useCreatorSessionStore.getState().session).not.toBeNull(),
    );
    let finish!: () => void;
    const pending = new Promise<void>((resolve) => {
      finish = resolve;
    });
    const original = fetchMock.getMockImplementation()!;
    let graphFetches = 0;
    fetchMock.mockImplementation(async (input, init) => {
      if (String(input).endsWith("/work-graph")) {
        graphFetches++;
        await pending;
      }
      return original(input, init);
    });
    try {
      const count = () =>
        calls.filter((call) => call.url.endsWith("/tasks")).length;
      const initial = count();
      for (let i = 0; i < 3; i++)
        await act(async () => {
          document.dispatchEvent(new Event("visibilitychange"));
        });
      expect(count()).toBe(initial + 3);
      expect(graphFetches).toBe(1);
    } finally {
      await act(async () => finish());
    }
  });

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

  it("keeps a Project draft across the layout reset on a Project switch", async () => {
    seedCreatorSession();
    installMockFetch([...commonRoutes(), ...commonRoutes(undefined, "p2")]);
    const router = renderShellWithDock();
    const box = await screen.findByRole("textbox", {
      name: "输入修改意图，@ 可引用对象…",
    });
    fireEvent.input(box, { target: { textContent: "Draft for p1" } });

    await act(() => router.navigate("/project/p2/plan"));

    // The layout resets the dock on every Project switch; the draft parked by
    // the outgoing composer must survive that reset for the return trip.
    await waitFor(() =>
      expect(useAgentDockUiStore.getState().unsentDrafts).toEqual({
        p1: ["Draft for p1"],
      }),
    );
    expect(useAgentDockUiStore.getState().open).toBe(true);

    await act(() => router.navigate("/project/p1/plan"));
    await waitFor(() => expect(composerBox().textContent).toBe("Draft for p1"));
  });

  it("keeps both Project drafts across an A → B → A → B round trip", async () => {
    seedCreatorSession();
    installMockFetch([...commonRoutes(), ...commonRoutes(undefined, "p2")]);
    const router = renderShellWithDock();
    await screen.findByRole("textbox", {
      name: "输入修改意图，@ 可引用对象…",
    });
    fireEvent.input(composerBox(), { target: { textContent: "Draft A" } });

    await act(() => router.navigate("/project/p2/plan"));
    await waitFor(() => expect(composerBox().textContent ?? "").toBe(""));
    fireEvent.input(composerBox(), { target: { textContent: "Draft B" } });

    await act(() => router.navigate("/project/p1/plan"));
    await waitFor(() => expect(composerBox().textContent).toBe("Draft A"));
    // Restoring A consumed only A: B must still be parked for its own return.
    expect(useAgentDockUiStore.getState().unsentDrafts).toEqual({
      p2: ["Draft B"],
    });

    await act(() => router.navigate("/project/p2/plan"));
    await waitFor(() => expect(composerBox().textContent).toBe("Draft B"));
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
