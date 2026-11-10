import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { BrowserEventNotifier } from "./browserEvents";
import { updateNotificationPreferences } from "./preferences";
import type { SystemNotificationEvent } from "./notificationEvents";

const shown: {
  title: string;
  onclick?: () => void;
  close: ReturnType<typeof vi.fn>;
}[] = [];
class TestNotification {
  static permission = "granted";
  static failNext = false;
  close = vi.fn();
  title: string;
  constructor(title: string) {
    if (TestNotification.failNext) {
      TestNotification.failNext = false;
      throw new Error("Temporary notification delivery failure");
    }
    this.title = title;
    shown.push(this);
  }
}
const event = (id: string): SystemNotificationEvent => ({
  id,
  category: "cron",
  agent_id: "default",
  title: id,
  body: "result",
  created_at: Date.now() / 1000,
});
const flush = async () => {
  await Promise.resolve();
  await Promise.resolve();
};

describe("browser event delivery", () => {
  beforeEach(() => {
    localStorage.clear();
    shown.length = 0;
    TestNotification.failNext = false;
    vi.stubGlobal("Notification", TestNotification);
    vi.spyOn(document, "hasFocus").mockReturnValue(false);
    updateNotificationPreferences({ enabled: true, cron: true });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("seeds history, deduplicates snapshots and coordinates clients", async () => {
    const first = new BrowserEventNotifier(() => "Done", vi.fn());
    const second = new BrowserEventNotifier(() => "Done", vi.fn());
    first.update([event("old")]);
    second.update([event("old")]);
    first.update([event("old"), event("new")]);
    second.update([event("old"), event("new")]);
    first.update([event("old"), event("new")]);
    await flush();
    expect(shown.map((item) => item.title)).toEqual(["new"]);
    first.dispose();
    second.dispose();
  });

  it("does not replay events received while disabled", async () => {
    const notifier = new BrowserEventNotifier(() => "Done", vi.fn());
    notifier.update([]);
    updateNotificationPreferences({ enabled: false });
    notifier.update([event("disabled")]);
    await flush();
    updateNotificationPreferences({ enabled: true });
    notifier.update([event("disabled")]);
    await flush();
    expect(shown).toHaveLength(0);
    notifier.dispose();
  });

  it("retries a failed notification on the next snapshot and then deduplicates", async () => {
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});
    const notifier = new BrowserEventNotifier(() => "Done", vi.fn());
    const result = event("retry");
    notifier.update([]);
    TestNotification.failNext = true;
    notifier.update([result]);
    await flush();
    expect(shown).toHaveLength(0);
    expect(warning).toHaveBeenCalledOnce();

    notifier.update([result]);
    await flush();
    expect(shown.map((item) => item.title)).toEqual(["retry"]);
    notifier.update([result]);
    await flush();
    expect(shown).toHaveLength(1);
    notifier.dispose();
  });

  it("retries when the browser notification lock fails", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const request = vi
      .fn()
      .mockRejectedValueOnce(new Error("Temporary lock failure"))
      .mockImplementation(async (_name: string, send: () => void) => send());
    vi.stubGlobal("navigator", { locks: { request } });
    const notifier = new BrowserEventNotifier(() => "Done", vi.fn());
    const result = event("lock-retry");
    notifier.update([]);
    notifier.update([result]);
    await flush();
    expect(shown).toHaveLength(0);

    notifier.update([result]);
    await flush();
    expect(request).toHaveBeenCalledTimes(2);
    expect(shown.map((item) => item.title)).toEqual(["lock-retry"]);
    notifier.dispose();
  });

  it("rechecks preferences before a queued notification and stops after disposal", async () => {
    const notifier = new BrowserEventNotifier(() => "Done", vi.fn());
    notifier.update([]);
    notifier.update([event("queued")]);
    updateNotificationPreferences({ cron: false });
    await flush();
    expect(shown).toHaveLength(0);
    updateNotificationPreferences({ cron: true });
    notifier.update([event("next")]);
    notifier.dispose();
    await flush();
    expect(shown).toHaveLength(0);
  });

  it("does not send an event that arrived before enabling its category", async () => {
    const notifier = new BrowserEventNotifier(() => "Done", vi.fn());
    notifier.update([]);
    updateNotificationPreferences({ cron: false });
    notifier.update([event("disabled")]);
    updateNotificationPreferences({ cron: true });
    await flush();
    expect(shown).toHaveLength(0);
    notifier.dispose();
  });

  it("focuses the app and opens the notification target on click", async () => {
    const focus = vi.spyOn(window, "focus").mockImplementation(() => undefined);
    const open = vi.fn();
    const notifier = new BrowserEventNotifier(() => "Done", open);
    notifier.update([]);
    const result = event("clicked");
    notifier.update([result]);
    await flush();
    shown[0].onclick?.();
    expect(focus).toHaveBeenCalledOnce();
    expect(open).toHaveBeenCalledWith(result);
    notifier.dispose();
  });
});
