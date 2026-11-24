// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { createInstance } from "i18next";
import { I18nextProvider } from "react-i18next";
import { MemoryRouter, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { CommunityConnectionStatus } from "@/api/modules/community";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import { CommunityInboxState } from "./CommunityInboxState";

const mocks = vi.hoisted(() => ({ status: vi.fn(), sync: vi.fn() }));
vi.mock("@/api/modules/community", () => ({ communityConnectionApi: mocks }));

function LocationProbe() {
  return <span data-testid="location">{useLocation().pathname}</span>;
}

async function renderState(language: "en" | "zh") {
  const i18n = createInstance();
  await i18n.init({
    lng: language,
    fallbackLng: false,
    resources: { en: { translation: en }, zh: { translation: zh } },
    interpolation: { escapeValue: false },
  });
  render(
    <I18nextProvider i18n={i18n}>
      <MemoryRouter initialEntries={["/inbox?source=community"]}>
        <CommunityInboxState />
        <LocationProbe />
      </MemoryRouter>
    </I18nextProvider>,
  );
}

const connected: CommunityConnectionStatus = {
  status: "connected",
  sync_enabled: true,
  messages_enabled: true,
};

beforeEach(() => {
  vi.clearAllMocks();
});

describe.each([
  {
    language: "en" as const,
    paused: "Community sync is paused. Existing messages remain available.",
    settings: "Community settings",
    failed: "Community sync failed. Existing messages have been kept.",
    retry: "Retry",
    hint: "Connect your community account to receive replies, mentions, and resource feedback here.",
    connect: "Connect community",
  },
  {
    language: "zh" as const,
    paused: "社区消息同步已暂停，已有消息仍可查看。",
    settings: "社区设置",
    failed: "社区消息同步失败，已保留已有消息。",
    retry: "重试",
    hint: "连接社区账号，在这里接收回复、提及和资源反馈。",
    connect: "连接社区",
  },
])("CommunityInboxState with real $language translations", (copy) => {
  it("translates a disabled message connection and opens its settings", async () => {
    mocks.status.mockResolvedValue({ ...connected, messages_enabled: false });
    await renderState(copy.language);

    expect(await screen.findByText(copy.paused)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: copy.settings }));
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/community-settings",
    );
  });

  it("translates sync failures and the retry action", async () => {
    mocks.status.mockResolvedValue({ ...connected, last_error: "sync_failed" });
    await renderState(copy.language);

    expect(await screen.findByText(copy.failed)).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: (name) =>
          name.replace(/\s/g, "") === copy.retry.replace(/\s/g, ""),
      }),
    ).toBeEnabled();
  });

  it("translates the disconnected state and account connection action", async () => {
    mocks.status.mockResolvedValue({
      ...connected,
      status: "disconnected",
      sync_enabled: false,
    });
    await renderState(copy.language);

    expect(await screen.findByText(copy.hint)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: copy.connect })).toBeEnabled();
  });
});
