import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import React from "react";

import {
  calculateReserveThreshold,
  usesTieredToolResultSettings,
} from "./toolResultSettings";

describe("usesTieredToolResultSettings", () => {
  it("hides old-preview tiers for Scroll", () => {
    expect(usesTieredToolResultSettings("scroll")).toBe(false);
    expect(usesTieredToolResultSettings(undefined)).toBe(false);
  });

  it("shows old-preview tiers for Native context", () => {
    expect(usesTieredToolResultSettings("native")).toBe(true);
  });
});

describe("calculateReserveThreshold", () => {
  it("applies Scroll's bounded recent-tail budget", () => {
    expect(calculateReserveThreshold(128_000, 0.1, "scroll")).toBe(12_800);
    expect(calculateReserveThreshold(1_000_000, 0.1, "scroll")).toBe(40_000);
    expect(calculateReserveThreshold(32_000, 0.01, "scroll")).toBe(3_200);
  });

  it("uses the configured ratio directly for Native context", () => {
    expect(calculateReserveThreshold(1_000_000, 0.1, "native")).toBe(100_000);
  });
});

// ---------------------------------------------------------------------------
// historyRetentionDays warning logic — regression for A#80646153
// The Form.Item only has `required` validation (no min/max), so any numeric
// value passes validation. Warnings are non-blocking hints:
// - <= 0: "forever" warning
// - > 30: "large window" warning
// - 1..30: no warning
// ---------------------------------------------------------------------------

vi.mock("@agentscope-ai/design", () => {
  const passThrough = ({ children, ...props }: Record<string, unknown>) =>
    React.createElement("div", props, children as any);

  // Form.useWatch returns values from a map keyed by the path array joined
  const watchValues: Record<string, unknown> = {};
  const Form = Object.assign(passThrough, {
    Item: ({ extra, children, ...props }: Record<string, unknown>) =>
      React.createElement(
        "div",
        props,
        children as any,
        extra
          ? React.createElement(
              "span",
              { "data-testid": "warning" },
              extra as any,
            )
          : null,
      ),
    useForm: () => [{}],
    useWatch: (path: string[]) => watchValues[path.join(".")],
    _setWatchValues: (values: Record<string, unknown>) => {
      Object.keys(watchValues).forEach((k) => delete watchValues[k]);
      Object.assign(watchValues, values);
    },
  });

  return {
    Form,
    Card: passThrough,
    Switch: passThrough,
    Input: passThrough,
    Collapse: ({ items }: Record<string, unknown>) =>
      React.createElement(
        "div",
        null,
        (
          items as Array<{
            key: string;
            label: string;
            children: React.ReactNode;
          }>
        ).map((item) =>
          React.createElement(
            "div",
            { key: item.key },
            item.label,
            item.children,
          ),
        ),
      ),
    Select: passThrough,
    InputNumber: (props: Record<string, unknown>) =>
      React.createElement("input", { type: "number", ...props } as any),
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("./SliderWithValue", () => ({
  SliderWithValue: () => React.createElement("div"),
}));

vi.mock("./VisualCompactSettings", () => ({
  VisualCompactSettings: () => React.createElement("div"),
}));

vi.mock("../index.module.less", () => ({
  default: new Proxy({}, { get: (_t, prop) => String(prop) }),
}));

import { Form } from "@agentscope-ai/design";
import { LightContextCard } from "./LightContextCard";

function renderWithRetention(days: number | undefined) {
  const form = Form as any;
  form._setWatchValues({
    "light_context_config.strategy": "scroll",
    "light_context_config.context_compact_config.compact_threshold_ratio": 0.8,
    "light_context_config.context_compact_config.reserve_threshold_ratio": 0.1,
    "light_context_config.scroll_config.history_retention_days": days,
  });
  return render(
    React.createElement(LightContextCard, { maxInputLength: 128000 }),
  );
}

describe("historyRetentionDays warning (A#80646153)", () => {
  it("does not trigger validation error or warning for days=11", () => {
    renderWithRetention(11);
    // No warning should appear for values between 1 and 30
    expect(screen.queryByTestId("warning")).not.toBeInTheDocument();
  });

  it("does not trigger large warning for days=30 (boundary: >30 triggers)", () => {
    renderWithRetention(30);
    // 30 is NOT > 30, so no large warning
    expect(screen.queryByTestId("warning")).not.toBeInTheDocument();
  });

  it("triggers large warning for days=31 (non-blocking)", () => {
    renderWithRetention(31);
    const warning = screen.getByTestId("warning");
    expect(warning).toBeInTheDocument();
    expect(warning.textContent).toContain("historyRetentionDaysLargeWarning");
  });

  it("triggers forever warning for days=0", () => {
    renderWithRetention(0);
    const warning = screen.getByTestId("warning");
    expect(warning).toBeInTheDocument();
    expect(warning.textContent).toContain("historyRetentionDaysForeverWarning");
  });
});
