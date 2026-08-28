import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import api from "../../../../../api";
import type { ProviderInfo } from "../../../../../api/types";
import { renderWithProviders } from "@/test/common_setup";

import { RemoteModelManageModal } from "./RemoteModelManageModal";

vi.mock("../../../../../api", () => ({
  default: {
    addModel: vi.fn(),
    discoverModels: vi.fn(),
  },
}));

vi.mock("../../../../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
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

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("RemoteModelManageModal", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("adds all available candidates without hidden or unavailable models", async () => {
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

  it("populates model ID candidates from preview discovery", async () => {
    vi.mocked(api.discoverModels).mockResolvedValue({
      success: true,
      message: "",
      models: [
        { id: "remote-model", name: "Remote Model" },
      ] as unknown as ProviderInfo["models"],
      discovered_count: 1,
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={{ ...provider, discovered_models: [] }}
        open
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );

    await user.click(screen.getByRole("button", { name: "models.addModel" }));
    await waitFor(() =>
      expect(api.discoverModels).toHaveBeenCalledWith(
        "siliconflow",
        undefined,
        true,
      ),
    );
    expect(
      await screen.findByRole("button", {
        name: /Add all available \(\{\{count\}\}\)/,
      }),
    ).toBeInTheDocument();
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("shows a successful empty discovery distinctly", async () => {
    vi.mocked(api.discoverModels).mockResolvedValue({
      success: true,
      message: "",
      models: [],
      discovered_count: 0,
    });
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={{ ...provider, discovered_models: [] }}
        open
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "models.addModel" }));
    await waitFor(() => expect(api.discoverModels).toHaveBeenCalledOnce());
    expect(
      await screen.findByText(
        "Discovery succeeded, but the provider returned no models.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the real preview discovery error", async () => {
    vi.mocked(api.discoverModels).mockResolvedValue({
      success: false,
      message: "status=401: invalid API key",
      models: [],
      discovered_count: 0,
    });
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={{ ...provider, discovered_models: [] }}
        open
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "models.addModel" }));

    expect(
      (await screen.findAllByText("status=401: invalid API key")).length,
    ).toBeGreaterThan(0);
  });

  it("refreshes and publishes discovered models", async () => {
    vi.mocked(api.discoverModels).mockResolvedValue({
      success: true,
      message: "",
      models: [
        { id: "refreshed", name: "Refreshed" },
      ] as unknown as ProviderInfo["models"],
      discovered_count: 1,
    });
    const onSaved = vi.fn();
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={{ ...provider, discovered_models: [] }}
        open
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Refresh models" }));

    await waitFor(() =>
      expect(api.discoverModels).toHaveBeenCalledWith(
        "siliconflow",
        undefined,
        true,
      ),
    );
    expect(onSaved).toHaveBeenCalledOnce();
  });

  it("disables add while refresh discovery is running", async () => {
    const pending = deferred<Awaited<ReturnType<typeof api.discoverModels>>>();
    vi.mocked(api.discoverModels).mockReturnValue(pending.promise);
    const user = userEvent.setup();

    renderWithProviders(
      <RemoteModelManageModal
        provider={{ ...provider, discovered_models: [] }}
        open
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Refresh models" }));

    const addButton = screen.getByRole("button", { name: "models.addModel" });
    expect(addButton).toBeDisabled();
    expect(api.discoverModels).toHaveBeenCalledOnce();

    await act(async () => {
      pending.resolve({
        success: true,
        message: "",
        models: [],
        discovered_count: 0,
      });
      await pending.promise;
    });
  });
});
