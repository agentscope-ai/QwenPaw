import { beforeEach, describe, expect, it } from "vitest";
import {
  getNotificationPreferences,
  updateNotificationPreferences,
} from "./preferences";
import {
  notificationEventPath,
  shouldNotifyEvent,
  type SystemNotificationEvent,
} from "./notificationEvents";

const event: SystemNotificationEvent = {
  id: "result",
  category: "conversation",
  agent_id: "agent a",
  title: "Done",
  body: "",
  created_at: 100,
  session_id: "session/one",
};

describe("system notification preferences and routing", () => {
  beforeEach(() => localStorage.clear());

  it("inherits existing approval consent and defaults new categories to off", () => {
    localStorage.setItem("qwenpaw.approvalNotifications.enabled", "true");
    expect(getNotificationPreferences()).toEqual({
      enabled: true,
      approval: true,
      approvalTiming: "background",
      conversation: "off",
      cron: false,
      heartbeat: false,
      mail: false,
    });
    updateNotificationPreferences({ mail: true });
    expect(getNotificationPreferences().approval).toBe(true);
  });

  it("preserves existing approval choices and validates the new timing", () => {
    localStorage.setItem(
      "qwenpaw.systemNotifications",
      JSON.stringify({ enabled: true, approval: true }),
    );
    expect(getNotificationPreferences()).toMatchObject({
      approval: true,
      approvalTiming: "background",
    });
    updateNotificationPreferences({ approvalTiming: "always" });
    updateNotificationPreferences({ enabled: false });
    expect(getNotificationPreferences()).toMatchObject({
      enabled: false,
      approval: true,
      approvalTiming: "always",
    });
    localStorage.setItem(
      "qwenpaw.systemNotifications",
      JSON.stringify({ approval: false, approvalTiming: "invalid" }),
    );
    expect(getNotificationPreferences()).toMatchObject({
      approval: false,
      approvalTiming: "background",
    });
  });

  it("handles corrupt and malformed persisted settings", () => {
    localStorage.setItem("qwenpaw.systemNotifications", "{");
    expect(getNotificationPreferences().enabled).toBe(false);
    localStorage.setItem(
      "qwenpaw.systemNotifications",
      '{"enabled":"false","mail":1,"conversation":"invalid"}',
    );
    expect(getNotificationPreferences()).toMatchObject({
      enabled: false,
      mail: false,
      conversation: "off",
    });
  });

  it("applies master, category and foreground policy", () => {
    updateNotificationPreferences({
      enabled: true,
      conversation: "background",
      cron: true,
    });
    expect(shouldNotifyEvent(event, getNotificationPreferences(), false)).toBe(
      false,
    );
    expect(shouldNotifyEvent(event, getNotificationPreferences(), true)).toBe(
      true,
    );
    updateNotificationPreferences({ conversation: "always" });
    expect(shouldNotifyEvent(event, getNotificationPreferences(), false)).toBe(
      true,
    );
    expect(
      shouldNotifyEvent(
        { ...event, category: "mail" },
        getNotificationPreferences(),
        true,
      ),
    ).toBe(false);
    expect(
      shouldNotifyEvent(
        { ...event, category: "cron" },
        getNotificationPreferences(),
        false,
      ),
    ).toBe(false);
    updateNotificationPreferences({ enabled: false });
    expect(shouldNotifyEvent(event, getNotificationPreferences(), true)).toBe(
      false,
    );
  });

  it("routes to the owning agent or exact inbox event with encoded IDs", () => {
    expect(notificationEventPath(event)).toBe(
      "/chat/session%2Fone?agent=agent%20a",
    );
    expect(
      notificationEventPath({
        ...event,
        category: "mail",
        inbox_event_id: "mail&1",
      }),
    ).toBe("/inbox?tab=messages&event=mail%261");
  });
});
