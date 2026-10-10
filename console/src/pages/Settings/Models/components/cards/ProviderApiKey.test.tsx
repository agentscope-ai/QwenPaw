import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import type { ProviderInfo } from "@/api/types";
import { RemoteProviderCard } from "./RemoteProviderCard";
import { ProviderGroupCard } from "./ProviderGroupCard";

it.each([false, true])(
  "allows an optional API key and masks configured keys consistently (group=%s)",
  (grouped) => {
    const provider: ProviderInfo = {
      api_key_prefix: "",
      api_key: "",
      chat_model: "OpenAIChatModel",
      is_custom: false,
      is_local: false,
      support_model_discovery: true,
      support_connection_check: true,
      freeze_url: false,
      generate_kwargs: {},
      id: "kilo",
      name: "Kilo",
      models: [],
      extra_models: [],
      require_api_key: false,
      base_url: "https://example.test",
    };
    const onOpenConfig = vi.fn();
    const props = { onOpenConfig, onSaved: vi.fn(), onOpenModels: vi.fn() };
    const card = (value: ProviderInfo) =>
      grouped ? (
        <ProviderGroupCard
          {...props}
          group={{ groupKey: "test", groupName: "Test", providers: [value] }}
        />
      ) : (
        <RemoteProviderCard {...props} provider={value} />
      );
    const view = renderWithProviders(card(provider));
    fireEvent.click(screen.getByRole("button", { name: "models.add" }));
    expect(onOpenConfig).toHaveBeenCalledWith(provider);
    const configured = { ...provider, api_key: "sk-ant-******" };
    view.rerender(card(configured));
    expect(screen.getByText("••••••••")).toBeInTheDocument();
    expect(screen.queryByText(configured.api_key)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "models.changeApiKey" }),
    );
    expect(onOpenConfig).toHaveBeenLastCalledWith(configured);
  },
);
