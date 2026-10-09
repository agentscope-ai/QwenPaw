import { afterEach, describe, expect, it, vi } from "vitest";
import { migrateTerminalGroup, terminalGroup } from "./terminalIdentity";

const getRandomValues = crypto.getRandomValues.bind(crypto);

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("terminal conversation identity", () => {
  it("uses the native UUID generator when available", () => {
    const uuid = "12345678-1234-4123-8123-123456789abc";
    const randomUUID = vi.fn(() => uuid);
    vi.stubGlobal("crypto", { randomUUID });

    expect(terminalGroup("native-agent", "chat")).toBe(uuid);
    expect(randomUUID).toHaveBeenCalledOnce();
  });

  it("sets the UUID version and variant when randomUUID is unavailable", () => {
    vi.stubGlobal("crypto", {
      getRandomValues: (bytes: Uint8Array) => bytes.fill(255),
    });

    expect(terminalGroup("fallback-format-agent", "chat")).toBe(
      "ffffffff-ffff-4fff-bfff-ffffffffffff",
    );
  });

  it("restores a fallback UUID from session storage after reload", async () => {
    vi.stubGlobal("crypto", { getRandomValues });
    const original = terminalGroup("fallback-storage-agent", "chat");
    expect(original).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );

    vi.resetModules();
    const reloaded = await import("./terminalIdentity");
    expect(reloaded.terminalGroup("fallback-storage-agent", "chat")).toBe(
      original,
    );
  });

  it("reuses, isolates, and migrates groups without randomUUID", () => {
    vi.stubGlobal("crypto", { getRandomValues });
    const original = terminalGroup("fallback-agent", "new");

    expect(terminalGroup("fallback-agent", "new")).toBe(original);
    expect(terminalGroup("fallback-other-agent", "new")).not.toBe(original);
    expect(terminalGroup("fallback-agent", "another")).not.toBe(original);
    migrateTerminalGroup("fallback-agent", "new", "persisted");
    expect(terminalGroup("fallback-agent", "persisted")).toBe(original);
    expect(terminalGroup("fallback-agent", "new")).not.toBe(original);
  });

  it("keeps the PTY group through both stages of draft allocation", () => {
    const original = terminalGroup("migration-agent", "new");
    migrateTerminalGroup("migration-agent", "new", "temporary");
    migrateTerminalGroup("migration-agent", "temporary", "persisted");
    expect(terminalGroup("migration-agent", "persisted")).toBe(original);
    expect(terminalGroup("migration-agent", "new")).not.toBe(original);
  });

  it("isolates different agents and conversations", () => {
    const first = terminalGroup("a", "chat");
    expect(terminalGroup("a", "chat")).toBe(first);
    expect(terminalGroup("b", "chat")).not.toBe(first);
    expect(terminalGroup("a", "another")).not.toBe(first);
    migrateTerminalGroup("a", "chat", "chat");
    expect(terminalGroup("a", "chat")).toBe(first);
  });
});
