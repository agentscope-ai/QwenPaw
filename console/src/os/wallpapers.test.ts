import { describe, expect, it } from "vitest";
import {
  DEFAULT_WALLPAPER_ID,
  WALLPAPERS,
  wallpaperBackground,
} from "./wallpapers";

describe("WALLPAPERS catalogue", () => {
  it("ships six presets with unique ids", () => {
    expect(WALLPAPERS).toHaveLength(6);
    const ids = WALLPAPERS.map((w) => w.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("gives every entry a css gradient and an os.wp.* label key", () => {
    for (const w of WALLPAPERS) {
      expect(w.background).toMatch(/^linear-gradient\(/);
      expect(w.labelKey).toMatch(/^os\.wp\./);
      expect(w.name.length).toBeGreaterThan(0);
    }
  });

  it("defaults to the first entry, mirroring the original desktop gradient", () => {
    expect(DEFAULT_WALLPAPER_ID).toBe("aurora");
    expect(DEFAULT_WALLPAPER_ID).toBe(WALLPAPERS[0].id);
  });
});

describe("wallpaperBackground", () => {
  it("returns each preset's own background when looked up by id", () => {
    for (const w of WALLPAPERS) {
      expect(wallpaperBackground(w.id)).toBe(w.background);
    }
  });

  it("falls back to the first preset for an unknown id", () => {
    expect(wallpaperBackground("does-not-exist")).toBe(
      WALLPAPERS[0].background,
    );
  });

  it("falls back to the first preset for an empty id", () => {
    expect(wallpaperBackground("")).toBe(WALLPAPERS[0].background);
  });
});
