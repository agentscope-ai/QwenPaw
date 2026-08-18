import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import api from "../../../../../api";
import type { ProviderInfo } from "../../../../../api/types";
import { renderWithProviders } from "@/test/common_setup";

import { RemoteModelManageModal } from "./RemoteModelManageModal";

vi.mock("../../../../../api", () => ({
  default: {
    addModel: vi.fn(),
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

describe("RemoteModelManageModal", () => {
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
});
