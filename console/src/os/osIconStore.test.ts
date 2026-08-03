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
    useOsIcons.getState().setLayout("name");
    useOsIcons.getState().reset();
    expect(useOsIcons.getState().positions).toEqual({});
    expect(useOsIcons.getState().layout).toBe("free");
  });

  it("purge drops positions for confirmed-removed apps only", () => {
    useOsIcons.getState().setPosition("core.chat", 1, 2);
    useOsIcons.getState().setPosition("gone.app", 3, 4);
    useOsIcons.getState().purge(new Set(["gone.app"]));
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

  it("arranges visible ids without deleting hidden app positions", () => {
    useOsIcons.getState().setPosition("hidden.app", 700, 300);
    useOsIcons.getState().arrange(["core.chat", "core.inbox"], 800);

    expect(useOsIcons.getState().positions).toEqual({
      "hidden.app": { x: 700, y: 300 },
      "core.chat": defaultIconPos(0, 800),
      "core.inbox": defaultIconPos(1, 800),
    });
  });
});
