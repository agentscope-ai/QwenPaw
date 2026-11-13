/**
 * osWallpaperStore.ts — Persisted desktop wallpaper selection for the OS shell.
 *
 * Tracks the chosen wallpaper id (see wallpapers.ts). Persisted to
 * localStorage so the desktop keeps its look across reloads.
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";
import { DEFAULT_WALLPAPER_ID } from "./wallpapers";

interface WallpaperStore {
  /** Currently selected wallpaper id. */
  wallpaperId: string;
  /** Select a wallpaper by id. */
  setWallpaper: (id: string) => void;
}

export const useOsWallpaper = create<WallpaperStore>()(
  persist(
    (set) => ({
      wallpaperId: DEFAULT_WALLPAPER_ID,
      setWallpaper: (id) => set({ wallpaperId: id }),
    }),
    { name: "qwenpaw-os-wallpaper" },
  ),
);
