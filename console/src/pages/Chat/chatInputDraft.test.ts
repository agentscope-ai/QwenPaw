import { describe, expect, it } from "vitest";
import {
  DRAFT_STORAGE_KEY_PREFIX,
  getDraftStorageKey,
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
    expect(getDraftStorageKey("agent-a")).toBe(
      `${DRAFT_STORAGE_KEY_PREFIX}_agent-a`,
    );
  });

  it("produces distinct keys for distinct agents", () => {
    // The core contract: switching agents must never surface another
    // agent's draft.
    expect(getDraftStorageKey("agent-a")).not.toBe(
      getDraftStorageKey("agent-b"),
    );
  });

  it("falls back to the shared key without an agent id", () => {
    expect(getDraftStorageKey()).toBe(DRAFT_STORAGE_KEY_PREFIX);
    expect(getDraftStorageKey(undefined)).toBe(DRAFT_STORAGE_KEY_PREFIX);
  });

  it("falls back to the shared key for a falsy agent id", () => {
    expect(getDraftStorageKey("")).toBe(DRAFT_STORAGE_KEY_PREFIX);
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
