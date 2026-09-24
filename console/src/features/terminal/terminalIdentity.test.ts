import { describe, expect, it } from "vitest";
import { migrateTerminalGroup, terminalGroup } from "./terminalIdentity";

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
});
