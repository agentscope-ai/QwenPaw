import { describe, it, expect, beforeEach } from "vitest";
import { useOsIcons, defaultIconPos } from "./osIconStore";

describe("osIconStore", () => {
  beforeEach(() => {
    useOsIcons.getState().reset();
  });

  it("stores a position by route id", () => {
    useOsIcons.getState().setPosition("core.chat", 120, 240);
    expect(useOsIcons.getState().positions["core.chat"]).toEqual({
      x: 120,
      y: 240,
    });
  });

  it("reset clears all positions", () => {
    useOsIcons.getState().setPosition("core.chat", 1, 2);
    useOsIcons.getState().reset();
    expect(useOsIcons.getState().positions).toEqual({});
  });

  it("prune drops positions for apps missing from the registry", () => {
    useOsIcons.getState().setPosition("core.chat", 1, 2);
    useOsIcons.getState().setPosition("gone.app", 3, 4);
    useOsIcons.getState().prune(new Set(["core.chat"]));
    expect(useOsIcons.getState().positions).toEqual({
      "core.chat": { x: 1, y: 2 },
    });
  });

  it("defaultIconPos lays out column-major with a fixed step", () => {
    const first = defaultIconPos(0, 800);
    const second = defaultIconPos(1, 800);
    expect(second.y).toBe(first.y + 104);
    expect(second.x).toBe(first.x);
  });
});
