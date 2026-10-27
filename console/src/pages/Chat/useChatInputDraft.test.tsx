import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";
import { stripRouterBasename } from "../../utils/navigationMode";
import { getSessionIdFromPath } from "../../utils/sessionRoute";
import {
  DRAFT_STORAGE_KEY_PREFIX,
  getDraftStorageKey,
  handoverDraftToSession,
  useChatInputDraft,
} from "./chatInputDraft";

/**
 * Mounts the real draft hook. ChatPage's integration suite mocks
 * setTextareaValue, so it cannot show whether the composer is cleared.
 */

function Harness({ sessionId }: { sessionId?: string }) {
  useChatInputDraft(true, "agent-a", sessionId);
  return (
    <div className="sender">
      <textarea aria-label="composer" />
    </div>
  );
}

function AgentHarness({
  agentId,
  sessionId,
}: {
  agentId: string;
  sessionId?: string;
}) {
  useChatInputDraft(true, agentId, sessionId);
  return (
    <div className="sender">
      <textarea aria-label="composer" />
    </div>
  );
}

function SessionSwitch() {
  const [sessionId, setSessionId] = useState("session-a");
  useChatInputDraft(true, "agent-a", sessionId);
  return (
    <>
      <button type="button" onClick={() => setSessionId("session-b")}>
        open-b
      </button>
      <div className="sender">
        <textarea aria-label="composer" />
      </div>
    </>
  );
}

function DesktopRouteHarness() {
  const sessionId = getSessionIdFromPath(useLocation().pathname);
  useChatInputDraft(true, "agent-a", sessionId);
  return (
    <div className="sender">
      <textarea aria-label="composer" />
    </div>
  );
}

function Switchable() {
  const [sessionId, setSessionId] = useState<string | undefined>(undefined);
  useChatInputDraft(true, "agent-a", sessionId);
  return (
    <>
      <button type="button" onClick={() => setSessionId("session-b")}>
        open-b
      </button>
      <button type="button" onClick={() => setSessionId(undefined)}>
        open-new
      </button>
      <button type="button" onClick={() => setSessionId("real-session")}>
        open-real
      </button>
      <div className="sender">
        <textarea aria-label="composer" />
      </div>
    </>
  );
}

function composer(): HTMLTextAreaElement {
  const textarea = screen.getByRole("textbox", { name: "composer" });
  if (!(textarea instanceof HTMLTextAreaElement)) {
    throw new Error("composer is not a textarea");
  }
  return textarea;
}

function typeIntoComposer(value: string) {
  const textarea = composer();
  textarea.value = value;
  textarea.selectionStart = value.length;
  textarea.selectionEnd = value.length;
  fireEvent.input(textarea);
  return textarea;
}

afterEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  window.history.replaceState({}, "", "/");
});

describe("useChatInputDraft (#8351)", () => {
  it("does not restore a legacy per-agent draft on a new chat", () => {
    const legacy = `${DRAFT_STORAGE_KEY_PREFIX}_agent-a`;
    localStorage.setItem(
      legacy,
      JSON.stringify({
        value: "stale legacy",
        selectionStart: 0,
        selectionEnd: 0,
      }),
    );
    render(<Harness />);
    expect(composer().value).toBe("");
    expect(localStorage.getItem(legacy)).toBeNull();
    expect(localStorage.getItem(getDraftStorageKey("agent-a"))).toBeNull();
  });

  it("does not restore a legacy per-agent draft into an existing session", () => {
    const legacy = `${DRAFT_STORAGE_KEY_PREFIX}_agent-a`;
    localStorage.setItem(
      legacy,
      JSON.stringify({
        value: "stale legacy",
        selectionStart: 0,
        selectionEnd: 0,
      }),
    );
    render(<Harness sessionId="session-a" />);
    expect(composer().value).toBe("");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "session-a")),
    ).toBeNull();
    expect(localStorage.getItem(legacy)).toBeNull();
  });

  it("keeps the follow-up when the blank route becomes a real session", () => {
    render(<Switchable />);
    const textarea = typeIntoComposer("follow up");
    act(() => {
      handoverDraftToSession("agent-a", "real-session");
    });
    fireEvent.click(screen.getByRole("button", { name: "open-real" }));
    expect(textarea.value).toBe("follow up");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "real-session")),
    ).toContain("follow up");
    expect(localStorage.getItem(getDraftStorageKey("agent-a"))).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "open-new" }));
    expect(textarea.value).toBe("");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "real-session")),
    ).toContain("follow up");
  });

  it("does not carry a blank-route draft into a different session", () => {
    render(<Switchable />);
    typeIntoComposer("only new");
    fireEvent.click(screen.getByRole("button", { name: "open-b" }));
    const textarea = composer();
    expect(textarea.value).toBe("");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "session-b")),
    ).toBeNull();
    expect(localStorage.getItem(getDraftStorageKey("agent-a"))).toContain(
      "only new",
    );
    fireEvent.click(screen.getByRole("button", { name: "open-new" }));
    expect(textarea.value).toBe("only new");
  });

  it("restores the same session after leaving and coming back (#4774)", () => {
    const view = render(<Harness sessionId="session-a" />);
    typeIntoComposer("keep me");
    view.unmount();
    render(<Harness sessionId="session-a" />);
    expect(composer().value).toBe("keep me");
  });

  it("shows session B's draft and never session A's", () => {
    localStorage.setItem(
      getDraftStorageKey("agent-a", "session-b"),
      JSON.stringify({
        value: "only B",
        selectionStart: 0,
        selectionEnd: 0,
      }),
    );
    render(<SessionSwitch />);
    typeIntoComposer("only A");
    fireEvent.click(screen.getByRole("button", { name: "open-b" }));
    expect(composer().value).toBe("only B");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "session-a")),
    ).toContain("only A");
  });

  it("restores a pre-creation composer after leaving and coming back (#4774)", () => {
    const view = render(<Harness />);
    typeIntoComposer("pending keep");
    view.unmount();
    render(<Harness />);
    expect(composer().value).toBe("pending keep");
  });

  it("does not restore the previous new chat when New Chat is opened from another page", () => {
    const view = render(<Harness />);
    typeIntoComposer("alpha");
    const firstKey = getDraftStorageKey("agent-a");
    expect(localStorage.getItem(firstKey)).toContain("alpha");
    view.unmount();
    sessionStorage.setItem("qwenpaw_pending_new_chat", "1");
    render(<Harness />);
    expect(composer().value).toBe("");
    expect(getDraftStorageKey("agent-a")).not.toBe(firstKey);
    expect(localStorage.getItem(firstKey)).toContain("alpha");
  });

  it("does not show one brand-new chat's text in the next new chat", () => {
    render(<Harness />);
    typeIntoComposer("alpha");
    const firstKey = getDraftStorageKey("agent-a");
    expect(localStorage.getItem(firstKey)).toContain("alpha");
    act(() => {
      window.dispatchEvent(new CustomEvent("qwenpaw:sidebar-new-chat"));
    });
    expect(composer().value).toBe("");
    expect(localStorage.getItem(firstKey)).toContain("alpha");
    const secondKey = getDraftStorageKey("agent-a");
    expect(secondKey).not.toBe(firstKey);
    typeIntoComposer("beta");
    expect(composer().value).toBe("beta");
    expect(localStorage.getItem(secondKey)).toContain("beta");
    expect(localStorage.getItem(firstKey)).toContain("alpha");
  });

  it("does not restore the shared per-agent pending slot into a new chat", () => {
    const shared = `${DRAFT_STORAGE_KEY_PREFIX}_agent-a__pending`;
    localStorage.setItem(
      shared,
      JSON.stringify({
        value: "from the other new chat",
        selectionStart: 0,
        selectionEnd: 0,
      }),
    );
    render(<Harness />);
    expect(composer().value).toBe("");
    expect(localStorage.getItem(shared)).toBeNull();
  });

  it("clears only the conversation that was sent", () => {
    localStorage.setItem(
      getDraftStorageKey("agent-a", "session-b"),
      JSON.stringify({
        value: "keep B",
        selectionStart: 0,
        selectionEnd: 0,
      }),
    );
    render(<Harness sessionId="session-a" />);
    typeIntoComposer("gone A");
    typeIntoComposer("");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "session-a")),
    ).toBeNull();
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "session-b")),
    ).toContain("keep B");
  });

  it("does not leak a draft across agents", () => {
    const view = render(
      <AgentHarness agentId="agent-a" sessionId="session-a" />,
    );
    typeIntoComposer("secret-a");
    view.unmount();
    render(<AgentHarness agentId="agent-b" sessionId="session-a" />);
    expect(composer().value).toBe("");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "session-a")),
    ).toContain("secret-a");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-b", "session-a")),
    ).toBeNull();
  });

  it("stores a desktop /console/chat/<id> draft on that session", () => {
    window.history.replaceState({}, "", "/console/chat/session-a");
    expect(getSessionIdFromPath(window.location.pathname)).toBeUndefined();
    expect(
      getSessionIdFromPath(stripRouterBasename(window.location.pathname)),
    ).toBe("session-a");
    render(
      <MemoryRouter
        basename="/console"
        initialEntries={["/console/chat/session-a"]}
      >
        <DesktopRouteHarness />
      </MemoryRouter>,
    );
    typeIntoComposer("desktop only");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "session-a")),
    ).toContain("desktop only");
    expect(
      Object.keys(localStorage).some((key) => key.endsWith("__pending")),
    ).toBe(false);
  });
});
