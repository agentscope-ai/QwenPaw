// @vitest-environment jsdom
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";
import MigrationPreviewPage from "./index";

const hoisted = vi.hoisted(() => ({
  getPreview: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

vi.mock("@/api/modules/migration", () => ({
  migrationApi: { getPreview: hoisted.getPreview },
}));

const preview = {
  generated_at: "2026-09-08T02:00:00Z",
  read_only: true as const,
  summary: {
    domain_count: 10,
    item_count: 18,
    conflict_count: 1,
    rejected_count: 0,
    secret_reference_count: 2,
  },
  integrity: {
    before_hash: "sha256:before",
    after_hash: "sha256:before",
    unchanged: true,
  },
  domains: [
    {
      key: "identity",
      label: "身份",
      status: "ready" as const,
      count: 1,
      source_hash: "sha256:identity",
      mapping: { "legacy.auth": "identity.users" },
      conflicts: [],
      rejected: [],
    },
    {
      key: "legacy_postgres",
      label: "旧 PostgreSQL",
      status: "unavailable" as const,
      count: 0,
      source_hash: "sha256:empty",
      mapping: { "legacy.postgres": "platform.postgres" },
      conflicts: [{ code: "duplicate", source: "legacy", detail: "重复记录" }],
      rejected: [],
    },
  ],
  secret_references: [
    {
      reference: "secret/auth.json#jwt_secret",
      version: "fernet-v1" as const,
      value_exposed: false,
    },
    {
      reference: "work/agent.json#mcp.clients.docs.env.API_KEY",
      version: "plaintext" as const,
      value_exposed: false,
    },
  ],
};

describe("MigrationPreviewPage", () => {
  beforeEach(() => {
    hoisted.getPreview.mockReset();
    hoisted.getPreview.mockResolvedValue(preview);
  });

  it("展示十类汇总、映射和脱敏引用且不提供迁移写入按钮", async () => {
    renderWithProviders(<MigrationPreviewPage />);

    expect(
      await screen.findByText("Read-only migration preview"),
    ).toBeVisible();
    expect(screen.getByText("10")).toBeVisible();
    expect(screen.getByText("18")).toBeVisible();
    expect(screen.getByText("legacy.auth → identity.users")).toBeVisible();
    expect(screen.getByText("重复记录")).toBeVisible();
    expect(screen.getByText("secret/auth.json#jwt_secret")).toBeVisible();
    expect(screen.getByText("fernet-v1")).toBeVisible();
    expect(screen.getByText("Source data unchanged")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Migrate" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("ENC:gAAAA-secret-ciphertext"),
    ).not.toBeInTheDocument();
  });

  it("重新扫描会刷新页面报告", async () => {
    renderWithProviders(<MigrationPreviewPage />);
    await screen.findByText("Read-only migration preview");
    fireEvent.click(screen.getByRole("button", { name: "Scan again" }));
    await waitFor(() => expect(hoisted.getPreview).toHaveBeenCalledTimes(2));
  });
});
