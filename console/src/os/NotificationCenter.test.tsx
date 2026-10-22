// @vitest-environment jsdom
/**
 * NotificationCenter tests - the Desktop OS notification shell's
 * user-visible contract: which icon and which label each notification kind
 * gets, that approval banners keep their quick approve/deny actions while
 * inbox banners do not, that the approval command is sent with the id and
 * session taken from the item, that a rejected command surfaces the backend
 * message and KEEPS the banner actionable (the approval is still pending),
 * that a successful one drops it, that inbox banners auto dismiss on a timer
 * while approval banners never do, that clicking a banner records which Inbox
 * tab to open and survives an unavailable localStorage, and the Notification
 * Center panel's empty state, clear-all and close actions.
 *
 * Two environment facts drive the assertions here, both measured rather than
 * assumed:
 *   - formatTime() renders toLocaleTimeString(undefined, ...), so the exact
 *     string depends on the runtime locale and ICU data. Only its presence and
 *     shape are asserted, never a literal time.
 *   - CSS Modules hash the component's own class names, so nothing is queried
 *     by class. The lucide icons do carry stable classes, and those are used to
 *     tell the two notification kinds apart.
 *
 * Two guard arms stay uncovered, both measured (branch id and source line):
 *   - `NotificationCenter.tsx:56` branch id=3 hits [0, 6]: the route equality
 *     guard compares two module constants ("core.inbox" against "os.store"), so
 *     its then-arm never runs. The source itself comments it as never true.
 *   - `NotificationCenter.tsx:73` branch id=4 hits [0, 10]: the early return in
 *     the action handler needs a busy flag or a missing request id, but the
 *     buttons are disabled while busy and are not rendered at all without a
 *     request id, so no click can reach it. Both cases are asserted as the
 *     user-visible behaviour they produce instead.
 */
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";

const h = vi.hoisted(() => ({ send: vi.fn() }));

vi.mock("../api/modules/commands", () => ({
  commandsApi: { sendApprovalCommand: h.send },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) =>
      typeof fallback === "string" ? fallback : key,
  }),
}));

import NotificationCenter from "./NotificationCenter";
import { useOsNotify, type OsNotifyItem } from "./osNotifyStore";
import { useOsWindows } from "./osWindowStore";

const INBOX_TAB_KEY = "qwenpaw.inbox.activeTab";

function makeItem(overrides: Partial<OsNotifyItem> = {}): OsNotifyItem {
  return {
    id: "ap:req-1",
    kind: "approval",
    title: "Deploy request",
    body: "Someone asked to deploy",
    createdAt: 1700000000000,
    read: false,
    requestId: "req-1",
    rootSessionId: "sess-1",
    ...overrides,
  };
}

function inboxItem(overrides: Partial<OsNotifyItem> = {}): OsNotifyItem {
  return makeItem({
    id: "ib:evt-1",
    kind: "inbox",
    title: "Nightly report",
    body: "3 failures",
    requestId: undefined,
    rootSessionId: undefined,
    ...overrides,
  });
}

/**
 * The store is read through a hook subscription, so state must be in place
 * before render (or changed inside act) for the component to see it.
 */
function seedStore(state: {
  toasts?: OsNotifyItem[];
  history?: OsNotifyItem[];
  centerOpen?: boolean;
}) {
  useOsNotify.setState({
    history: state.history ?? [],
    toasts: state.toasts ?? [],
    approvalCount: 0,
    inboxCount: 0,
    centerOpen: state.centerOpen ?? false,
    seeded: true,
    knownIds: new Set<string>(),
  });
}

function approvalIconCount(): number {
  return document.querySelectorAll("svg.lucide-shield-alert").length;
}

function inboxIconCount(): number {
  return document.querySelectorAll("svg.lucide-inbox").length;
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  h.send.mockReset();
  h.send.mockResolvedValue({});
  window.localStorage.clear();
  seedStore({});
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("NotificationCenter - banners", () => {
  it("renders nothing when there are no banners and the panel is closed", () => {
    renderWithProviders(<NotificationCenter />);

    expect(document.querySelector('[role="status"]')).toBeNull();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("shows one banner per toast", () => {
    seedStore({ toasts: [makeItem(), inboxItem({ id: "ib:evt-2" })] });
    renderWithProviders(<NotificationCenter />);

    expect(document.querySelectorAll('[role="status"]')).toHaveLength(2);
  });

  it("gives an approval banner the shield icon and the Approval label", () => {
    seedStore({ toasts: [makeItem()] });
    renderWithProviders(<NotificationCenter />);

    expect(approvalIconCount()).toBe(1);
    expect(inboxIconCount()).toBe(0);
    // The kind label, the separator and the timestamp are sibling text nodes of
    // one meta row, so the label has to be matched as a prefix of that row.
    expect(screen.getByText(/^Approval/)).toBeInTheDocument();
    expect(screen.queryByText(/^Inbox/)).toBeNull();
  });

  it("gives an inbox banner the inbox icon and the Inbox label", () => {
    seedStore({ toasts: [inboxItem()] });
    renderWithProviders(<NotificationCenter />);

    expect(inboxIconCount()).toBe(1);
    expect(approvalIconCount()).toBe(0);
    expect(screen.getByText(/^Inbox/)).toBeInTheDocument();
    expect(screen.queryByText(/^Approval/)).toBeNull();
  });

  it("renders the title and body of the banner", () => {
    seedStore({
      toasts: [makeItem({ title: "Restart pod", body: "needs ok" })],
    });
    renderWithProviders(<NotificationCenter />);

    expect(screen.getByText("Restart pod")).toBeInTheDocument();
    expect(screen.getByText("needs ok")).toBeInTheDocument();
  });

  it("renders a timestamp next to the kind label without pinning the locale", () => {
    seedStore({ toasts: [makeItem()] });
    renderWithProviders(<NotificationCenter />);

    const banner = document.querySelector('[role="status"]') as HTMLElement;
    const text = banner.textContent ?? "";
    // The banner always carries "kind separator time"; only the shape is
    // asserted because the exact time string is locale and ICU dependent.
    expect(text).toContain("Approval");
    expect(text).toContain(" · ");
    expect(text.replace(/\s+/g, " ")).toMatch(/· \S+/);
  });
});

describe("NotificationCenter - approval actions", () => {
  it("offers approve and deny only when the item carries a request id", () => {
    seedStore({ toasts: [makeItem()] });
    renderWithProviders(<NotificationCenter />);

    expect(screen.getByText("Approve")).toBeInTheDocument();
    expect(screen.getByText("Deny")).toBeInTheDocument();
  });

  it("hides both actions for an approval item that lost its request id", () => {
    seedStore({ toasts: [makeItem({ requestId: undefined })] });
    renderWithProviders(<NotificationCenter />);

    expect(screen.queryByText("Approve")).toBeNull();
    expect(screen.queryByText("Deny")).toBeNull();
  });

  it("never offers actions on an inbox banner", () => {
    seedStore({ toasts: [inboxItem({ requestId: "should-not-render" })] });
    renderWithProviders(<NotificationCenter />);

    expect(screen.queryByText("Approve")).toBeNull();
    expect(screen.queryByText("Deny")).toBeNull();
  });

  it("sends the approve command with the id and session from the item", async () => {
    seedStore({
      toasts: [makeItem({ requestId: "r-7", rootSessionId: "s-9" })],
    });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Approve"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(h.send).toHaveBeenCalledTimes(1);
    expect(h.send).toHaveBeenCalledWith("approve", "r-7", "s-9");
  });

  it("sends the deny command and falls back to an empty session id", async () => {
    seedStore({
      toasts: [makeItem({ requestId: "r-8", rootSessionId: undefined })],
    });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Deny"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(h.send).toHaveBeenCalledWith("deny", "r-8", "");
  });

  it("drops the banner once the backend accepted the command", async () => {
    seedStore({ toasts: [makeItem({ id: "ap:gone" })] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Approve"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(useOsNotify.getState().toasts.map((t) => t.id)).not.toContain(
      "ap:gone",
    );
  });

  it("keeps the banner actionable when the command fails and shows the backend message", async () => {
    h.send.mockRejectedValue(new Error("gateway is down"));
    seedStore({ toasts: [makeItem({ id: "ap:stay" })] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Approve"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(useOsNotify.getState().toasts.map((t) => t.id)).toContain("ap:stay");
    expect(await screen.findByText("gateway is down")).toBeInTheDocument();
  });

  it("shows the generic fallback when the rejection is not an Error", async () => {
    h.send.mockRejectedValue("plain string failure");
    seedStore({ toasts: [makeItem()] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Deny"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(
      await screen.findByText("Action failed, please retry"),
    ).toBeInTheDocument();
  });

  it("disables both actions while a command is in flight", async () => {
    const gate = deferred<unknown>();
    h.send.mockReturnValue(gate.promise);
    seedStore({ toasts: [makeItem()] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Approve"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("Approve")).toBeDisabled();
    expect(screen.getByText("Deny")).toBeDisabled();

    // The disabled buttons swallow further clicks, so the command stays one.
    fireEvent.click(screen.getByText("Deny"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.send).toHaveBeenCalledTimes(1);

    // Settling the command drops the banner, so the actions go with it.
    await act(async () => {
      gate.resolve({});
      await Promise.resolve();
    });
    expect(screen.queryByText("Approve")).toBeNull();
    expect(useOsNotify.getState().toasts).toHaveLength(0);
  });

  it("re-enables both actions after a failure so the user can retry", async () => {
    h.send.mockRejectedValue(new Error("transient"));
    seedStore({ toasts: [makeItem()] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Approve"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText("Approve")).not.toBeDisabled();
    expect(screen.getByText("Deny")).not.toBeDisabled();

    h.send.mockResolvedValue({});
    fireEvent.click(screen.getByText("Deny"));
    await act(async () => {
      await Promise.resolve();
    });
    expect(h.send).toHaveBeenCalledTimes(2);
    expect(h.send).toHaveBeenLastCalledWith("deny", "req-1", "sess-1");
  });

  it("does not call the api at all when the item has no request id", async () => {
    seedStore({ toasts: [makeItem({ requestId: undefined })] });
    renderWithProviders(<NotificationCenter />);

    // No action buttons are rendered, so nothing can be clicked.
    expect(screen.queryByText("Approve")).toBeNull();
    expect(h.send).not.toHaveBeenCalled();
  });
});

describe("NotificationCenter - banner lifetime", () => {
  it("auto dismisses an inbox banner after the ttl", () => {
    vi.useFakeTimers();
    seedStore({ toasts: [inboxItem({ id: "ib:ttl" })] });
    renderWithProviders(<NotificationCenter />);

    expect(useOsNotify.getState().toasts).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(5999);
    });
    expect(useOsNotify.getState().toasts).toHaveLength(1);
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(useOsNotify.getState().toasts).toHaveLength(0);
  });

  it("never auto dismisses an approval banner", () => {
    vi.useFakeTimers();
    seedStore({ toasts: [makeItem({ id: "ap:persist" })] });
    renderWithProviders(<NotificationCenter />);

    act(() => {
      vi.advanceTimersByTime(600000);
    });
    expect(useOsNotify.getState().toasts.map((t) => t.id)).toContain(
      "ap:persist",
    );
  });

  it("cancels the pending timer when the banner unmounts", () => {
    vi.useFakeTimers();
    seedStore({ toasts: [inboxItem({ id: "ib:unmount" })] });
    const { unmount } = renderWithProviders(<NotificationCenter />);

    unmount();
    act(() => {
      vi.advanceTimersByTime(10000);
    });
    // The store was never touched again, so the item is still there.
    expect(useOsNotify.getState().toasts.map((t) => t.id)).toContain(
      "ib:unmount",
    );
  });
});

describe("NotificationCenter - opening the Inbox", () => {
  it("records the approvals tab and opens the inbox route for an approval", () => {
    const open = vi.fn();
    useOsWindows.setState({ open } as never);
    seedStore({ toasts: [makeItem()] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(document.querySelector('[role="status"]') as HTMLElement);

    expect(window.localStorage.getItem(INBOX_TAB_KEY)).toBe("approvals");
    expect(open).toHaveBeenCalledWith("core.inbox");
  });

  it("records the messages tab for an inbox notification", () => {
    const open = vi.fn();
    useOsWindows.setState({ open } as never);
    seedStore({ toasts: [inboxItem()] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(document.querySelector('[role="status"]') as HTMLElement);

    expect(window.localStorage.getItem(INBOX_TAB_KEY)).toBe("messages");
    expect(open).toHaveBeenCalledWith("core.inbox");
  });

  it("dismisses the banner when it is clicked", () => {
    useOsWindows.setState({ open: vi.fn() } as never);
    seedStore({ toasts: [inboxItem({ id: "ib:clicked" })] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(document.querySelector('[role="status"]') as HTMLElement);

    expect(useOsNotify.getState().toasts).toHaveLength(0);
  });

  it("still opens the inbox when localStorage is unavailable", () => {
    const open = vi.fn();
    useOsWindows.setState({ open } as never);
    const setItem = vi.mocked(window.localStorage.setItem);
    setItem.mockImplementationOnce(() => {
      throw new Error("storage disabled");
    });
    seedStore({ toasts: [inboxItem()] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(document.querySelector('[role="status"]') as HTMLElement);

    expect(open).toHaveBeenCalledWith("core.inbox");
    expect(useOsNotify.getState().toasts).toHaveLength(0);
  });

  it("dismisses the banner from its close button without opening the inbox", () => {
    const open = vi.fn();
    useOsWindows.setState({ open } as never);
    seedStore({ toasts: [inboxItem({ id: "ib:closed" })] });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByLabelText("Close"));

    expect(useOsNotify.getState().toasts).toHaveLength(0);
    expect(open).not.toHaveBeenCalled();
  });
});

describe("NotificationCenter - center panel", () => {
  it("is hidden while the center is closed", () => {
    seedStore({ history: [makeItem()], centerOpen: false });
    renderWithProviders(<NotificationCenter />);

    expect(document.querySelector('[role="dialog"]')).toBeNull();
  });

  it("shows the empty state when there is no history", () => {
    seedStore({ centerOpen: true });
    renderWithProviders(<NotificationCenter />);

    expect(screen.getByText("No notifications")).toBeInTheDocument();
  });

  it("lists every history item with its own icon", () => {
    seedStore({
      history: [makeItem(), inboxItem(), inboxItem({ id: "ib:evt-3" })],
      centerOpen: true,
    });
    renderWithProviders(<NotificationCenter />);

    expect(approvalIconCount()).toBe(1);
    expect(inboxIconCount()).toBe(2);
  });

  it("exposes the history item as a labelled button", () => {
    seedStore({
      history: [makeItem({ title: "Restart pod" })],
      centerOpen: true,
    });
    renderWithProviders(<NotificationCenter />);

    expect(
      screen.getByRole("button", { name: "Restart pod" }),
    ).toBeInTheDocument();
  });

  it("closes the panel and opens the inbox when a history item is activated", () => {
    const open = vi.fn();
    useOsWindows.setState({ open } as never);
    seedStore({ history: [inboxItem()], centerOpen: true });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByRole("button", { name: "Nightly report" }));

    expect(open).toHaveBeenCalledWith("core.inbox");
    expect(useOsNotify.getState().centerOpen).toBe(false);
  });

  it("activates the history item from the keyboard too", () => {
    const open = vi.fn();
    useOsWindows.setState({ open } as never);
    seedStore({ history: [inboxItem()], centerOpen: true });
    renderWithProviders(<NotificationCenter />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Nightly report" }), {
      key: "Enter",
    });

    expect(open).toHaveBeenCalledWith("core.inbox");
    expect(useOsNotify.getState().centerOpen).toBe(false);
  });

  it("ignores keys that are not activation keys", () => {
    const open = vi.fn();
    useOsWindows.setState({ open } as never);
    seedStore({ history: [inboxItem()], centerOpen: true });
    renderWithProviders(<NotificationCenter />);

    fireEvent.keyDown(screen.getByRole("button", { name: "Nightly report" }), {
      key: "a",
    });

    expect(open).not.toHaveBeenCalled();
    expect(useOsNotify.getState().centerOpen).toBe(true);
  });

  it("clears the whole history from the clear all button", () => {
    seedStore({ history: [makeItem(), inboxItem()], centerOpen: true });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByLabelText("Clear all"));

    expect(useOsNotify.getState().history).toHaveLength(0);
  });

  it("closes the panel from its own close button", () => {
    seedStore({ history: [makeItem()], centerOpen: true });
    renderWithProviders(<NotificationCenter />);

    const closeButtons = screen.getAllByLabelText("Close");
    fireEvent.click(closeButtons[closeButtons.length - 1]);

    expect(useOsNotify.getState().centerOpen).toBe(false);
  });

  it("offers quick actions on an approval item inside the panel", async () => {
    seedStore({
      history: [makeItem({ id: "ap:panel", requestId: "r-panel" })],
      centerOpen: true,
    });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Approve"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(h.send).toHaveBeenCalledWith("approve", "r-panel", "sess-1");
  });

  it("stops the action row from activating the surrounding history item", async () => {
    const open = vi.fn();
    useOsWindows.setState({ open } as never);
    seedStore({ history: [makeItem({ id: "ap:stop" })], centerOpen: true });
    renderWithProviders(<NotificationCenter />);

    fireEvent.click(screen.getByText("Approve"));
    await act(async () => {
      await Promise.resolve();
    });

    expect(h.send).toHaveBeenCalledTimes(1);
    expect(open).not.toHaveBeenCalled();
    expect(useOsNotify.getState().centerOpen).toBe(true);
  });
});
