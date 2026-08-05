import { describe, expect, it } from "vitest";
import {
  dismissDesktopModeHint,
  shouldShowDesktopModeHint,
} from "./desktopModeHint";

describe("desktopModeHint", () => {
  it("shows until the hint is dismissed", () => {
    const storage = new Map<string, string>();
    const adapter = {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
    } as unknown as Storage;

    expect(shouldShowDesktopModeHint(adapter)).toBe(true);
    dismissDesktopModeHint(adapter);
    expect(shouldShowDesktopModeHint(adapter)).toBe(false);
  });

  it("does not interrupt the UI when storage is unavailable", () => {
    const storage = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;

    expect(shouldShowDesktopModeHint(storage)).toBe(false);
    expect(() => dismissDesktopModeHint(storage)).not.toThrow();
  });
});
