/**
 * Regression for #8836: opening a config modal that carries a password field
 * must not write anything on its own.
 *
 * The failing behaviour: opening the modal ran one auto-save with values the
 * user never touched. That save goes through saveToolConfig() + loadTools(),
 * so it refreshes the tool list and can re-enter the modal 鈥?the reported
 * "page keeps refreshing".
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, waitFor } from "@testing-library/react";

const hoisted = vi.hoisted(() => ({
  getToolConfig: vi.fn().mockResolvedValue({}),
  confirm: vi.fn(),
}));

vi.mock("../../../api", () => ({
  default: { getToolConfig: hoisted.getToolConfig },
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { destroy: vi.fn(), error: vi.fn() },
    modal: { confirm: hoisted.confirm },
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

// Bridge the design package's ESM build to the real antd statics, as the main
// suite does; without it Form.useForm/useWatch are unavailable under Vitest.
vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const antd = await import("antd");
  const original = (await importOriginal()) as Record<string, unknown>;
  return {
    ...original,
    Form: antd.Form,
    Modal: antd.Modal,
    Input: antd.Input,
    Select: antd.Select,
  };
});

import type { ToolInfo } from "../../../api/modules/tools";
import { WebSearchConfigModal } from "./WebSearchConfigModal";

const tool: ToolInfo = {
  name: "web_search",
  enabled: true,
  async_execution: false,
  description: "Search the web",
  icon: "馃攷",
  config_fields: [],
  config_values: {},
};

function passwordInput(): HTMLInputElement | null {
  return document.querySelector('input[type="password"]');
}

type SaveHandler = (values: Record<string, unknown>) => Promise<void>;

async function openAndSettle(onSave: SaveHandler) {
  render(
    <WebSearchConfigModal
      tool={tool}
      visible
      onClose={vi.fn()}
      onSave={onSave}
    />,
  );
  await waitFor(() => expect(passwordInput()).toBeTruthy());
  const fetchesAfterOpen = hoisted.getToolConfig.mock.calls.length;
  // Debounced auto-save fires at 1s; leave room for a follow-up fetch chain.
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 2200));
  });
  return fetchesAfterOpen;
}

describe("WebSearchConfigModal auto-save guard (#8836)", () => {
  beforeEach(() => {
    hoisted.getToolConfig.mockReset();
    hoisted.getToolConfig.mockResolvedValue({});
  });

  it("does not write when the saved config already has a provider and key", async () => {
    hoisted.getToolConfig.mockResolvedValue({
      provider: "tavily",
      api_key: "tvly-secret",
    });
    const onSave = vi.fn<SaveHandler>().mockResolvedValue(undefined);

    const fetchesAfterOpen = await openAndSettle(onSave);

    expect(onSave).not.toHaveBeenCalled();
    expect(hoisted.getToolConfig.mock.calls.length).toBeLessThanOrEqual(
      fetchesAfterOpen + 1,
    );
  });

  it("does not write when the saved config has no provider yet", async () => {
    hoisted.getToolConfig.mockResolvedValue({ api_key: "tvly-secret" });
    const onSave = vi.fn<SaveHandler>().mockResolvedValue(undefined);

    const fetchesAfterOpen = await openAndSettle(onSave);

    expect(onSave).not.toHaveBeenCalled();
    expect(hoisted.getToolConfig.mock.calls.length).toBeLessThanOrEqual(
      fetchesAfterOpen + 1,
    );
  });
});
