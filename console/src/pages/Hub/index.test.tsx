import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HubPage from ".";
import { hubApi } from "../../api/modules/hub";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: Record<string, unknown>) =>
      values ? `${key}:${JSON.stringify(values)}` : key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false, toggleTheme: vi.fn() }),
}));

vi.mock("../../components/LanguageSwitcher", () => ({
  default: () => <span>language</span>,
}));

vi.mock("../../api/modules/hub", async () => {
  const actual = await vi.importActual<typeof import("../../api/modules/hub")>(
    "../../api/modules/hub",
  );
  return {
    ...actual,
    hubApi: {
      me: vi.fn(),
      getHealth: vi.fn(),
      getOverview: vi.fn(),
      listRuntimes: vi.fn(),
      listUsers: vi.fn(),
      getRegistration: vi.fn(),
      listCredentials: vi.fn(),
      listAuditEvents: vi.fn(),
    },
  };
});

const page = {
  items: [],
  page: 1,
  page_size: 20,
  total: 0,
  pages: 1,
};

describe("HubPage", () => {
  beforeEach(() => {
    vi.mocked(hubApi.me).mockResolvedValue({
      user_id: "user-a",
      username: "owner",
      role: "admin",
      disabled: false,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    });
    vi.mocked(hubApi.getHealth).mockResolvedValue({
      status: "ok",
      mode: "hub",
      default_provisioner: "local",
      runtime_available: true,
      provisioner_statuses: {
        local: { available: true, security_level: "isolated-local" },
      },
    });
    vi.mocked(hubApi.getOverview).mockResolvedValue({
      runtime_counts: {
        created: 0,
        starting: 0,
        running: 2,
        stopped: 0,
        failed: 0,
      },
      total_runtimes: 2,
      total_users: 1,
      runtime_available: true,
      host: { cpu_percent: 12, memory_percent: 34, disk_percent: 56 },
      recent_events: [],
    });
    vi.mocked(hubApi.listRuntimes).mockResolvedValue(page);
    vi.mocked(hubApi.listUsers).mockResolvedValue(page);
    vi.mocked(hubApi.getRegistration).mockResolvedValue({ enabled: false });
    vi.mocked(hubApi.listCredentials).mockResolvedValue(page);
    vi.mocked(hubApi.listAuditEvents).mockResolvedValue(page);
  });

  it("loads the real operations overview for administrators", async () => {
    render(
      <App>
        <HubPage />
      </App>,
    );

    expect(await screen.findByText("hub.overview.title")).toBeInTheDocument();
    expect(hubApi.getOverview).toHaveBeenCalledOnce();
    expect(screen.getByText("100%", { exact: false })).toBeInTheDocument();
  });

  it("queries the server when runtime search changes", async () => {
    render(
      <App>
        <HubPage />
      </App>,
    );
    fireEvent.click(await screen.findByText("hub.navigation.runtimes"));
    const search = await screen.findByPlaceholderText(
      "hub.table.searchRuntimes",
    );
    fireEvent.change(search, { target: { value: "research" } });

    await waitFor(
      () => {
        expect(hubApi.listRuntimes).toHaveBeenLastCalledWith(
          expect.objectContaining({
            page: 1,
            pageSize: 20,
            query: "research",
          }),
        );
      },
      { timeout: 1500 },
    );
  });
});
