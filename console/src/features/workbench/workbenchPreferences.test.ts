import { afterEach, describe, expect, it } from "vitest";
import {
  migrateWorkbenchPreferences,
  workbenchTabStorageKey,
  workbenchWidthStorageKey,
} from "./workbenchPreferences";

describe("workbenchPreferences", () => {
  afterEach(() => localStorage.clear());

  it("migrates temporary session preferences to the resolved session", () => {
    localStorage.setItem(workbenchTabStorageKey("agent-a", "new"), "terminal");
    localStorage.setItem(workbenchWidthStorageKey("agent-a", "new"), "720");

    migrateWorkbenchPreferences("agent-a", "new", "chat-1");

    expect(
      localStorage.getItem(workbenchTabStorageKey("agent-a", "chat-1")),
    ).toBe("terminal");
    expect(
      localStorage.getItem(workbenchWidthStorageKey("agent-a", "chat-1")),
    ).toBe("720");
    expect(
      localStorage.getItem(workbenchTabStorageKey("agent-a", "new")),
    ).toBeNull();
    expect(
      localStorage.getItem(workbenchWidthStorageKey("agent-a", "new")),
    ).toBeNull();
  });

  it("does not overwrite preferences already stored for the target", () => {
    localStorage.setItem(workbenchTabStorageKey("agent-a", "new"), "tools");
    localStorage.setItem(workbenchTabStorageKey("agent-a", "chat-1"), "files");

    migrateWorkbenchPreferences("agent-a", "new", "chat-1");

    expect(
      localStorage.getItem(workbenchTabStorageKey("agent-a", "chat-1")),
    ).toBe("files");
    expect(
      localStorage.getItem(workbenchTabStorageKey("agent-a", "new")),
    ).toBeNull();
  });
});
