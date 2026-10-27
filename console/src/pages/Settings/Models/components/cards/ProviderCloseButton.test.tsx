import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  configureProvider: vi.fn(),
  error: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/api/modules/provider", () => ({
  providerApi: { configureProvider: mocks.configureProvider },
}));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: mocks.error } }),
}));

import { ProviderCloseButton } from "./ProviderCloseButton";

describe("ProviderCloseButton", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("names provider actions uniquely by their display name", () => {
    render(
      <>
        <ProviderCloseButton
          ids={["aliyun"]}
          providerName="Aliyun"
          onSaved={vi.fn()}
          onConfigure={vi.fn()}
        />
        <ProviderCloseButton
          ids={["agentscope"]}
          providerName="AgentScope Platform"
          onSaved={vi.fn()}
          onConfigure={vi.fn()}
        />
      </>,
    );

    expect(
      screen.getByRole("button", { name: "models.settings: Aliyun" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "models.settings: AgentScope Platform",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "models.disableBtn: Aliyun" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "models.disableBtn: AgentScope Platform",
      }),
    ).toBeInTheDocument();
    for (const button of screen.getAllByRole("button")) {
      expect(button).toHaveAttribute("data-icon-button");
    }
  });

  it("keeps the provider-specific name while a disable request is pending", async () => {
    let finish!: () => void;
    mocks.configureProvider.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    const onSaved = vi.fn();
    render(
      <ProviderCloseButton
        ids={["aliyun"]}
        providerName="Aliyun"
        onSaved={onSaved}
      />,
    );

    const disable = screen.getByRole("button", {
      name: "models.disableBtn: Aliyun",
    });
    fireEvent.click(disable);

    expect(disable).toBeDisabled();
    expect(mocks.configureProvider).toHaveBeenCalledWith("aliyun", {
      enabled: false,
    });

    await act(async () => finish());
    await waitFor(() => expect(disable).toBeEnabled());
    expect(onSaved).toHaveBeenCalledTimes(1);
  });
});
