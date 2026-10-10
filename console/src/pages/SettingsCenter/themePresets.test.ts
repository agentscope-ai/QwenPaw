import { describe, expect, it } from "vitest";

import {
  applyThemePreset,
  getThemePresetId,
  THEME_PRESETS,
} from "./themePresets";

describe("theme presets", () => {
  it("offers the reference-inspired color palettes", () => {
    expect(THEME_PRESETS.map((preset) => preset.name)).toEqual([
      "QwenPaw",
      "Codex",
      "Ayu",
      "Catppuccin",
      "Dracula",
      "Everforest",
    ]);
  });

  it("applies colors without changing the corner radius", () => {
    const theme = applyThemePreset({ radius: "12px" }, "codex");

    expect(theme.radius).toBe("12px");
    expect(theme.accent).toBe("#2563eb");
    expect(theme.dark?.surface).toBe("#181818");
  });

  it("recognizes defaults, presets and custom colors", () => {
    expect(getThemePresetId({})).toBe("qwenpaw");
    expect(getThemePresetId(applyThemePreset({}, "dracula"))).toBe("dracula");
    expect(getThemePresetId({ accent: "#123456" })).toBeUndefined();
  });
});
