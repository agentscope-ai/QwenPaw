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

  it("reflows all visible icons when the viewport grows", () => {
    const ids = Array.from({ length: 12 }, (_, index) => `app.${index}`);
    useOsIcons.getState().arrange(ids, 738);

    useOsIcons.getState().reflowToViewport(ids, 1132);

    expect(useOsIcons.getState().positions["app.0"]).toEqual(
      defaultIconPos(0, 1132),
    );
    expect(useOsIcons.getState().positions["app.6"]).toEqual(
      defaultIconPos(6, 1132),
    );
    expect(useOsIcons.getState().positions["app.11"]).toEqual(
      defaultIconPos(11, 1132),
    );
    expect(useOsIcons.getState().positions["app.6"].x).toBe(20);
  });

  it("reflows all visible icons when the viewport shrinks", () => {
    const ids = Array.from({ length: 12 }, (_, index) => `app.${index}`);
    useOsIcons.getState().arrange(ids, 1132);

    useOsIcons.getState().reflowToViewport(ids, 738);

    expect(useOsIcons.getState().positions["app.0"]).toEqual(
      defaultIconPos(0, 738),
    );
    expect(useOsIcons.getState().positions["app.6"]).toEqual(
      defaultIconPos(6, 738),
    );
    expect(useOsIcons.getState().positions["app.11"]).toEqual(
      defaultIconPos(11, 738),
    );
    expect(useOsIcons.getState().positions["app.6"].x).toBeGreaterThan(20);
  });

  it("preserves hidden app positions while reflowing visible apps", () => {
    useOsIcons.getState().setPosition("core.chat", 500, 300);
    useOsIcons.getState().setPosition("hidden.app", 9000, 9000);

    useOsIcons.getState().reflowToViewport(["core.chat"], 738);

    expect(useOsIcons.getState().positions["core.chat"]).toEqual(
      defaultIconPos(0, 738),
    );
    expect(useOsIcons.getState().positions["hidden.app"]).toEqual({
      x: 9000,
      y: 9000,
    });
  });

  it("does not rewrite saved free positions in a sorted layout", () => {
    useOsIcons.getState().setPosition("core.chat", 20, 888);
    useOsIcons.getState().setLayout("name");

    useOsIcons.getState().reflowToViewport(["core.chat"], 738);

    expect(useOsIcons.getState().positions["core.chat"]).toEqual({
      x: 20,
      y: 888,
    });
  });
});
