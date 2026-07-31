/**
 * findSessionRowIndex locates the active conversation inside the
 * flattened (group header + session) row list used by the virtualized
 * session lists, so they can scroll it into view after remount.
 */
import { describe, it, expect } from "vitest";
import { findSessionRowIndex } from "./sessionGrouping";

const rows = [
  { kind: "groupHeader" as const },
  { kind: "session" as const, session: { id: "a" } },
  { kind: "session" as const, session: { id: "local-1", realId: "b" } },
  { kind: "groupHeader" as const },
  { kind: "session" as const, session: { id: "c" } },
];

describe("findSessionRowIndex", () => {
  it("finds a session row by id", () => {
    expect(findSessionRowIndex(rows, "c")).toBe(4);
  });

  it("finds a session row by realId (local timestamp entries)", () => {
    expect(findSessionRowIndex(rows, "b")).toBe(2);
  });

  it("returns -1 when the session is not in the visible rows", () => {
    expect(findSessionRowIndex(rows, "hidden")).toBe(-1);
  });

  it("returns -1 for an undefined session id", () => {
    expect(findSessionRowIndex(rows, undefined)).toBe(-1);
  });

  it("never matches a group header row", () => {
    expect(findSessionRowIndex([{ kind: "groupHeader" }], "a")).toBe(-1);
  });
});
