// @vitest-environment jsdom
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingApproval } from "../api/modules/console";
import { ApprovalProvider } from "../contexts/ApprovalContext";
import type { ApprovalNotificationTarget } from "../notifications/approvalNavigation";
import { useOsNotify } from "./osNotifyStore";
import { useOsRoute } from "./osRouteStore";
import { useOsWindows } from "./osWindowStore";
import DesktopPollingServices from "./DesktopPollingServices";

const mocks = vi.hoisted(() => ({
  getInboxEvents: vi.fn(),
  getPushMessages: vi.fn(),
  native: false,
  subscribeDesktop: vi.fn(),
  listeners: new Map<
    string,
    (event: { payload?: ApprovalNotificationTarget }) => void
  >(),
}));

vi.mock("../tauri/backendRuntime", () => ({
  isDesktopApp: () => mocks.native,
}));

vi.mock("../tauri/consoleNotifications", () => ({
  subscribeDesktopConsolePush: mocks.subscribeDesktop,
  configureDesktopApprovalNotifications: vi.fn(async () => undefined),
}));

vi.mock("@tauri-apps/api/event", () => ({
  listen: vi.fn(
    async (
      name: string,
      handler: (event: { payload?: ApprovalNotificationTarget }) => void,
    ) => {
      mocks.listeners.set(name, handler);
      return () => mocks.listeners.delete(name);
    },
  ),
}));

vi.mock("../api", () => ({
  default: {
    getInboxEvents: mocks.getInboxEvents,
  },
}));

vi.mock("../api/modules/console", () => ({
  consoleApi: {
    getPushMessages: mocks.getPushMessages,
  },
}));

const approval = (): PendingApproval =>
  ({
    request_id: "approval-1",
    session_id: "session-1",
    root_session_id: "session-1",
    agent_id: "agent-1",
    tool_name: "execute_shell_command",
    severity: "info",
    findings_count: 0,
    findings_summary: "Review command",
    tool_params: {},
    created_at: 1,
  }) as PendingApproval;

const setVisibility = (state: "visible" | "hidden") => {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  Object.defineProperty(document, "hidden", {
    configurable: true,
    get: () => state === "hidden",
  });
};

const advance = async (ms: number) => {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
};

describe("DesktopPollingServices", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setVisibility("visible");
    mocks.native = false;
    mocks.listeners.clear();
    mocks.subscribeDesktop.mockReset().mockResolvedValue(() => undefined);
    mocks.getPushMessages.mockReset();
    mocks.getInboxEvents.mockReset();
    mocks.getPushMessages.mockResolvedValue({
      messages: [],
      pending_approvals: [approval()],
    });
    mocks.getInboxEvents.mockResolvedValue({
      events: [],
      unread_count: 3,
    });
    useOsNotify.setState({
      history: [],
      toasts: [],
      approvalCount: 0,
      inboxCount: 0,
      centerOpen: false,
      seeded: false,
      knownIds: new Set<string>(),
    });
    useOsRoute.setState({ targets: {} });
    useOsWindows.setState({
      windows: {},
      order: [],
      activeId: null,
      saved: {},
    });
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
    setVisibility("visible");
  });

  it("keeps one push owner while Desktop OS consumes shared approvals", async () => {
    const view = render(
      <ApprovalProvider>
        <DesktopPollingServices />
      </ApprovalProvider>,
    );

    await advance(0);
    expect(useOsNotify.getState()).toMatchObject({
      approvalCount: 1,
      inboxCount: 3,
    });
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(1);
    expect(mocks.getInboxEvents).toHaveBeenCalledTimes(1);

    await advance(12000);
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(5);
    expect(mocks.getInboxEvents).toHaveBeenCalledTimes(2);

    setVisibility("hidden");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await advance(30000);
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(6);
    expect(mocks.getInboxEvents).toHaveBeenCalledTimes(2);

    setVisibility("visible");
    act(() => document.dispatchEvent(new Event("visibilitychange")));
    await advance(0);
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(7);
    expect(mocks.getInboxEvents).toHaveBeenCalledTimes(3);

    view.unmount();
    const pushCalls = mocks.getPushMessages.mock.calls.length;
    const inboxCalls = mocks.getInboxEvents.mock.calls.length;
    await advance(60000);
    expect(mocks.getPushMessages).toHaveBeenCalledTimes(pushCalls);
    expect(mocks.getInboxEvents).toHaveBeenCalledTimes(inboxCalls);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("restores the chat app and preserves the native notification target", async () => {
    mocks.native = true;
    const view = render(
      <ApprovalProvider>
        <DesktopPollingServices />
      </ApprovalProvider>,
    );
    await advance(0);
    useOsWindows.getState().open("core.chat");
    useOsWindows.getState().minimize("core.chat");

    const target = {
      requestId: "approval/1",
      rootSessionId: "session-1",
      agentId: "agent-1",
    };
    act(() => {
      mocks.listeners.get("qwenpaw:open-approval")?.({ payload: target });
    });
    expect(useOsRoute.getState().targets["core.chat"]).toEqual({
      path: "/chat/session-1?approval=approval%2F1&agent=agent-1",
      nonce: 1,
    });
    expect(useOsWindows.getState().activeId).toBe("core.chat");
    expect(useOsWindows.getState().windows["core.chat"].minimized).toBe(false);

    act(() => {
      mocks.listeners.get("qwenpaw:open-approval")?.({ payload: target });
    });
    expect(useOsRoute.getState().targets["core.chat"].nonce).toBe(2);
    view.unmount();
    expect(mocks.listeners.size).toBe(0);
  });

  it.each([
    ["qwenpaw:open-approvals", undefined],
    ["qwenpaw:open-approval", { requestId: "approval-1" }],
  ])(
    "opens Inbox approvals for %s without a source chat",
    async (name, target) => {
      mocks.native = true;
      const view = render(
        <ApprovalProvider>
          <DesktopPollingServices />
        </ApprovalProvider>,
      );
      await advance(0);

      act(() => {
        mocks.listeners.get(name)?.({ payload: target });
      });
      expect(useOsRoute.getState().targets["core.inbox"]?.path).toBe(
        "/inbox?tab=approvals",
      );
      expect(useOsWindows.getState().activeId).toBe("core.inbox");
      view.unmount();
    },
  );
});
