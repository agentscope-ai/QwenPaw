import { afterEach, describe, expect, it } from "vitest";
import { migrateTerminalGroup, terminalGroup } from "./terminalIdentity";

const originalRandomUUID = crypto.randomUUID;
const originalGetRandomValues = crypto.getRandomValues;

afterEach(() => {
  Object.defineProperty(crypto, "randomUUID", {
    value: originalRandomUUID,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(crypto, "getRandomValues", {
    value: originalGetRandomValues,
    configurable: true,
    writable: true,
  });
});

describe("terminal conversation identity", () => {
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

  it("creates a valid UUID when crypto.randomUUID is unavailable", () => {
    Object.defineProperty(crypto, "randomUUID", {
      value: undefined,
      configurable: true,
      writable: true,
    });
    let generated = 0;
    Object.defineProperty(crypto, "getRandomValues", {
      value: (bytes: Uint8Array) => {
        bytes.fill(generated++ === 0 ? 0x11 : 0x22);
        return bytes;
      },
      configurable: true,
      writable: true,
    });

    const group = terminalGroup("insecure-context-agent", "session");

    expect(group).toBe("11111111-1111-4111-9111-111111111111");
    expect(terminalGroup("insecure-context-agent", "session")).toBe(group);
    expect(terminalGroup("insecure-context-agent", "another-session")).toBe(
      "22222222-2222-4222-a222-222222222222",
    );
  });
});
