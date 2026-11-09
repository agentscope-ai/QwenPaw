/**
 * Tests for the persisted desktop wallpaper store.
 *
 * The store is the single source of truth for the wallpaper id that
 * DesktopOS renders and WallpaperPicker writes. Two contracts matter:
 *   - the initial id must be the preset default, otherwise a first-run
 *     desktop would resolve to an unknown background;
 *   - the persisted key is part of the on-disk format, so a rename would
 *     silently drop every user's saved choice.
 *
 * The store deliberately stores whatever id it is given: unknown ids are
 * tolerated on purpose because wallpaperBackground() already falls back to
 * the default gradient, so the picker never has to validate first.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { DEFAULT_WALLPAPER_ID, WALLPAPERS } from "./wallpapers";
import { useOsWallpaper } from "./osWallpaperStore";

const PERSIST_KEY = "qwenpaw-os-wallpaper";

beforeEach(() => {
  localStorage.clear();
  useOsWallpaper.setState({ wallpaperId: DEFAULT_WALLPAPER_ID });
});

describe("osWallpaperStore", () => {
  it("starts on the default preset wallpaper", () => {
    expect(useOsWallpaper.getState().wallpaperId).toBe(DEFAULT_WALLPAPER_ID);
    expect(WALLPAPERS.map((w) => w.id)).toContain(DEFAULT_WALLPAPER_ID);
  });

  it("selects a wallpaper by id", () => {
    const other = WALLPAPERS.find((w) => w.id !== DEFAULT_WALLPAPER_ID);

    useOsWallpaper.getState().setWallpaper(other!.id);

    expect(useOsWallpaper.getState().wallpaperId).toBe(other!.id);
  });

  it("allows re-selecting the current wallpaper without changing it", () => {
    useOsWallpaper.getState().setWallpaper(DEFAULT_WALLPAPER_ID);

    expect(useOsWallpaper.getState().wallpaperId).toBe(DEFAULT_WALLPAPER_ID);
  });

  it("keeps an unknown id verbatim so the background can fall back", () => {
    useOsWallpaper.getState().setWallpaper("no-such-wallpaper");

    expect(useOsWallpaper.getState().wallpaperId).toBe("no-such-wallpaper");
  });

  it("persists under the stable storage key", () => {
    useOsWallpaper
      .getState()
      .setWallpaper(WALLPAPERS[WALLPAPERS.length - 1].id);

    const raw = localStorage.getItem(PERSIST_KEY);

    expect(raw).not.toBeNull();
    expect(JSON.parse(raw!).state.wallpaperId).toBe(
      useOsWallpaper.getState().wallpaperId,
    );
  });

  it("exposes setWallpaper as part of the store state", () => {
    expect(typeof useOsWallpaper.getState().setWallpaper).toBe("function");
  });
});
