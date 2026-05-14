/**
 * Tests for api/types.
 *
 * Covers:
 * - Barrel re-export completeness
 * - Type constant values (ACP, backup)
 * - isFullBackup() function
 * - Channel type structure
 * - Skill type structure
 */
import { describe, it, expect } from "vitest";

// --- Barrel re-exports ---
import * as types from "./index";

describe("api/types barrel exports", () => {
  it("exports ACP types", () => {
    expect(types.ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES).toBeDefined();
  });

  it("exports backup types", () => {
    expect(typeof types.isFullBackup).toBe("function");
  });

  it("exports channel types", () => {
    // Channel types are interfaces — just verify the module loaded
    expect(types).toBeDefined();
  });

  it("exports skill types", () => {
    expect(types).toBeDefined();
  });
});

// --- ACP constants ---
describe("ACP constants", () => {
  it("ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES is 50MB", () => {
    expect(types.ACP_DEFAULT_STDIO_BUFFER_LIMIT_BYTES).toBe(50 * 1024 * 1024);
  });
});

// --- isFullBackup ---
import { isFullBackup } from "./backup";
import type { BackupScope } from "./backup";

describe("isFullBackup", () => {
  const fullScope: BackupScope = {
    include_agents: true,
    include_global_config: true,
    include_secrets: true,
    include_skill_pool: true,
  };

  it("returns true when all scope flags are true", () => {
    expect(isFullBackup(fullScope)).toBe(true);
  });

  it("returns false when include_agents is false", () => {
    expect(isFullBackup({ ...fullScope, include_agents: false })).toBe(false);
  });

  it("returns false when include_global_config is false", () => {
    expect(isFullBackup({ ...fullScope, include_global_config: false })).toBe(
      false,
    );
  });

  it("returns false when include_secrets is false", () => {
    expect(isFullBackup({ ...fullScope, include_secrets: false })).toBe(false);
  });

  it("returns false when include_skill_pool is false", () => {
    expect(isFullBackup({ ...fullScope, include_skill_pool: false })).toBe(
      false,
    );
  });

  it("returns false when all flags are false", () => {
    expect(
      isFullBackup({
        include_agents: false,
        include_global_config: false,
        include_secrets: false,
        include_skill_pool: false,
      }),
    ).toBe(false);
  });
});
