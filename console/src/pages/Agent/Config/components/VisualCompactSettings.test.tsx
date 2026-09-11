import React from "react";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  enabled: true,
  effort: "low",
}));

vi.mock("@agentscope-ai/design", async () => {
  const ReactModule = await import("react");
  const Item = ({ children }: { children?: React.ReactNode }) =>
    ReactModule.createElement("div", null, children);
  const Form = {
    Item,
    useWatch: (path: string[]) =>
      path[path.length - 1] === "enabled" ? state.enabled : state.effort,
  };
  const Switch = () =>
    ReactModule.createElement("input", {
      type: "checkbox",
      role: "switch",
    });
  return { Form, Switch };
});

vi.mock("antd", async () => {
  const ReactModule = await import("react");
  const TypographyElement = ({ children }: { children?: React.ReactNode }) =>
    ReactModule.createElement("span", null, children);
  return {
    Segmented: ({
      options,
      disabled,
      "aria-label": ariaLabel,
    }: {
      options: Array<{ label: string }>;
      disabled?: boolean;
      "aria-label"?: string;
    }) =>
      ReactModule.createElement(
        "div",
        {
          "aria-disabled": disabled,
          "aria-label": ariaLabel,
          role: "radiogroup",
        },
        options.map((option) =>
          ReactModule.createElement(
            "span",
            { key: option.label },
            option.label,
          ),
        ),
      ),
    Typography: {
      Paragraph: TypographyElement,
      Text: TypographyElement,
    },
  };
});

const translations: Record<string, string> = {
  "agentConfig.visualCompactDescription": "将较早的上下文压缩为视觉页面。",
  "agentConfig.visualCompactEnabled": "启用视觉压缩",
  "agentConfig.visualCompactEffort": "压缩强度",
  "agentConfig.visualCompactLow": "低",
  "agentConfig.visualCompactMedium": "中",
  "agentConfig.visualCompactHigh": "高",
  "agentConfig.visualCompactLowDescription": "优先保证可读性。",
  "agentConfig.visualCompactMediumDescription": "平衡节省与可读性。",
  "agentConfig.visualCompactHighDescription": "优先节省 Token。",
  "agentConfig.visualCompactQualityNote": "压缩强度不代表回答质量。",
  "agentConfig.visualCompactCapabilityNote": "仅对支持图片的模型生效。",
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => translations[key] ?? key,
  }),
}));

import { VisualCompactSettings } from "./VisualCompactSettings";

describe("VisualCompactSettings", () => {
  afterEach(() => {
    state.enabled = true;
    state.effort = "low";
  });

  it("uses localized effort labels", () => {
    render(<VisualCompactSettings />);

    expect(screen.getByText("低")).toBeInTheDocument();
    expect(screen.getByText("中")).toBeInTheDocument();
    expect(screen.getByText("高")).toBeInTheDocument();
    expect(screen.queryByText("Low")).not.toBeInTheDocument();
  });

  it("shows the description for the selected effort", () => {
    state.effort = "high";

    render(<VisualCompactSettings />);

    expect(screen.getByText("优先节省 Token。")).toBeInTheDocument();
  });

  it("disables the effort selector while Visual Compact is off", () => {
    state.enabled = false;

    render(<VisualCompactSettings />);

    expect(
      screen.getByRole("radiogroup", { name: "压缩强度" }),
    ).toHaveAttribute("aria-disabled", "true");
  });
});
