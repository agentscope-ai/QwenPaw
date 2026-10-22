/**
 * lineChartChrome - the shared chart "chrome" builder behind every token-usage
 * line chart. Four callers spread its return value into a Line config:
 * TokenUsage/index.tsx, hooks/useTokenTypeConfig.ts, hooks/useModelTrendConfig.ts
 * and Hub/governance/ModelUsage.tsx. A field dropped here silently changes all
 * four charts, so this file pins the returned object field by field.
 *
 * What this file pins:
 *   1. the static contract callers rely on: fixed x/y field names ("date" and
 *      "value"), seriesField driving BOTH seriesField and colorField, the
 *      smooth/autoFit/height trio, the line style, the x-axis range+nice+grid
 *      and the tooltip title;
 *   2. theme switching from isDark, and the grid stroke derived from the SAME
 *      flag so the grid can never disagree with the theme;
 *   3. the conditional color key: absent (not merely undefined) when no palette
 *      is passed, and an exact copy of the palette when one is;
 *   4. legend defaults (top / circle) being overridable through the caller
 *      spread, which is what lets one caller move the legend without touching
 *      the rest of the config;
 *   5. the x label formatter switching between "MM-DD" and "YY/MM-DD" purely on
 *      whether the range crosses a year boundary;
 *   6. the y label formatter, which uses its OWN three-band compaction rather
 *      than utils/formatCompact: 999 -> "999", 1000 -> "1K", 1000000 -> "1.0M",
 *      2500000 -> "2.5M". The 999999 -> "1000K" result asserted below is
 *      CURRENT BEHAVIOUR pinned on purpose (this formatter has no promotion
 *      guard, unlike formatCompact); it is not an endorsed axis label;
 *   7. the tooltip item builder: it reads datum[seriesField] (parametric, so a
 *      different seriesField reads a different key) and formats datum.value
 *      through formatCompact, with "" for a missing series value and 0 for a
 *      missing or non-numeric value.
 *
 * No React harness is needed: this is a pure builder, so the assertions call it
 * directly and read the returned config object.
 */
import { describe, it, expect } from "vitest";
import dayjs from "dayjs";
import { lineChartChrome } from "./lineChartChrome";
import { formatCompact } from "../../../../utils/formatNumber";

type ChromeOptions = Parameters<typeof lineChartChrome>[0];

function chrome(overrides: Partial<ChromeOptions> = {}) {
  return lineChartChrome({
    isDark: false,
    tickCount: 5,
    startDate: dayjs("2026-10-01"),
    endDate: dayjs("2026-10-03"),
    seriesField: "model",
    ...overrides,
  });
}

function asRecord(value: unknown): Record<string, unknown> {
  return value as Record<string, unknown>;
}

describe("lineChartChrome static contract", () => {
  it("fixes the axis field names and derives colorField from seriesField", () => {
    const config = chrome();
    expect(config.xField).toBe("date");
    expect(config.yField).toBe("value");
    expect(config.seriesField).toBe("model");
    // colorField is not a literal: it follows whatever seriesField is given.
    expect(config.colorField).toBe("model");
    const byProvider = chrome({ seriesField: "provider" });
    expect(byProvider.seriesField).toBe("provider");
    expect(byProvider.colorField).toBe("provider");
  });

  it("keeps the drawing options every caller depends on", () => {
    const config = chrome();
    expect(config.smooth).toBe(true);
    expect(config.autoFit).toBe(true);
    expect(config.height).toBe(300);
    expect(config.style).toEqual({ lineWidth: 3, fillOpacity: 0 });
  });

  it("keeps the x-axis range, nice flag and null grid", () => {
    const axisX = chrome().axis.x;
    expect(axisX.range).toEqual([0, 1]);
    expect(axisX.nice).toBe(true);
    expect(axisX.grid).toBeNull();
  });

  it("passes tickCount through to the x axis", () => {
    expect(chrome({ tickCount: 5 }).axis.x.tickCount).toBe(5);
    expect(chrome({ tickCount: 12 }).axis.x.tickCount).toBe(12);
  });

  it("exposes exactly one tooltip item builder titled by the date field", () => {
    const tooltip = chrome().tooltip;
    expect(tooltip.title).toBe("date");
    expect(tooltip.items).toHaveLength(1);
    expect(typeof tooltip.items[0]).toBe("function");
  });
});

describe("lineChartChrome theme and grid", () => {
  it("maps isDark to the theme name", () => {
    expect(chrome({ isDark: false }).theme).toBe("light");
    expect(chrome({ isDark: true }).theme).toBe("dark");
  });

  it("derives the y grid stroke from the same isDark flag as the theme", () => {
    const light = chrome({ isDark: false });
    const dark = chrome({ isDark: true });
    expect(light.theme).toBe("light");
    expect(dark.theme).toBe("dark");
    expect(light.axis.y.grid).toEqual({
      line: { style: { stroke: "rgba(0, 0, 0, 0.04)" } },
    });
    expect(dark.axis.y.grid).toEqual({
      line: { style: { stroke: "rgba(255, 255, 255, 0.05)" } },
    });
  });
});

describe("lineChartChrome optional keys", () => {
  it("omits the color key entirely when no palette is passed", () => {
    const config = chrome();
    // Absent, not undefined: callers spread this object, and an explicit
    // undefined would still create the key in the resulting chart config.
    expect("color" in config).toBe(false);
  });

  it("copies the palette verbatim when one is passed", () => {
    const palette = ["#1f77b4", "#ff7f0e"];
    const config = asRecord(chrome({ colors: palette }));
    expect("color" in config).toBe(true);
    expect(config.color).toEqual(["#1f77b4", "#ff7f0e"]);
  });

  it("seeds the legend defaults", () => {
    expect(chrome().legend).toEqual({
      position: "top",
      itemMarker: "circle",
    });
  });

  it("lets a caller legend spread override the defaults", () => {
    const config = chrome({
      legend: { position: "left", itemMarker: "square" },
    });
    expect(config.legend).toEqual({ position: "left", itemMarker: "square" });
  });
});

describe("lineChartChrome x label formatter", () => {
  it("uses MM-DD when start and end fall in the same year", () => {
    const format = chrome({
      startDate: dayjs("2026-10-01"),
      endDate: dayjs("2026-10-03"),
    }).axis.x.labelFormatter;
    expect(format("2026-10-01")).toBe("10-01");
    expect(format("2026-10-03")).toBe("10-03");
  });

  it("switches to YY/MM-DD when the range crosses a year boundary", () => {
    const format = chrome({
      startDate: dayjs("2025-12-30"),
      endDate: dayjs("2026-01-02"),
    }).axis.x.labelFormatter;
    expect(format("2025-12-30")).toBe("25/12-30");
    expect(format("2026-01-02")).toBe("26/01-02");
  });
});

describe("lineChartChrome y label formatter", () => {
  it("keeps values under one thousand verbatim", () => {
    const format = chrome().axis.y.labelFormatter;
    expect(format(0)).toBe("0");
    expect(format(7)).toBe("7");
    expect(format(999)).toBe("999");
  });

  it("compacts the thousands band without decimals", () => {
    const format = chrome().axis.y.labelFormatter;
    expect(format(1000)).toBe("1K");
    expect(format(1500)).toBe("2K");
  });

  it("compacts the millions band with one decimal", () => {
    const format = chrome().axis.y.labelFormatter;
    expect(format(1000000)).toBe("1.0M");
    expect(format(2500000)).toBe("2.5M");
  });

  it("pins the current non-compact label just under one million", () => {
    // 999999 / 1000 rounds to 1000, so the label reads "1000K". This formatter
    // has no promotion guard (utils/formatCompact does), so the assertion keeps
    // the behaviour visible instead of letting it change unnoticed.
    expect(chrome().axis.y.labelFormatter(999999)).toBe("1000K");
  });
});

describe("lineChartChrome tooltip item builder", () => {
  it("names the item after the configured series field and compacts the value", () => {
    const build = chrome().tooltip.items[0];
    expect(build({ model: "qwen-max", value: 1500 })).toEqual({
      name: "qwen-max",
      value: "1.5K",
    });
  });

  it("reads the series key parametrically", () => {
    const build = chrome({ seriesField: "provider" }).tooltip.items[0];
    // A "model" key must NOT be picked up once seriesField points elsewhere.
    expect(
      build({ provider: "dashscope", model: "ignored", value: 42 }),
    ).toEqual({ name: "dashscope", value: "42" });
    expect(build({ model: "ignored", value: 42 })).toEqual({
      name: "",
      value: "42",
    });
  });

  it("falls back to an empty name when the series value is missing", () => {
    const build = chrome().tooltip.items[0];
    expect(build({ value: 42 })).toEqual({ name: "", value: "42" });
  });

  it("falls back to zero when the value is missing or not numeric", () => {
    const build = chrome().tooltip.items[0];
    expect(build({ model: "m" })).toEqual({ name: "m", value: "0" });
    expect(build({ model: "m", value: "abc" })).toEqual({
      name: "m",
      value: "0",
    });
  });

  it("agrees with formatCompact for the values a chart actually plots", () => {
    const build = chrome().tooltip.items[0];
    for (const value of [0, 42, 1500, 250000, 1000000, 2500000]) {
      expect(build({ model: "m", value }).value).toBe(formatCompact(value));
    }
  });
});
