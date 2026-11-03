import { describe, it, expect } from "vitest";
import { editable } from "./shared";

/**
 * editable strips the two server owned identity fields so a PUT body never
 * echoes back an id or a stale revision.
 */

describe("editable", () => {
  it("drops id and revision from the payload", () => {
    expect(
      editable({ id: "c-1", revision: 7, name: "main", enabled: true }),
    ).toEqual({ name: "main", enabled: true });
  });

  it("keeps the remaining fields untouched", () => {
    const result = editable({
      id: "c-2",
      revision: 0,
      label: "staging",
      limit: 100,
      nested: { a: 1 },
    });
    expect(result).toEqual({ label: "staging", limit: 100, nested: { a: 1 } });
  });

  it("returns an empty object when only identity fields are present", () => {
    expect(editable({ id: "c-3", revision: 1 })).toEqual({});
  });

  it("drops a revision of zero as well", () => {
    expect(editable({ id: "c-4", revision: 0, name: "x" })).toEqual({
      name: "x",
    });
  });

  it("keeps falsy business fields that are not identity fields", () => {
    expect(
      editable({ id: "c-5", revision: 3, enabled: false, note: "", count: 0 }),
    ).toEqual({ enabled: false, note: "", count: 0 });
  });

  it("does not mutate the input object", () => {
    const input = { id: "c-6", revision: 9, name: "keep" };
    editable(input);
    expect(input).toEqual({ id: "c-6", revision: 9, name: "keep" });
  });

  it("keeps a field that merely mentions id or revision in its name", () => {
    expect(
      editable({ id: "c-7", revision: 1, model_id: "m-1", revisionNote: "n" }),
    ).toEqual({ model_id: "m-1", revisionNote: "n" });
  });

  it("returns a new object rather than the original reference", () => {
    const input = { id: "c-8", revision: 2, name: "a" };
    expect(editable(input)).not.toBe(input);
  });
});
