import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HubPage from ".";
import { hubApi } from "../../api/modules/hub";
import {
  dockerCatalog,
  hubHealth,
  hubOverview,
  hubSettings,
  hubUser,
  page,
  runtime,
} from "../../test/hubFixtures";

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
      getSettings: vi.fn(),
      getDockerImages: vi.fn(),
      listDockerImagePulls: vi.fn(),
      pullDockerImage: vi.fn(),
      updateSettings: vi.fn(),
      listRuntimes: vi.fn(),
      listUsers: vi.fn(),
      listCredentials: vi.fn(),
      listAuditEvents: vi.fn(),
      startRuntime: vi.fn(),
      stopRuntime: vi.fn(),
      disableRuntime: vi.fn(),
      rebuildRuntime: vi.fn(),
      deleteRuntime: vi.fn(),
    },
  };
});

function renderHubPage() {
  return render(
    <App>
      <HubPage />
    </App>,
  );
}

describe("HubPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(hubApi.me).mockResolvedValue(hubUser());
    vi.mocked(hubApi.getHealth).mockResolvedValue(hubHealth());
    vi.mocked(hubApi.getOverview).mockResolvedValue(hubOverview());
    vi.mocked(hubApi.listRuntimes).mockResolvedValue(page());
    vi.mocked(hubApi.listUsers).mockResolvedValue(page());
    vi.mocked(hubApi.getSettings).mockResolvedValue(hubSettings());
    vi.mocked(hubApi.getDockerImages).mockResolvedValue(dockerCatalog());
    vi.mocked(hubApi.listDockerImagePulls).mockResolvedValue([]);
    vi.mocked(hubApi.listCredentials).mockResolvedValue(page());
    vi.mocked(hubApi.listAuditEvents).mockResolvedValue(page());
  });

  it("loads the real operations overview for administrators", async () => {
    renderHubPage();

    expect(await screen.findByText("hub.overview.title")).toBeInTheDocument();
    expect(hubApi.getOverview).toHaveBeenCalledOnce();
    expect(screen.getByText("100%", { exact: false })).toBeInTheDocument();
  });

  it("shows the backend reason when the runtime is unavailable", async () => {
    vi.mocked(hubApi.getHealth).mockResolvedValue(
      hubHealth({
        status: "degraded",
        runtime_available: false,
        provisioner_statuses: {
          local: {
            available: false,
            reason: "Sandbox executable is missing or unsupported.",
            security_level: "unavailable",
          },
        },
      }),
    );

    renderHubPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("hub.runtimes.unavailableTitle");
    expect(alert).toHaveTextContent(
      "Sandbox executable is missing or unsupported.",
    );
    expect(alert).toHaveTextContent('"provisioner":"local"');
  });

  it("does not expose the backend reason to non-administrators", async () => {
    vi.mocked(hubApi.me).mockResolvedValue(hubUser({ role: "user" }));
    vi.mocked(hubApi.getHealth).mockResolvedValue(
      hubHealth({
        status: "degraded",
        runtime_available: false,
        provisioner_statuses: {
          local: {
            available: false,
            reason: "Cannot connect to /var/run/docker.sock.",
            security_level: "unavailable",
          },
        },
      }),
    );

    renderHubPage();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("hub.runtimes.unavailableUserDescription");
    expect(alert).not.toHaveTextContent("/var/run/docker.sock");
    expect(alert).not.toHaveTextContent('"provisioner":"local"');
  });

  it("queries the server when runtime search changes", async () => {
    renderHubPage();
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

  it("shows the owner username with the full user id", async () => {
    vi.mocked(hubApi.listRuntimes).mockResolvedValue(
      page([
        runtime({
          runtime_id: "personal-a4715bbaa57446b7b3b15b54",
          tenant_id: "personal-a4715bbaa57446b7b3b15b54",
          owner_user_id: "a4715bbaa57446b7b3b15b54",
          owner_username: "ray",
          port: 35583,
          endpoint: "http://127.0.0.1:35583",
        }),
      ]),
    );

    renderHubPage();
    fireEvent.click(await screen.findByText("hub.navigation.runtimes"));

    expect(await screen.findByText("ray")).toBeInTheDocument();
    expect(screen.getByText("a4715bbaa57446b7b3b15b54")).toBeInTheDocument();
  });

  it("does not expose the internal runtime boundary mode", async () => {
    vi.mocked(hubApi.listRuntimes).mockResolvedValue(
      page([
        runtime({
          provisioner: "docker",
          metadata: {
            docker: {
              image: "qwenpaw:latest",
              pull_policy: "if_not_present",
              boundary_mode: "token",
            },
          },
        }),
      ]),
    );

    renderHubPage();
    fireEvent.click(await screen.findByText("hub.navigation.runtimes"));

    expect(
      screen.queryByText("hub.runtimes.boundary.token"),
    ).not.toBeInTheDocument();
  });

  it("shows administrator-locked runtimes as enable-only", async () => {
    vi.mocked(hubApi.listRuntimes).mockResolvedValue(
      page([
        runtime({
          runtime_id: "personal-disabled",
          tenant_id: "personal-user-b",
          owner_user_id: "user-b",
          owner_username: "member",
          state: "stopped",
          desired_state: "stopped",
          start_policy: "admin_only",
        }),
      ]),
    );

    renderHubPage();
    fireEvent.click(await screen.findByText("hub.navigation.runtimes"));

    expect(
      await screen.findByText("hub.runtimePolicies.admin_only"),
    ).toBeInTheDocument();
    expect(screen.getByText("hub.actions.enableAndStart")).toBeInTheDocument();
    expect(screen.queryByText("hub.actions.disable")).not.toBeInTheDocument();
  });

  it("does not offer runtime deletion to non-administrators", async () => {
    vi.mocked(hubApi.me).mockResolvedValue(hubUser({ role: "user" }));
    vi.mocked(hubApi.listRuntimes).mockResolvedValue(
      page([
        runtime({
          runtime_id: "personal-stopped",
          state: "stopped",
          desired_state: "stopped",
        }),
      ]),
    );

    renderHubPage();
    fireEvent.click(await screen.findByText("hub.navigation.runtimes"));
    const runtimeId = await screen.findByText("personal-stopped");
    const row = runtimeId.closest("tr");

    expect(row).not.toBeNull();
    expect(within(row!).queryByRole("button")).not.toBeInTheDocument();
  });

  it("locks the current administrator role and account status", async () => {
    vi.mocked(hubApi.listUsers).mockResolvedValue(page([hubUser()]));

    renderHubPage();
    fireEvent.click(await screen.findByText("hub.navigation.users"));
    const protectedLabel = await screen.findByText(
      "hub.users.currentAccountProtected",
    );
    const row = protectedLabel.closest("tr");

    expect(row).not.toBeNull();
    expect(protectedLabel).toBeInTheDocument();
    expect(within(row!).getByRole("combobox")).toBeDisabled();
    expect(within(row!).getByRole("switch")).toBeDisabled();
  });

  it("loads and saves the complete Hub settings document", async () => {
    vi.mocked(hubApi.updateSettings).mockImplementation(
      async (revision, config) => ({
        config,
        revision: revision + 1,
        updated_at: "2026-01-02T00:00:00Z",
        available_provisioners: ["local"],
      }),
    );
    renderHubPage();

    fireEvent.click(await screen.findByText("hub.navigation.settings"));
    expect(
      await screen.findByDisplayValue("https://hub.example.com"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText("hub.settings.save"));

    await waitFor(() => {
      expect(hubApi.updateSettings).toHaveBeenCalledWith(
        3,
        expect.objectContaining({
          control_plane: expect.objectContaining({
            public_base_url: "https://hub.example.com",
          }),
          runtime: {
            provisioner: "local",
            docker: {
              source: "docker_hub",
              image: "docker.io/agentscope/qwenpaw:latest",
              pull_policy: "if_not_present",
              cpu_limit: 2,
              memory_limit_mb: 4096,
              pids_limit: 1024,
              shm_size_mb: 512,
            },
          },
        }),
      );
    });
  });

  it("shows Docker policy only when the Docker backend is selected", async () => {
    renderHubPage();

    fireEvent.click(await screen.findByText("hub.navigation.settings"));
    fireEvent.click(await screen.findByText("hub.settings.tabs.runtime"));
    expect(hubApi.getDockerImages).not.toHaveBeenCalled();
    expect(
      screen.queryByText("hub.settings.docker.title"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("hub.settings.runtime.dockerBackend"));
    expect(
      await screen.findByText("hub.settings.docker.title"),
    ).toBeInTheDocument();
    expect(hubApi.getDockerImages).toHaveBeenCalledOnce();
  });

  it("shows the settings shell before the base request completes", async () => {
    vi.mocked(hubApi.getSettings).mockReturnValue(new Promise(() => {}));
    renderHubPage();

    fireEvent.click(await screen.findByText("hub.navigation.settings"));

    expect(await screen.findByText("hub.settings.title")).toBeInTheDocument();
    expect(
      screen.queryByDisplayValue("https://hub.example.com"),
    ).not.toBeInTheDocument();
    expect(hubApi.getDockerImages).not.toHaveBeenCalled();
  });

  it("uses a tagged local image without a registry allowlist", async () => {
    vi.mocked(hubApi.getDockerImages).mockResolvedValue(
      dockerCatalog({
        official_images: [],
        local_images: [
          {
            reference: "qwenpaw-hub-e2e:test",
            image_id: "sha256:1234567890",
            short_id: "sha256:123456",
            digests: [],
            size: 1024 * 1024 * 900,
            downloaded: true,
          },
        ],
      }),
    );
    vi.mocked(hubApi.updateSettings).mockImplementation(
      async (revision, config) => ({
        config,
        revision: revision + 1,
        updated_at: "2026-01-02T00:00:00Z",
        available_provisioners: ["local", "docker"],
      }),
    );

    renderHubPage();
    fireEvent.click(await screen.findByText("hub.navigation.settings"));
    fireEvent.click(await screen.findByText("hub.settings.tabs.runtime"));
    fireEvent.click(screen.getByText("hub.settings.runtime.dockerBackend"));
    fireEvent.click(await screen.findByText("hub.settings.docker.localHost"));
    fireEvent.click(screen.getByText("hub.settings.save"));

    await waitFor(() => {
      expect(hubApi.updateSettings).toHaveBeenCalledWith(
        3,
        expect.objectContaining({
          runtime: expect.objectContaining({
            provisioner: "docker",
            docker: expect.objectContaining({
              source: "custom",
              image: "qwenpaw-hub-e2e:test",
              pull_policy: "never",
            }),
          }),
        }),
      );
    });
  });
});
