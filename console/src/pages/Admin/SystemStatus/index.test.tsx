// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import SystemStatusPage from "./index";

const hoisted = vi.hoisted(() => ({
  getStorageStatus: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock("@/api/modules/systemStatus", () => ({
  systemStatusApi: {
    getStorageStatus: hoisted.getStorageStatus,
  },
}));

describe("SystemStatusPage", () => {
  beforeEach(() => {
    hoisted.getStorageStatus.mockReset();
    hoisted.getStorageStatus.mockResolvedValue({
      status: "legacy",
      connected: false,
      schema_version: null,
      expected_schema_version: "0003_governance_operations",
      schema_ready: false,
      storage_mode: "legacy",
      active_repository: "legacy",
      migration_lock_state: "not_applicable",
      domains: [],
      error_code: null,
    });
  });

  it("只读展示 Legacy 状态且不提供危险操作", async () => {
    renderWithProviders(<SystemStatusPage />, {
      initialEntries: ["/system-status"],
    });

    expect(await screen.findByText("Legacy storage is active")).toBeVisible();
    expect(screen.getByText("Legacy file storage")).toBeVisible();
    expect(screen.getByText("Not applicable")).toBeVisible();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeEnabled();

    for (const label of ["Migrate", "Rebuild", "DROP", "Delete"]) {
      expect(
        screen.queryByRole("button", { name: label }),
      ).not.toBeInTheDocument();
    }
  });

  it("刷新后展示 PostgreSQL 与 Schema 状态", async () => {
    hoisted.getStorageStatus
      .mockResolvedValueOnce({
        status: "legacy",
        connected: false,
        schema_version: null,
        expected_schema_version: "0003_governance_operations",
        schema_ready: false,
        storage_mode: "legacy",
        active_repository: "legacy",
        migration_lock_state: "not_applicable",
        domains: [],
        error_code: null,
      })
      .mockResolvedValueOnce({
        status: "ready",
        connected: true,
        schema_version: "0003_governance_operations",
        expected_schema_version: "0003_governance_operations",
        schema_ready: true,
        storage_mode: "postgres",
        active_repository: "postgres",
        migration_lock_state: "locked",
        domains: [
          {
            domain: "messages",
            migration_validated: true,
            legacy_writes_frozen: true,
            postgres_writes_open: true,
            read_repository: "postgres",
            write_repository: "postgres",
          },
        ],
        error_code: null,
      });

    renderWithProviders(<SystemStatusPage />);
    await screen.findByText("Legacy storage is active");
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));

    await waitFor(() => {
      expect(screen.getByText("Database connected")).toBeVisible();
    });
    expect(screen.getByText("0003_governance_operations")).toBeVisible();
    expect(
      screen.getByText("Expected: 0003_governance_operations"),
    ).toBeVisible();
    expect(screen.getByText("Legacy writes frozen")).toBeVisible();
    expect(screen.getByText("messages")).toBeVisible();
    expect(
      screen.getByText(
        "Validated · Legacy writes frozen · PostgreSQL writes open",
      ),
    ).toBeVisible();
  });

  it("接口失败时显示安全错误并允许重试", async () => {
    hoisted.getStorageStatus.mockRejectedValue(
      new Error("network unavailable"),
    );

    renderWithProviders(<SystemStatusPage />);

    expect(
      await screen.findByText("Unable to load storage status"),
    ).toBeVisible();
    expect(screen.getByText("network unavailable")).toBeVisible();
    expect(screen.getByRole("button", { name: "Retry" })).toBeEnabled();
  });
});
