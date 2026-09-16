import { describe, expect, it } from "vitest";
import {
  decideChatResumeAction,
  shouldSyncChatAfterResume,
} from "./chatResumeSync";

describe("shouldSyncChatAfterResume", () => {
  it("does not synchronize an idle chat merely because the tab becomes visible", () => {
    expect(
      shouldSyncChatAfterResume({
        wasRunningWhenHidden: false,
        frontendRunning: false,
      }),
    ).toBe(false);
  });

  it("synchronizes when a foreground run was active before the tab was hidden", () => {
    expect(
      shouldSyncChatAfterResume({
        wasRunningWhenHidden: true,
        frontendRunning: false,
      }),
    ).toBe(true);
  });

  it("synchronizes while the frontend still considers the chat running", () => {
    expect(
      shouldSyncChatAfterResume({
        wasRunningWhenHidden: false,
        frontendRunning: true,
      }),
    ).toBe(true);
  });
});

describe("decideChatResumeAction", () => {
  it("does nothing for an idle chat when message counts already match", () => {
    expect(
      decideChatResumeAction({
        backendStatus: "idle",
        backendMessageCount: 4,
        currentMessageCount: 4,
        frontendRunning: false,
      }),
    ).toBe("none");
  });

  it("replaces the UI from the canonical history when idle messages are missing", () => {
    expect(
      decideChatResumeAction({
        backendStatus: "idle",
        backendMessageCount: 6,
        currentMessageCount: 4,
        frontendRunning: false,
      }),
    ).toBe("replace_history");
  });

  it("replaces the UI when a frontend run completed while the page was hidden", () => {
    expect(
      decideChatResumeAction({
        backendStatus: "idle",
        backendMessageCount: 4,
        currentMessageCount: 4,
        frontendRunning: true,
      }),
    ).toBe("replace_history");
  });

  it("replaces duplicated UI messages from the canonical idle history", () => {
    expect(
      decideChatResumeAction({
        backendStatus: "idle",
        backendMessageCount: 2,
        currentMessageCount: 4,
        frontendRunning: false,
      }),
    ).toBe("replace_history");
  });

  it("does nothing while both sides still report the active run", () => {
    expect(
      decideChatResumeAction({
        backendStatus: "running",
        backendMessageCount: 4,
        currentMessageCount: 4,
        frontendRunning: true,
      }),
    ).toBe("none");
  });

  it("reconnects an active run only when the backend is ahead", () => {
    expect(
      decideChatResumeAction({
        backendStatus: "running",
        backendMessageCount: 6,
        currentMessageCount: 4,
        frontendRunning: true,
      }),
    ).toBe("reconnect");
  });
});
