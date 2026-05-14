import { describe, expect, it } from "vitest";
import {
  getRouterBasename,
  normalizeBasePath,
  stripRuntimeBasePath,
} from "./basePath";

describe("basePath utilities", () => {
  it("normalizes Vite base paths", () => {
    expect(normalizeBasePath("/")).toBe("");
    expect(normalizeBasePath("copaw/test-001/")).toBe("/copaw/test-001");
    expect(normalizeBasePath("/copaw/test-001/")).toBe("/copaw/test-001");
  });

  it("uses configured build base for router basename", () => {
    expect(getRouterBasename("/copaw/test-001/chat", "/copaw/test-001/")).toBe(
      "/copaw/test-001",
    );
  });

  it("preserves legacy /console alias when no build base is configured", () => {
    expect(getRouterBasename("/console/chat", "/")).toBe("/console");
  });

  it("strips runtime base from redirect targets", () => {
    expect(
      stripRuntimeBasePath(
        "/copaw/test-001/chat?session=1",
        "/copaw/test-001/chat",
        "/copaw/test-001/",
      ),
    ).toBe("/chat?session=1");
  });
});
