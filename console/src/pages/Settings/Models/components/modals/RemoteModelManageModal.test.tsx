import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Modal } from "@agentscope-ai/design";

import api from "../../../../../api";
import type { ProviderInfo } from "../../../../../api/types";
import { renderWithProviders } from "@/test/common_setup";

import { RemoteModelManageModal } from "./RemoteModelManageModal";

vi.mock("../../../../../api", () => ({
  default: {
    addModel: vi.fn(),
    removeModel: vi.fn(),
    setModelVisibility: vi.fn(),
  },
}));

vi.mock("../../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

const messageMock = vi.hoisted(() => ({
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn(),
}));

vi.mock("../../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: messageMock }),
}));

const provider = {
  id: "siliconflow",
  name: "SiliconFlow",
  api_key_prefix: "sk-",
  chat_model: "OpenAIChatModel",
  models: [],
  extra_models: [],
  discovered_models: [
    { id: "ready", name: "Ready", availability_status: "available" },
    { id: "hidden", name: "Hidden", availability_status: "available" },
    {
      id: "forbidden",
      name: "Forbidden",
      availability_status: "permission_denied",
    },
  ],
  hidden_model_ids: ["hidden"],
  removed_model_ids: ["ready"],
  is_custom: false,
  is_local: false,
  support_model_discovery: true,
  support_connection_check: true,
  freeze_url: false,
  require_api_key: true,
  api_key: "",
  base_url: "https://api.example/v1",
  generate_kwargs: {},
} as unknown as ProviderInfo;

const configuredProvider = {
  ...provider,
  models: [
    { id: "builtin", name: "Builtin" },
    { id: "hidden-configured", name: "Hidden Configured" },
  ],
  hidden_model_ids: ["hidden", "hidden-configured"],
} as unknown as ProviderInfo;

describe("RemoteModelManageModal", () => {
  it("re-adds removed candidates without hidden or unavailable models", async () => {
    vi.mocked(api.addModel).mockResolvedValue(provider);
    const onSaved = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={provider}
        open
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: /Add all available/,
      }),
    );

    await waitFor(() => expect(api.addModel).toHaveBeenCalledOnce());
    expect(api.addModel).toHaveBeenCalledWith(
      "siliconflow",
      expect.objectContaining({ id: "ready", name: "Ready" }),
    );
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("does not save when adding discovered models fails", async () => {
    vi.mocked(api.addModel)
      .mockClear()
      .mockRejectedValue(new Error("add failed"));
    messageMock.error.mockClear();
    const onSaved = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={provider}
        open
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );

    await user.click(
      screen.getByRole("button", {
        name: /Add all available/,
      }),
    );

    await waitFor(() => expect(api.addModel).toHaveBeenCalledOnce());
    expect(onSaved).not.toHaveBeenCalled();
    expect(messageMock.error).toHaveBeenCalledOnce();
    expect(
      screen.getByRole("button", { name: /Add all available/ }),
    ).toBeInTheDocument();
  });

  it("hides and restores configured models on the Models page", async () => {
    vi.mocked(api.setModelVisibility).mockResolvedValue(configuredProvider);
    const onSaved = vi.fn();
    const onProviderUpdated = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={configuredProvider}
        open
        onClose={vi.fn()}
        onSaved={onSaved}
        onProviderUpdated={onProviderUpdated}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "modelSelector.hideModel" }),
    );
    await waitFor(() =>
      expect(api.setModelVisibility).toHaveBeenCalledWith(
        "siliconflow",
        "builtin",
        true,
      ),
    );

    await user.click(
      screen.getByRole("button", { name: "modelSelector.restoreModel" }),
    );
    await waitFor(() =>
      expect(api.setModelVisibility).toHaveBeenCalledWith(
        "siliconflow",
        "hidden-configured",
        false,
      ),
    );
    expect(onProviderUpdated).toHaveBeenCalledWith(configuredProvider);
  });

  it("removes a built-in model after confirmation", async () => {
    vi.mocked(api.removeModel).mockResolvedValue(configuredProvider);
    const onSaved = vi.fn();
    const user = userEvent.setup();
    const confirmSpy = vi.spyOn(Modal, "confirm");

    renderWithProviders(
      <RemoteModelManageModal
        provider={configuredProvider}
        open
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "models.removeModel" }),
    );
    expect(confirmSpy).toHaveBeenCalledOnce();

    const confirmOptions = confirmSpy.mock.calls[0][0];
    await confirmOptions.onOk?.();

    await waitFor(() =>
      expect(api.removeModel).toHaveBeenCalledWith("siliconflow", "builtin"),
    );
    expect(onSaved).toHaveBeenCalledOnce();
  });
});
