import { describe, it, expect, beforeEach } from "vitest";
import { useChatStore } from "./chatStore";
import type { ChatMessage } from "../types";
import { MESSAGE_STATUS } from "../constants";

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: `msg-${Date.now()}`,
    role: "user",
    content: [{ type: "text", text: "hello" }],
    status: MESSAGE_STATUS.COMPLETED,
    createdAt: Date.now(),
    ...overrides,
  };
}

describe("chatStore", () => {
  beforeEach(() => {
    useChatStore.setState({
      messages: {},
      activeSessionId: null,
      isGenerating: false,
      streamingMessageId: null,
    });
  });

  // -------------------------------------------------------------------------
  // Initial state
  // -------------------------------------------------------------------------

  it("has empty initial state", () => {
    const state = useChatStore.getState();
    expect(state.messages).toEqual({});
    expect(state.activeSessionId).toBeNull();
    expect(state.isGenerating).toBe(false);
    expect(state.streamingMessageId).toBeNull();
  });

  // -------------------------------------------------------------------------
  // setActiveSession
  // -------------------------------------------------------------------------

  it("setActiveSession updates activeSessionId", () => {
    useChatStore.getState().setActiveSession("session-1");
    expect(useChatStore.getState().activeSessionId).toBe("session-1");
  });

  it("setActiveSession can clear to null", () => {
    useChatStore.getState().setActiveSession("session-1");
    useChatStore.getState().setActiveSession(null);
    expect(useChatStore.getState().activeSessionId).toBeNull();
  });

  // -------------------------------------------------------------------------
  // setGenerating
  // -------------------------------------------------------------------------

  it("setGenerating toggles isGenerating", () => {
    useChatStore.getState().setGenerating(true);
    expect(useChatStore.getState().isGenerating).toBe(true);
    useChatStore.getState().setGenerating(false);
    expect(useChatStore.getState().isGenerating).toBe(false);
  });

  // -------------------------------------------------------------------------
  // addMessage
  // -------------------------------------------------------------------------

  it("addMessage appends to session message list", () => {
    const msg = makeMessage({ id: "m1" });
    useChatStore.getState().addMessage("s1", msg);
    expect(useChatStore.getState().messages["s1"]).toHaveLength(1);
    expect(useChatStore.getState().messages["s1"][0].id).toBe("m1");
  });

  it("addMessage creates session entry if not exists", () => {
    const msg = makeMessage({ id: "m1" });
    useChatStore.getState().addMessage("new-session", msg);
    expect(useChatStore.getState().messages["new-session"]).toBeDefined();
  });

  it("addMessage generates id if not provided", () => {
    const msg = makeMessage({ id: "" });
    useChatStore.getState().addMessage("s1", msg);
    const stored = useChatStore.getState().messages["s1"][0];
    expect(stored.id).toBeTruthy();
  });

  // -------------------------------------------------------------------------
  // updateMessage
  // -------------------------------------------------------------------------

  it("updateMessage patches specific fields", () => {
    const msg = makeMessage({ id: "m1", status: MESSAGE_STATUS.PENDING });
    useChatStore.getState().addMessage("s1", msg);
    useChatStore
      .getState()
      .updateMessage("s1", "m1", { status: MESSAGE_STATUS.COMPLETED });
    expect(useChatStore.getState().messages["s1"][0].status).toBe(
      MESSAGE_STATUS.COMPLETED,
    );
  });

  it("updateMessage does nothing for nonexistent session", () => {
    const before = useChatStore.getState();
    useChatStore
      .getState()
      .updateMessage("nope", "m1", { status: MESSAGE_STATUS.ERROR });
    expect(useChatStore.getState()).toBe(before);
  });

  // -------------------------------------------------------------------------
  // appendStreamText
  // -------------------------------------------------------------------------

  it("appendStreamText appends to last text content block", () => {
    const msg = makeMessage({
      id: "m1",
      role: "assistant",
      content: [{ type: "text", text: "Hello" }],
    });
    useChatStore.getState().addMessage("s1", msg);
    useChatStore.getState().appendStreamText("s1", "m1", " world");
    const content = useChatStore.getState().messages["s1"][0].content;
    expect(content[0]).toEqual({ type: "text", text: "Hello world" });
  });

  it("appendStreamText creates new text block if none exists", () => {
    const msg = makeMessage({
      id: "m1",
      role: "assistant",
      content: [{ type: "thinking", text: "hmm", collapsed: false }],
    });
    useChatStore.getState().addMessage("s1", msg);
    useChatStore.getState().appendStreamText("s1", "m1", "response");
    const content = useChatStore.getState().messages["s1"][0].content;
    expect(content).toHaveLength(2);
    expect(content[1]).toEqual({ type: "text", text: "response" });
  });

  // -------------------------------------------------------------------------
  // updateStreamContent
  // -------------------------------------------------------------------------

  it("updateStreamContent replaces content array", () => {
    const msg = makeMessage({ id: "m1", content: [] });
    useChatStore.getState().addMessage("s1", msg);
    const newContent = [
      { type: "text" as const, text: "new" },
      { type: "thinking" as const, text: "think", collapsed: false },
    ];
    useChatStore.getState().updateStreamContent("s1", "m1", newContent);
    expect(useChatStore.getState().messages["s1"][0].content).toEqual(
      newContent,
    );
  });

  // -------------------------------------------------------------------------
  // setStreamingMessage
  // -------------------------------------------------------------------------

  it("setStreamingMessage sets and clears streaming ID", () => {
    useChatStore.getState().setStreamingMessage("m1");
    expect(useChatStore.getState().streamingMessageId).toBe("m1");
    useChatStore.getState().setStreamingMessage(null);
    expect(useChatStore.getState().streamingMessageId).toBeNull();
  });

  // -------------------------------------------------------------------------
  // finalizeMessage
  // -------------------------------------------------------------------------

  it("finalizeMessage sets status to completed and clears streaming", () => {
    const msg = makeMessage({ id: "m1", status: MESSAGE_STATUS.STREAMING });
    useChatStore.getState().addMessage("s1", msg);
    useChatStore.setState({ streamingMessageId: "m1", isGenerating: true });

    useChatStore.getState().finalizeMessage("s1", "m1", { model: "qwen" });

    const state = useChatStore.getState();
    expect(state.messages["s1"][0].status).toBe(MESSAGE_STATUS.COMPLETED);
    expect(state.messages["s1"][0].metadata?.model).toBe("qwen");
    expect(state.streamingMessageId).toBeNull();
    expect(state.isGenerating).toBe(false);
  });

  it("finalizeMessage does not clear streaming if different message", () => {
    const msg = makeMessage({ id: "m1", status: MESSAGE_STATUS.STREAMING });
    useChatStore.getState().addMessage("s1", msg);
    useChatStore.setState({ streamingMessageId: "m2", isGenerating: true });

    useChatStore.getState().finalizeMessage("s1", "m1");

    expect(useChatStore.getState().streamingMessageId).toBe("m2");
    expect(useChatStore.getState().isGenerating).toBe(true);
  });

  // -------------------------------------------------------------------------
  // clearMessages
  // -------------------------------------------------------------------------

  it("clearMessages empties session messages", () => {
    useChatStore.getState().addMessage("s1", makeMessage({ id: "m1" }));
    useChatStore.getState().addMessage("s1", makeMessage({ id: "m2" }));
    useChatStore.getState().clearMessages("s1");
    expect(useChatStore.getState().messages["s1"]).toEqual([]);
  });

  // -------------------------------------------------------------------------
  // removeMessage
  // -------------------------------------------------------------------------

  it("removeMessage removes specific message by ID", () => {
    useChatStore.getState().addMessage("s1", makeMessage({ id: "m1" }));
    useChatStore.getState().addMessage("s1", makeMessage({ id: "m2" }));
    useChatStore.getState().removeMessage("s1", "m1");
    const msgs = useChatStore.getState().messages["s1"];
    expect(msgs).toHaveLength(1);
    expect(msgs[0].id).toBe("m2");
  });

  // -------------------------------------------------------------------------
  // getMessages
  // -------------------------------------------------------------------------

  it("getMessages returns empty array for unknown session", () => {
    expect(useChatStore.getState().getMessages("unknown")).toEqual([]);
  });

  it("getMessages returns messages for known session", () => {
    useChatStore.getState().addMessage("s1", makeMessage({ id: "m1" }));
    expect(useChatStore.getState().getMessages("s1")).toHaveLength(1);
  });
});
