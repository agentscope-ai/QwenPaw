import { describe, expect, it } from "vitest";
import {
  DRAFT_STORAGE_KEY_PREFIX,
  getDraftStorageKey,
  handoverDraftToSession,
  parseDraft,
  serializeDraft,
} from "./chatInputDraft";

// ---------------------------------------------------------------------------
// getDraftStorageKey — regression for A#82689956
// (drafts leaked across agents because all agents shared one storage key;
// the key must be namespaced per agent so drafts stay isolated)
// ---------------------------------------------------------------------------
describe("getDraftStorageKey (A#82689956)", () => {
  it("namespaces the key with the agent id", () => {
    const key = getDraftStorageKey("agent-a");
    expect(key).toContain(`${DRAFT_STORAGE_KEY_PREFIX}_agent-a`);
    // The blank route must not reuse the pre-#8351 per-agent slot.
    expect(key).not.toBe(`${DRAFT_STORAGE_KEY_PREFIX}_agent-a`);
  });

  it("produces distinct keys for distinct agents", () => {
    // The core contract: switching agents must never surface another
    // agent's draft.
    expect(getDraftStorageKey("agent-a")).not.toBe(
      getDraftStorageKey("agent-b"),
    );
  });

  it("does not use the legacy shared key when no agent id is selected", () => {
    expect(getDraftStorageKey()).not.toBe(DRAFT_STORAGE_KEY_PREFIX);
    expect(getDraftStorageKey(undefined)).not.toBe(DRAFT_STORAGE_KEY_PREFIX);
    expect(getDraftStorageKey("")).not.toBe(DRAFT_STORAGE_KEY_PREFIX);
    expect(getDraftStorageKey()).toBe(getDraftStorageKey(undefined));
    expect(getDraftStorageKey()).toBe(getDraftStorageKey(""));
  });

  it("still appends a real session id when the agent id is missing", () => {
    expect(getDraftStorageKey(undefined, "session-1")).toBe(
      `${DRAFT_STORAGE_KEY_PREFIX}_session-1`,
    );
    expect(getDraftStorageKey(undefined, "session-1")).not.toBe(
      getDraftStorageKey(undefined),
    );
  });
});

// ---------------------------------------------------------------------------
// Per-session drafts — regression for #8351
// (one agent shares many conversations; the storage key must include the
// session so an unsent draft does not appear in the agent's other sessions.
// A legacy per-agent entry must not be read back for every session.)
// ---------------------------------------------------------------------------
describe("per-session chat input drafts (#8351)", () => {
  const memory = () => {
    const items = new Map<string, string>();
    return {
      get(agentId?: string, sessionId?: string) {
        return parseDraft(
          items.get(getDraftStorageKey(agentId, sessionId)) ?? null,
        );
      },
      set(
        agentId: string | undefined,
        sessionId: string | undefined,
        draft: { value: string; selectionStart: number; selectionEnd: number },
      ) {
        const key = getDraftStorageKey(agentId, sessionId);
        const serialized = serializeDraft(draft);
        if (serialized) items.set(key, serialized);
        else items.delete(key);
      },
      raw(agentId?: string, sessionId?: string) {
        return items.get(getDraftStorageKey(agentId, sessionId)) ?? null;
      },
    };
  };

  it("keys a saved draft by agent and session", () => {
    expect(getDraftStorageKey("agent-a", "session-1")).toBe(
      `${DRAFT_STORAGE_KEY_PREFIX}_agent-a_session-1`,
    );
  });

  it("gives each session of one agent its own key", () => {
    expect(getDraftStorageKey("agent-a", "session-1")).not.toBe(
      getDraftStorageKey("agent-a", "session-2"),
    );
    expect(getDraftStorageKey("agent-a", "session-1")).not.toBe(
      getDraftStorageKey("agent-b", "session-1"),
    );
  });

  it("gives each pre-creation composer its own pending slot (#8351)", () => {
    sessionStorage.clear();
    localStorage.clear();
    const legacy = `${DRAFT_STORAGE_KEY_PREFIX}_agent-a`;
    const sharedPending = `${legacy}__pending`;
    const first = getDraftStorageKey("agent-a");
    // /chat and /chat/new are the same composer until a new one starts.
    expect(getDraftStorageKey("agent-a", undefined)).toBe(first);
    expect(getDraftStorageKey("agent-a", "")).toBe(first);
    expect(getDraftStorageKey("agent-a", "new")).toBe(first);
    expect(first).not.toBe(legacy);
    expect(first).not.toBe(sharedPending);
    expect(first.startsWith(`${legacy}_pending_`)).toBe(true);
    expect(getDraftStorageKey("agent-a", "session-1")).not.toBe(first);
    expect(getDraftStorageKey("agent-a", "session-1")).not.toBe(legacy);

    sessionStorage.clear();
    const second = getDraftStorageKey("agent-a");
    expect(second).not.toBe(first);
    expect(second.startsWith(`${legacy}_pending_`)).toBe(true);
    expect(
      getDraftStorageKey("agent-b").startsWith(
        `${DRAFT_STORAGE_KEY_PREFIX}_agent-b_pending_`,
      ),
    ).toBe(true);
    sessionStorage.clear();
    localStorage.clear();
  });

  it("restores the draft saved for that session and not another session", () => {
    const storage = memory();
    const draftA = { value: "only A", selectionStart: 1, selectionEnd: 4 };
    storage.set("agent-a", "session-a", draftA);
    storage.set("agent-a", "session-b", {
      value: "only B",
      selectionStart: 0,
      selectionEnd: 0,
    });

    expect(storage.get("agent-a", "session-a")).toEqual(draftA);
    expect(storage.get("agent-a", "session-b")?.value).toBe("only B");
    expect(storage.get("agent-b", "session-a")).toBeNull();
  });

  it("does not load a blank-route draft into every session", () => {
    const storage = memory();
    storage.set("agent-a", undefined, {
      value: "unsent new chat",
      selectionStart: 0,
      selectionEnd: 0,
    });

    expect(storage.get("agent-a", "session-a")).toBeNull();
    expect(storage.get("agent-a", "session-b")).toBeNull();
    expect(storage.get("agent-a")?.value).toBe("unsent new chat");
    expect(storage.get("agent-a", "new")?.value).toBe("unsent new chat");
  });

  it("does not copy a legacy per-agent value into a session or a new chat", async () => {
    localStorage.clear();
    const legacy = `${DRAFT_STORAGE_KEY_PREFIX}_agent-a`;
    localStorage.setItem(
      legacy,
      JSON.stringify({
        value: "stale legacy",
        selectionStart: 0,
        selectionEnd: 0,
      }),
    );
    const draftModule = await import("./chatInputDraft");
    expect(draftModule.handoverDraftToSession).toEqual(expect.any(Function));
    draftModule.handoverDraftToSession("agent-a", "real-session");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "real-session")),
    ).toBeNull();
    expect(localStorage.getItem(getDraftStorageKey("agent-a"))).toBeNull();
    expect(localStorage.getItem(legacy)).toBeNull();
    localStorage.clear();
  });

  it("moves the blank-route draft onto the session that was just allocated", async () => {
    localStorage.clear();
    const pending = getDraftStorageKey("agent-a");
    const legacy = `${DRAFT_STORAGE_KEY_PREFIX}_agent-a`;
    const sessionKey = getDraftStorageKey("agent-a", "real-session");
    localStorage.setItem(
      pending,
      JSON.stringify({
        value: "follow up",
        selectionStart: 2,
        selectionEnd: 4,
      }),
    );
    if (legacy !== pending) {
      localStorage.setItem(
        legacy,
        JSON.stringify({
          value: "stale legacy",
          selectionStart: 0,
          selectionEnd: 0,
        }),
      );
    }
    const { handoverDraftToSession } = await import("./chatInputDraft");
    expect(handoverDraftToSession).toEqual(expect.any(Function));
    handoverDraftToSession("agent-a", "real-session");
    expect(localStorage.getItem(sessionKey)).toContain("follow up");
    expect(localStorage.getItem(sessionKey)).not.toContain("stale legacy");
    expect(localStorage.getItem(pending)).toBeNull();
    expect(localStorage.getItem(legacy)).toBeNull();
    localStorage.clear();
  });

  it("hands over only the active pre-creation composer", () => {
    sessionStorage.clear();
    localStorage.clear();
    const first = getDraftStorageKey("agent-a");
    localStorage.setItem(
      first,
      JSON.stringify({
        value: "first new",
        selectionStart: 0,
        selectionEnd: 0,
      }),
    );
    sessionStorage.clear();
    const second = getDraftStorageKey("agent-a");
    localStorage.setItem(
      second,
      JSON.stringify({
        value: "second new",
        selectionStart: 1,
        selectionEnd: 1,
      }),
    );
    handoverDraftToSession("agent-a", "real-session");
    expect(
      localStorage.getItem(getDraftStorageKey("agent-a", "real-session")),
    ).toContain("second new");
    expect(localStorage.getItem(first)).toContain("first new");
    expect(localStorage.getItem(second)).toBeNull();
    expect(
      localStorage.getItem(`${DRAFT_STORAGE_KEY_PREFIX}_agent-a`),
    ).toBeNull();
    sessionStorage.clear();
    localStorage.clear();
  });

  it("removes an empty draft from that session only", () => {
    const storage = memory();
    storage.set("agent-a", "session-a", {
      value: "gone",
      selectionStart: 0,
      selectionEnd: 0,
    });
    storage.set("agent-a", "session-b", {
      value: "keep",
      selectionStart: 2,
      selectionEnd: 2,
    });
    storage.set("agent-a", "session-a", {
      value: "",
      selectionStart: 0,
      selectionEnd: 0,
    });

    expect(storage.get("agent-a", "session-a")).toBeNull();
    expect(storage.raw("agent-a", "session-a")).toBeNull();
    expect(storage.get("agent-a", "session-b")?.value).toBe("keep");
  });
});

// ---------------------------------------------------------------------------
// serializeDraft / parseDraft — regression for #4774
// (navigating away and back must restore the draft exactly; empty drafts
// must be removed, malformed stored data must never throw)
// ---------------------------------------------------------------------------
describe("draft serialize/parse round-trip (#4774)", () => {
  it("round-trips value and cursor selection", () => {
    const draft = { value: "hello draft", selectionStart: 2, selectionEnd: 5 };
    expect(parseDraft(serializeDraft(draft))).toEqual(draft);
  });

  it("returns null for an empty value so callers remove the stored draft", () => {
    expect(
      serializeDraft({ value: "", selectionStart: 0, selectionEnd: 0 }),
    ).toBeNull();
  });

  it("returns null for missing or empty stored data", () => {
    expect(parseDraft(null)).toBeNull();
    expect(parseDraft("")).toBeNull();
  });

  it("fails soft on malformed JSON instead of throwing", () => {
    expect(parseDraft("{not valid json")).toBeNull();
  });

  it("returns null when the parsed draft has an empty value", () => {
    expect(
      parseDraft(
        JSON.stringify({ value: "", selectionStart: 0, selectionEnd: 0 }),
      ),
    ).toBeNull();
  });

  // -------------------------------------------------------------------------
  // Draft cleared after send — regression for A#82576583
  // After a message is sent, the draft must be cleared so it doesn't resurface
  // on the next visit. serializeDraft returns null for an empty draft,
  // signaling callers to removeItem from storage.
  // -------------------------------------------------------------------------
  it("serializeDraft returns null after send clears the draft (A#82576583)", () => {
    // Simulate: user had a draft, then sent the message (value becomes "")
    const afterSend = { value: "", selectionStart: 0, selectionEnd: 0 };
    const serialized = serializeDraft(afterSend);
    // null signals callers to removeItem — draft must not persist
    expect(serialized).toBeNull();
    // And parsing null returns null — no stale draft resurfaces
    expect(parseDraft(serialized)).toBeNull();
  });

  it("round-trip: non-empty draft survives, empty draft is removed (A#82576583)", () => {
    // User types something
    const typed = { value: "hello", selectionStart: 5, selectionEnd: 5 };
    expect(parseDraft(serializeDraft(typed))).toEqual(typed);

    // User sends the message → draft cleared
    const cleared = { value: "", selectionStart: 0, selectionEnd: 0 };
    expect(serializeDraft(cleared)).toBeNull();
    expect(parseDraft(null)).toBeNull();
  });
});
