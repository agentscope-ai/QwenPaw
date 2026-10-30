import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { PendingApproval } from "../api/modules/console";
import { BrowserApprovalNotifier } from "./browserApprovals";
import { setNotificationsEnabled } from "./preferences";

const shown: TestNotification[] = [];

class TestNotification {
  static permission: NotificationPermission = "granted";
  onclick: (() => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn(() => this.onclose?.());
  title: string;
  options: NotificationOptions;
  constructor(title: string, options: NotificationOptions) {
    this.title = title;
    this.options = options;
    shown.push(this);
  }
}

function approval(id = "approval-1", over: Partial<PendingApproval> = {}) {
  return {
    request_id: id,
    tool_name: "execute_shell_command",
    tool_display_name: "Bash",
    created_at: Date.now() / 1000,
    timeout_seconds: 300,
    tool_params: { command: "pwd" },
    ...over,
  } as PendingApproval;
}

function setHidden(hidden: boolean) {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: hidden,
  });
}

const flush = async () => {
  await Promise.resolve();
  await vi.advanceTimersByTimeAsync(0);
  await Promise.resolve();
};

describe("browser approval notifications", () => {
  const notifiers: BrowserApprovalNotifier[] = [];
  const openInbox = vi.fn();
  function create() {
    const notifier = new BrowserApprovalNotifier(
      () => ({ title: "Approval required", body: (tool) => `Review ${tool}` }),
      openInbox,
    );
    notifiers.push(notifier);
    return notifier;
  }

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-29T08:00:00Z"));
    localStorage.clear();
    shown.length = 0;
    openInbox.mockReset();
    TestNotification.permission = "granted";
    vi.stubGlobal("Notification", TestNotification);
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    vi.spyOn(window, "focus").mockImplementation(() => undefined);
    setHidden(true);
    setNotificationsEnabled(true);
  });

  afterEach(() => {
    for (const notifier of notifiers.splice(0)) notifier.dispose();
    vi.useRealTimers();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    setHidden(false);
  });

  it("seeds the first successful snapshot without notifying existing approvals", async () => {
    const notifier = create();
    notifier.update([approval()]);
    await flush();
    expect(shown).toHaveLength(0);
    notifier.update([approval(), approval("new")]);
    await flush();
    expect(shown).toHaveLength(1);
    expect(shown[0].options.tag).toBe("qwenpaw-approval:new");
  });

  it("notifies once for a new approval and does not expose its command arguments", async () => {
    const notifier = create();
    notifier.update([]);
    notifier.update([approval()]);
    await flush();
    notifier.update([approval()]);
    await flush();
    expect(shown).toHaveLength(1);
    expect(shown[0].options.body).toBe("Review Bash");
    expect(shown[0].options.body).not.toContain("pwd");
  });

  it.each(["default", "denied"] as const)(
    "does not notify with permission %s",
    async (permission) => {
      TestNotification.permission = permission;
      const notifier = create();
      notifier.update([]);
      notifier.update([approval()]);
      await flush();
      expect(shown).toHaveLength(0);
    },
  );

  it("does not notify when disabled or when the page is focused", async () => {
    const notifier = create();
    notifier.update([]);
    setNotificationsEnabled(false);
    notifier.update([approval("disabled")]);
    await flush();
    setNotificationsEnabled(true);
    setHidden(false);
    vi.mocked(document.hasFocus).mockReturnValue(true);
    notifier.update([approval("focused")]);
    await flush();
    expect(shown).toHaveLength(0);
  });

  it("notifies while the tab is visible but another application has focus", async () => {
    setHidden(false);
    const notifier = create();
    notifier.update([]);
    notifier.update([approval()]);
    await flush();
    expect(shown).toHaveLength(1);
  });

  it("notifies an approval that arrived while focused once focus is lost", async () => {
    setHidden(false);
    vi.mocked(document.hasFocus).mockReturnValue(true);
    const notifier = create();
    notifier.update([]);
    notifier.update([approval()]);
    await flush();
    expect(shown).toHaveLength(0);

    vi.mocked(document.hasFocus).mockReturnValue(false);
    setHidden(true);
    document.dispatchEvent(new Event("visibilitychange"));
    await flush();

    expect(shown).toHaveLength(1);
    notifier.update([approval()]);
    await flush();
    expect(shown).toHaveLength(1);
  });

  it("retries after a temporarily disabled delivery", async () => {
    const notifier = create();
    notifier.update([]);
    setNotificationsEnabled(false);
    notifier.update([approval()]);
    await flush();
    expect(shown).toHaveLength(0);

    setNotificationsEnabled(true);
    notifier.update([approval()]);
    await flush();
    expect(shown).toHaveLength(1);
  });

  it("ignores approvals that have already expired", async () => {
    const notifier = create();
    notifier.update([]);
    notifier.update([approval("old", { created_at: Date.now() / 1000 - 301 })]);
    await flush();
    expect(shown).toHaveLength(0);
  });

  it("closes a notification when the approval disappears", async () => {
    const notifier = create();
    notifier.update([]);
    notifier.update([approval()]);
    await flush();
    notifier.update([]);
    expect(shown[0].close).toHaveBeenCalledTimes(1);
  });

  it("closes a notification at its approval deadline even without another snapshot", async () => {
    const notifier = create();
    notifier.update([]);
    notifier.update([approval("short", { timeout_seconds: 3 })]);
    await flush();
    await vi.advanceTimersByTimeAsync(3000);
    expect(shown[0].close).toHaveBeenCalledTimes(1);
  });

  it("focuses the page and opens current approvals when a notification is clicked", async () => {
    const notifier = create();
    notifier.update([]);
    notifier.update([approval()]);
    await flush();
    shown[0].onclick?.();
    expect(window.focus).toHaveBeenCalledOnce();
    expect(openInbox).toHaveBeenCalledOnce();
    expect(shown[0].close).toHaveBeenCalledOnce();
  });

  it("deduplicates the same approval across two browser consumers", async () => {
    const first = create();
    const second = create();
    first.update([]);
    second.update([]);
    first.update([approval()]);
    second.update([approval()]);
    await flush();
    expect(shown).toHaveLength(1);
  });

  it("does not send a queued notification after the setting is disabled", async () => {
    const notifier = create();
    notifier.update([]);
    notifier.update([approval()]);
    setNotificationsEnabled(false);
    await flush();
    expect(shown).toHaveLength(0);
  });

  it("does not send queued notifications after disposal", async () => {
    const notifier = create();
    notifier.update([]);
    notifier.update([approval()]);
    notifier.dispose();
    await flush();
    expect(shown).toHaveLength(0);
  });

  it("closes all active notifications when disposed", async () => {
    const notifier = create();
    notifier.update([]);
    notifier.update([approval("one"), approval("two")]);
    await flush();
    notifier.dispose();
    expect(shown).toHaveLength(2);
    expect(
      shown.every((notification) => notification.close.mock.calls.length === 1),
    ).toBe(true);
  });
});
