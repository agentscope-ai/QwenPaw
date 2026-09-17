import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";

import { renderWithProviders } from "@/test/common_setup";

const apiMocks = vi.hoisted(() => ({
  createCustomProvider: vi.fn(),
}));

vi.mock("../../../../../api", () => ({
  default: apiMocks,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { changeLanguage: vi.fn(), language: "en" },
  }),
}));

const messageMocks = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: messageMocks }),
}));

vi.mock("@agentscope-ai/design", async (importOriginal) => {
  const antd = await import("antd");
  const original = (await importOriginal()) as Record<string, unknown>;
  const modalLike = ({ children, footer, title }: Record<string, unknown>) =>
    React.createElement(
      "div",
      { role: "dialog" },
      title ? React.createElement("div", null, title as React.ReactNode) : null,
      children as React.ReactNode,
      footer
        ? React.createElement("div", null, footer as React.ReactNode)
        : null,
    );

  return {
    ...original,
    Button: antd.Button,
    Form: antd.Form,
    Input: antd.Input,
    Select: antd.Select,
    Modal: modalLike,
  };
});

import { CustomProviderModal } from "./CustomProviderModal";

function renderModal(onSaved = vi.fn().mockResolvedValue(undefined)) {
  const onClose = vi.fn();
  renderWithProviders(
    <CustomProviderModal open onClose={onClose} onSaved={onSaved} />,
  );
  return { onClose, onSaved };
}

async function fillConnectionForm(user: ReturnType<typeof userEvent.setup>) {
  await user.type(
    screen.getByPlaceholderText("models.providerIdPlaceholder"),
    "team-api",
  );
  await user.type(
    screen.getByPlaceholderText("models.providerNamePlaceholder"),
    "Team API",
  );
  await user.type(
    screen.getByPlaceholderText("models.defaultBaseUrlPlaceholder"),
    "https://api.example.com/v1",
  );
  await user.type(
    screen.getByPlaceholderText("models.enterApiKeyOptional"),
    "sk-secret",
  );
}

describe("CustomProviderModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.createCustomProvider.mockResolvedValue({ id: "team-api" });
  });

  it("creates a provider with its connection configuration", async () => {
    const user = userEvent.setup();
    const { onClose, onSaved } = renderModal();
    await fillConnectionForm(user);

    await user.click(screen.getByText("models.save"));

    await waitFor(() =>
      expect(apiMocks.createCustomProvider).toHaveBeenCalledWith({
        id: "team-api",
        name: "Team API",
        default_base_url: "https://api.example.com/v1",
        api_key: "sk-secret",
        chat_model: "OpenAIChatModel",
      }),
    );
    expect(onSaved).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });
});
