import { describe, expect, it } from "vitest";
import { runtimeContextEqual } from "./runtimeContextEqual";

describe("runtimeContextEqual", () => {
  const context = {
    project_dir: "/old",
    project_dirs: [{ path: "/project", label: "Project" }],
    model_slot_override: { provider_id: "provider", model: "model" },
  };

  it("compares independently loaded values regardless of key order", () => {
    expect(
      runtimeContextEqual(context, {
        model_slot_override: { model: "model", provider_id: "provider" },
        project_dirs: [{ label: "Project", path: "/project" }],
        project_dir: "/old",
      }),
    ).toBe(true);
    expect(runtimeContextEqual(null, undefined)).toBe(true);
  });

  it.each([
    { project_dir: "/other" },
    { project_dirs: [] },
    { project_dirs: [{ path: "/other", label: "Project" }] },
    { project_dirs: [{ path: "/project", label: "Other" }] },
    { model_slot_override: null },
    { model_slot_override: { provider_id: "other", model: "model" } },
    { model_slot_override: { provider_id: "provider", model: "other" } },
  ])("detects UI-visible changes: %j", (change) => {
    expect(runtimeContextEqual(context, { ...context, ...change })).toBe(false);
  });

  it("never serializes or traverses unrelated plugin payloads", () => {
    const value = {
      ...context,
      toJSON() {
        throw new Error("serialized");
      },
    };
    Object.defineProperty(value, "plugin_payload", {
      get() {
        throw new Error("read");
      },
    });
    expect(runtimeContextEqual(value, { ...context })).toBe(true);
  });
});
