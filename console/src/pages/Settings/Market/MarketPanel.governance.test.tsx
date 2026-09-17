import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App, ConfigProvider } from "antd";
import { MarketPanel } from "./MarketPanel";
import { renderWithProviders } from "@/test/common_setup";
import { useAuthStore } from "@/stores/authStore";
import { useAgentStore } from "@/stores/agentStore";
import i18n from "@/i18n";

vi.mock("@agentscope-ai/design", async () => {
  const antd = await vi.importActual<typeof import("antd")>("antd");
  return { ...antd, IconButton: antd.Button };
});
beforeEach(async () => {
  await i18n.changeLanguage("en");
  useAuthStore.setState({
    mode: "multi_user",
    phase: "authenticated",
    user: { id: "reader", platform_role: "member" } as never,
  });
  useAgentStore.setState({
    selectedAgent: "a",
    agents: [
      { id: "a", enabled: true, access_role: "user", can_edit: false },
    ] as never,
  });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      const data = url.endsWith("/providers")
        ? [
            {
              key: "qwenpaw",
              label: "QwenPaw",
              available: true,
              supports_browse: true,
            },
          ]
        : url.includes("/categories")
        ? []
        : {
            results: [
              {
                source: "qwenpaw",
                slug: "sample",
                name: "Market sample",
                source_url: "https://example.invalid/sample",
              },
            ],
            errors: [],
            by_provider: { qwenpaw: { has_more: false, total: 1 } },
          };
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("lets a use-only consumer browse details without offering install controls", async () => {
  renderWithProviders(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <App>
        <MarketPanel installTarget="workspace" />
      </App>
    </ConfigProvider>,
  );
  fireEvent.click(await screen.findByText("Market sample"));
  await screen.findByRole("dialog");
  expect(
    screen.queryByRole("button", { name: i18n.t("common.save") }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByPlaceholderText(i18n.t("market.searchPlaceholder")),
  ).toBeInTheDocument();
  await waitFor(() =>
    expect(
      vi
        .mocked(fetch)
        .mock.calls.every(([url]) => String(url).startsWith("/api/market/")),
    ).toBe(true),
  );
});
