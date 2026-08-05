/**
 * wallpapers.ts — Preset desktop wallpapers / themes for the Desktop OS.
 *
 * Each wallpaper is a pure CSS background value (gradient) so no image assets
 * are required and the shell stays theme-consistent. The first entry mirrors
 * the original hard-coded desktop gradient and is the default.
 */

export interface Wallpaper {
  /** Stable id persisted in the wallpaper store. */
  id: string;
  /** i18n key for the display name. */
  labelKey: string;
  /** English fallback name. */
  name: string;
  /** CSS background value applied to the desktop root. */
  background: string;
}

export const WALLPAPERS: Wallpaper[] = [
  {
    id: "aurora",
    labelKey: "os.wp.aurora",
    name: "Aurora",
    background:
      "linear-gradient(135deg, #0b1120 0%, #14162e 50%, #1e1b4b 100%)",
  },
  {
    id: "graphite",
    labelKey: "os.wp.graphite",
    name: "Graphite",
    background:
      "linear-gradient(135deg, #111827 0%, #1f2937 55%, #374151 100%)",
  },
  {
    id: "ocean",
    labelKey: "os.wp.ocean",
    name: "Ocean",
    background:
      "linear-gradient(135deg, #0f172a 0%, #164e63 60%, #0369a1 100%)",
  },
  {
    id: "sunset",
    labelKey: "os.wp.sunset",
    name: "Sunset",
    background:
      "linear-gradient(135deg, #1e1b4b 0%, #7c2d12 60%, #b45309 100%)",
  },
  {
    id: "forest",
    labelKey: "os.wp.forest",
    name: "Forest",
    background:
      "linear-gradient(135deg, #0b1120 0%, #14532d 60%, #166534 100%)",
  },
  {
    id: "rose",
    labelKey: "os.wp.rose",
    name: "Rose",
    background:
      "linear-gradient(135deg, #1e1b4b 0%, #831843 60%, #be185d 100%)",
  },
];

/** Default wallpaper id (matches the original desktop gradient). */
export const DEFAULT_WALLPAPER_ID = WALLPAPERS[0].id;

/** Resolve a wallpaper's CSS background, falling back to the default. */
export function wallpaperBackground(id: string): string {
  const wp = WALLPAPERS.find((w) => w.id === id) ?? WALLPAPERS[0];
  return wp.background;
}
