import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import DecisionTray from "@/components/agent/DecisionTray";
import type { FileProjectReviewRecord } from "@/contracts/creator";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useDecisionFocusStore } from "@/store/decisionFocusStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import {
  makePendingAuthorization,
  makeReviewOperation,
  makeReviewRecord,
} from "@/test/agentFixtures";

vi.mock("@/routing/locators", () => ({
  navigateToLocator: vi.fn(),
}));

const showBackendFeedback = vi.fn();
vi.mock("@/lib/creatorFeedback", () => ({
  showBackendFeedback: (...args: unknown[]) => showBackendFeedback(...args),
}));

vi.mock("@/api/creator", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/creator")>();
  return {
    ...actual,
    getArtifactVersionMediaUrl: (versionId: string) =>
      `https://media.test/${versionId}`,
  };
});

const pendingAuthorization = makePendingAuthorization({
  scope: { operation: "image_generation", message: "生成开场分镜图" },
});

const textReview = (reviewId: string, pointer: string) =>
  makeReviewRecord({
    review_id: reviewId,
    round_id: `round-${reviewId}`,
    decision_token: `token-${reviewId}`,
    operations: [
      makeReviewOperation({
        json_pointer: pointer,
        before: "旧文案",
        after: "新文案",
        operation_id: `operation-${reviewId}`,
        ui_locator: { page: "plan", mediaType: "text", field: pointer },
      }),
    ],
  });

function dockRect(height: number): DOMRect {
  return {
    height,
    width: 300,
    top: 0,
    left: 0,
    bottom: height,
    right: 300,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  } as DOMRect;
}

function seed({
  authorizations = [pendingAuthorization],
  reviews = [] as FileProjectReviewRecord[],
} = {}) {
  useExecutionAuthorizationStore.setState({
    projectId: "p1",
    items: authorizations,
    error: null,
  });
  useFileProjectReviewStore.setState({
    projectId: "p1",
    reviews,
    decisionInFlight: false,
  });
}

afterEach(() => {
  showBackendFeedback.mockClear();
  useAgentDockUiStore.getState().reset();
  useExecutionAuthorizationStore.getState().reset();
  useFileProjectReviewStore.getState().reset();
  useDecisionFocusStore.getState().clear();
});

describe("DecisionTray", () => {
  it("focuses the blocking authorization first, then steps to the review", () => {
    seed({ reviews: [textReview("review-1", "/description")] });
    render(<DecisionTray projectId="p1" />);

    // Blocking item focused first: only the confirmation card is expanded.
    expect(screen.getByText(/生成画面/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "创作修改 · 1 处" }),
    ).toHaveAttribute("title", expect.stringContaining("下一条"));
    expect(screen.queryByText(/旧文案/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "折叠决策托盘" }));
    expect(document.querySelector("[data-decision-tray]")).toHaveAttribute(
      "data-decision-tray-urgent",
      "true",
    );
    expect(screen.getByText(/生产确认 1 项阻塞执行中/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开决策托盘" }));

    fireEvent.click(screen.getByRole("button", { name: "下一条决策" }));
    expect(screen.getByText(/旧文案/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一条决策" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "上一条决策" })).toBeEnabled();
  });

  it("shows every pending card in list mode and filters by decision kind", () => {
    seed({
      reviews: [
        textReview("review-1", "/description"),
        textReview("review-2", "/title"),
      ],
    });
    render(<DecisionTray projectId="p1" />);

    fireEvent.click(screen.getByRole("button", { name: /列表/ }));
    expect(screen.getByText(/生成画面/)).toBeInTheDocument();
    expect(screen.getAllByText(/旧文案/)).toHaveLength(2);
    expect(screen.getByRole("button", { name: /堆叠/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /^审阅 2$/ }));
    expect(screen.queryByText(/生成画面/)).not.toBeInTheDocument();
    expect(screen.getAllByText(/旧文案/)).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: /^全部 3$/ }));
    expect(screen.getByText(/生成画面/)).toBeInTheDocument();
  });

  it("keeps earlier reviews when one batch keep fails and reports the exact tally", async () => {
    // v2.0.6 problem 1: a failure in the middle of "keep all" used to look
    // like the whole batch failed. Each review is isolated, and the toast
    // states what actually landed.
    seed({
      reviews: [
        textReview("review-1", "/description"),
        textReview("review-2", "/title"),
      ],
    });
    const decide = vi.fn(async (_projectId: string, reviewId: string) => {
      if (reviewId === "review-2") {
        throw new Error("审阅令牌已过期，请刷新后重试");
      }
      return undefined;
    });
    const pollOnce = vi.fn(async () => {});
    useFileProjectReviewStore.setState({
      decide: decide as never,
      pollOnce: pollOnce as never,
    });
    render(<DecisionTray projectId="p1" />);

    const keepAll = screen.getByRole("button", { name: "全部保留" });
    // F1/F2: the batch action uses the shared decision-button style.
    expect(keepAll).toHaveClass("btn-decision");
    fireEvent.click(keepAll);

    await waitFor(() => expect(showBackendFeedback).toHaveBeenCalled());
    expect(decide.mock.calls.map((call) => call[1])).toEqual([
      "review-1",
      "review-2",
    ]);
    // A failed keep refreshes decision tokens before the next review runs.
    expect(pollOnce).toHaveBeenCalledWith("p1");
    expect(showBackendFeedback).toHaveBeenCalledWith(
      "warning",
      "已保留 1 项，1 项失败：审阅令牌已过期，请刷新后重试",
      "部分审阅已保留",
    );
    // The failed review stays actionable for a second attempt.
    fireEvent.click(screen.getByRole("button", { name: /列表/ }));
    expect(
      document.querySelector('[data-file-project-review="review-2"]'),
    ).toBeInTheDocument();
  });

  it("reports a conflict when another tab decided the review first", async () => {
    // Another tab rejected the review; this tab's keep hits a CAS conflict
    // and its refresh no longer lists the item. Leaving the pending list is
    // not proof this decision applied, so "全部保留" must not claim a keep.
    seed({ reviews: [textReview("review-1", "/description")] });
    const decide = vi.fn(async () => {
      throw new Error("审阅令牌已过期，请刷新后重试");
    });
    const pollOnce = vi.fn(async () => {
      useFileProjectReviewStore.setState({ reviews: [] });
    });
    useFileProjectReviewStore.setState({
      decide: decide as never,
      pollOnce: pollOnce as never,
    });
    render(<DecisionTray projectId="p1" />);

    fireEvent.click(screen.getByRole("button", { name: "全部保留" }));

    await waitFor(() => expect(showBackendFeedback).toHaveBeenCalled());
    expect(showBackendFeedback).toHaveBeenCalledWith(
      "warning",
      "已保留 0 项，1 项失败：审阅令牌已过期，请刷新后重试",
      "部分审阅已保留",
    );
  });

  it("credits a keep only when the store confirmed the decision landed", async () => {
    // The response was lost after the server committed: the store's
    // reconciliation stamps the review before the rejection reaches here.
    seed({ reviews: [textReview("review-1", "/description")] });
    const decide = vi.fn(async () => {
      useFileProjectReviewStore.setState({
        reconciledDecision: {
          reviewId: "review-1",
          at: new Date().toISOString(),
        },
      });
      throw new Error("response lost");
    });
    const pollOnce = vi.fn(async () => {});
    useFileProjectReviewStore.setState({
      decide: decide as never,
      pollOnce: pollOnce as never,
    });
    render(<DecisionTray projectId="p1" />);

    fireEvent.click(screen.getByRole("button", { name: "全部保留" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "全部保留" })).toBeEnabled(),
    );
    expect(showBackendFeedback).not.toHaveBeenCalled();
  });

  it("hoists blocking reviews above the blocked authorization and focuses them", () => {
    seed({
      reviews: [
        textReview("review-1", "/description"),
        textReview("review-2", "/title"),
      ],
    });
    render(<DecisionTray projectId="p1" />);

    // Default ordering still puts the blocking authorization first.
    expect(document.querySelector("[data-decision-tray]")).toHaveAttribute(
      "data-decision-tray-focused",
      "auth:authorization-1",
    );

    fireEvent.click(screen.getByRole("button", { name: /列表/ }));
    act(() =>
      useDecisionFocusStore.getState().noteBlockingReviews(["review-2"]),
    );
    const hoisted = document.querySelector(
      '[data-file-project-review="review-2"]',
    );
    const auth = document.querySelector(
      '[data-execution-authorization-card="authorization-1"]',
    );
    expect(hoisted).not.toBeNull();
    expect(auth).not.toBeNull();
    expect(
      hoisted!.compareDocumentPosition(auth!) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // An explicit request focuses the blocking review and flashes the tray.
    act(() => useDecisionFocusStore.getState().focusReviews());
    expect(document.querySelector("[data-decision-tray]")).toHaveClass(
      "decision-tray-flash",
    );
    expect(document.querySelector("[data-decision-tray]")).toHaveAttribute(
      "data-decision-tray-focused",
      "review:review-2",
    );
    expect(
      screen.getByRole("button", { name: "折叠决策托盘" }),
    ).toBeInTheDocument();
  });

  it("drags the tray within [floor, feed slack], nudges by keyboard and resets on double click", () => {
    // The tray is bottom-anchored, so dragging its top edge UP grows it — the
    // mirror of the creation overview. Render inside a dock with a flex-growing
    // feed sibling so trayHeightBounds can measure real slack; the dragged
    // height lives in the dock UI store and is exposed as a CSS var that
    // globals.css turns into flex-basis.
    seed({
      authorizations: [],
      reviews: [textReview("review-1", "/description")],
    });
    const { container } = render(
      <div data-agent-dock>
        <DecisionTray projectId="p1" />
        <div data-feed style={{ flexGrow: 1 }} />
      </div>,
    );
    const dock = container.querySelector<HTMLElement>("[data-agent-dock]")!;
    const section = container.querySelector<HTMLElement>(
      "[data-decision-tray]",
    )!;
    Object.defineProperty(dock, "clientHeight", { value: 600 });
    vi.spyOn(section, "getBoundingClientRect").mockReturnValue(dockRect(160));
    vi.spyOn(
      container.querySelector<HTMLElement>("[data-feed]")!,
      "getBoundingClientRect",
    ).mockReturnValue(dockRect(300));
    const handle = () =>
      container.querySelector<HTMLElement>("[data-decision-tray-resize]");
    const stored = () => useAgentDockUiStore.getState().decisionTrayHeight;

    expect(section).not.toHaveAttribute("data-resized");
    expect(handle()).toHaveAttribute("role", "separator");

    // Bounds: floor 120 (TRAY_MIN_HEIGHT), ceiling 160 + 300 slack - 120 = 340.
    fireEvent.pointerDown(handle()!, { button: 0, clientY: 500 });
    fireEvent.pointerMove(window, { clientY: 400 });
    expect(stored()).toBe(260);
    expect(section).toHaveAttribute("data-resized", "true");
    expect(section.getAttribute("style")).toContain(
      "--decision-tray-height: 260px",
    );

    // Dragging far down collapses to the floor; far up clamps to the ceiling.
    fireEvent.pointerMove(window, { clientY: 1000 });
    expect(stored()).toBe(120);
    fireEvent.pointerMove(window, { clientY: 0 });
    expect(stored()).toBe(340);
    fireEvent.pointerUp(window);
    // After release the tray stops tracking the pointer.
    fireEvent.pointerMove(window, { clientY: 300 });
    expect(stored()).toBe(340);

    // Keyboard nudges from the current 160px section height (step 16): ArrowUp
    // grows the bottom-anchored tray, ArrowDown shrinks it.
    fireEvent.keyDown(handle()!, { key: "ArrowUp" });
    expect(stored()).toBe(176);
    fireEvent.keyDown(handle()!, { key: "ArrowDown" });
    expect(stored()).toBe(144);

    // Double-click clears the drag, restoring the automatic cap.
    fireEvent.doubleClick(handle()!);
    expect(stored()).toBeNull();
    expect(section).not.toHaveAttribute("data-resized");
  });
});
