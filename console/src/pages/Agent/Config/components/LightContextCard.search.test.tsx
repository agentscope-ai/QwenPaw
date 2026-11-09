import { useRef } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { Form } from "@agentscope-ai/design";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { TFunction } from "i18next";
import { settingsSearchTarget } from "@/pages/SettingsCenter/settingsSearch";
import { useSettingsSearchTarget } from "@/pages/SettingsCenter/useSettingsSearchTarget";
import { LightContextCard } from "./LightContextCard";

vi.mock("@agentscope-ai/design", async () => {
  const antd = await import("antd");
  return {
    Form: antd.Form,
    Card: antd.Card,
    Switch: antd.Switch,
    Input: antd.Input,
    Collapse: antd.Collapse,
    Select: antd.Select,
  };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));

describe("context settings search", () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: vi.fn(),
    });
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockImplementation(
      function (this: HTMLElement) {
        return (this.closest(
          ".ant-collapse-content-hidden,.qwenpaw-collapse-content-hidden,[hidden]",
        )
          ? []
          : [{}]) as unknown as DOMRectList;
      },
    );
  });
  afterEach(() => vi.restoreAllMocks());

  it.each([
    ["agentConfig.toolResultCompactEnabled", "toolResultPruning"],
    ["agentConfig.toolResultCompactRecentThreshold", "toolResultPruning"],
    ["agentConfig.decisionCompactEnabled", "decisionCompact"],
    ["agentConfig.visualCompactEnabled", "visualCompact"],
    ["agentConfig.visualCompactEffort", "visualCompact"],
  ])("expands and highlights %s on its first search", async (key, section) => {
    const changed = vi.fn();
    const target = settingsSearchTarget(
      "agent-config",
      key,
      ((label: string) => label) as TFunction,
    );
    function Fixture() {
      const root = useRef<HTMLDivElement>(null);
      useSettingsSearchTarget(root, target, "agent-config");
      return (
        <div ref={root}>
          <Form onValuesChange={changed}>
            <LightContextCard maxInputLength={128000} />
          </Form>
        </div>
      );
    }
    const { container } = render(<Fixture />);
    await waitFor(() =>
      expect(
        screen.getByText(key).closest(".ant-form-item,.qwenpaw-form-item"),
      ).toHaveAttribute("data-search-highlight", "true"),
    );
    const headers = {
      toolResultPruning: "agentConfig.toolResultPruningCollapseLabel",
      decisionCompact: "agentConfig.decisionCompactLabel",
      visualCompact: "agentConfig.visualCompactCollapseLabel",
    };
    for (const [id, label] of Object.entries(headers)) {
      const disclosure = screen
        .getByText(label)
        .closest(".ant-collapse-item,.qwenpaw-collapse-item");
      expect(
        disclosure?.querySelector(':scope > [role="button"]'),
      ).toHaveAttribute("aria-expanded", String(id === section));
    }
    expect(
      container.querySelector('[role="switch"][aria-checked="true"]'),
    ).toBeNull();
    expect(changed).not.toHaveBeenCalled();
  });
});
