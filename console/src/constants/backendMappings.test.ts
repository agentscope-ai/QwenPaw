/**
 * Tests for constants/backendMappings.
 *
 * Covers:
 * - CONTEXT_MANAGER_BACKEND_MAPPINGS structure
 * - MEMORY_MANAGER_BACKEND_MAPPINGS structure
 * - Derived OPTIONS arrays
 */
import { describe, it, expect, vi } from "vitest";

// Mock the React component imports — we only test data shape, not rendering
vi.mock("../pages/Agent/Config/components/LightContextCard", () => ({
  LightContextCard: () => null,
}));
vi.mock("../pages/Agent/Config/components/ReMeLightMemoryCard", () => ({
  ReMeLightMemoryCard: () => null,
}));
vi.mock("../pages/Agent/Config/components/ADBPGConfigCard", () => ({
  ADBPGConfigCard: () => null,
}));

import {
  CONTEXT_MANAGER_BACKEND_MAPPINGS,
  MEMORY_MANAGER_BACKEND_MAPPINGS,
  CONTEXT_MANAGER_BACKEND_OPTIONS,
  MEMORY_MANAGER_BACKEND_OPTIONS,
} from "./backendMappings";

describe("CONTEXT_MANAGER_BACKEND_MAPPINGS", () => {
  it("has expected keys", () => {
    expect(Object.keys(CONTEXT_MANAGER_BACKEND_MAPPINGS)).toContain("light");
  });

  it("each mapping has configField, label, and tabKey", () => {
    for (const [, mapping] of Object.entries(
      CONTEXT_MANAGER_BACKEND_MAPPINGS,
    )) {
      expect(mapping).toHaveProperty("configField");
      expect(mapping).toHaveProperty("label");
      expect(mapping).toHaveProperty("tabKey");
      expect(typeof mapping.configField).toBe("string");
      expect(typeof mapping.label).toBe("string");
      expect(typeof mapping.tabKey).toBe("string");
    }
  });
});

describe("MEMORY_MANAGER_BACKEND_MAPPINGS", () => {
  it("has expected keys", () => {
    expect(Object.keys(MEMORY_MANAGER_BACKEND_MAPPINGS)).toContain("remelight");
    expect(Object.keys(MEMORY_MANAGER_BACKEND_MAPPINGS)).toContain("adbpg");
  });

  it("each mapping has configField, label, and tabKey", () => {
    for (const [, mapping] of Object.entries(MEMORY_MANAGER_BACKEND_MAPPINGS)) {
      expect(mapping).toHaveProperty("configField");
      expect(mapping).toHaveProperty("label");
      expect(mapping).toHaveProperty("tabKey");
    }
  });
});

describe("CONTEXT_MANAGER_BACKEND_OPTIONS", () => {
  it("is derived from CONTEXT_MANAGER_BACKEND_MAPPINGS", () => {
    expect(CONTEXT_MANAGER_BACKEND_OPTIONS.length).toBe(
      Object.keys(CONTEXT_MANAGER_BACKEND_MAPPINGS).length,
    );
  });

  it("each option has value and label", () => {
    for (const opt of CONTEXT_MANAGER_BACKEND_OPTIONS) {
      expect(opt).toHaveProperty("value");
      expect(opt).toHaveProperty("label");
    }
  });
});

describe("MEMORY_MANAGER_BACKEND_OPTIONS", () => {
  it("is derived from MEMORY_MANAGER_BACKEND_MAPPINGS", () => {
    expect(MEMORY_MANAGER_BACKEND_OPTIONS.length).toBe(
      Object.keys(MEMORY_MANAGER_BACKEND_MAPPINGS).length,
    );
  });
});
