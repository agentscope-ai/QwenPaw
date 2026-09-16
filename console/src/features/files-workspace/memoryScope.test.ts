import { describe, expect, it } from "vitest";
import {
  resolveMemoryScopeSelection,
  type MemoryScopeSummary,
} from "./filesWorkspaceScope";

const publicScope: MemoryScopeSummary = {
  scope: "public",
  can_read: true,
  can_edit: false,
  status: "active",
  index_state: "ready",
  index_version: 0,
};

const privateScope: MemoryScopeSummary = {
  scope: "private",
  can_read: true,
  can_edit: true,
  status: "active",
  index_state: "needs_reindex",
  index_version: 1,
};

describe("resolveMemoryScopeSelection", () => {
  it("defaults to private memory and preserves an available selection", () => {
    expect(resolveMemoryScopeSelection([publicScope, privateScope])).toBe(
      "private",
    );
    expect(
      resolveMemoryScopeSelection([publicScope, privateScope], "private"),
    ).toBe("private");
  });

  it("drops a private selection after permission removal", () => {
    expect(resolveMemoryScopeSelection([publicScope], "private")).toBe(
      "public",
    );
  });
});
