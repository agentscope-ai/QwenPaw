import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConfigProvider } from "antd";
import { expect, it, vi } from "vitest";
import type { BackupMeta } from "@/api/types/backup";
import BackupTable from "./BackupTable";

const { deleteBackups, success } = vi.hoisted(() => ({
  deleteBackups: vi.fn(),
  success: vi.fn(),
}));

vi.mock("@/api", () => ({ default: { deleteBackups } }));
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { success } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: { name: string; id: string }) =>
      key === "backup.deleteConfirm" && options
        ? `${key} ${options.name} (${options.id})`
        : key,
  }),
}));

it("does not report success when the backup API returns a failed deletion", async () => {
  deleteBackups.mockResolvedValueOnce({
    deleted: [],
    failed: [{ id: "backup-1", reason: "permission denied" }],
  });
  deleteBackups.mockResolvedValueOnce({ deleted: ["backup-1"], failed: [] });
  const backup: BackupMeta = {
    id: "backup-1",
    name: "Test backup",
    description: "",
    created_at: "2026-11-20T08:00:00Z",
    scope: {
      include_agents: false,
      include_global_config: false,
      include_secrets: false,
      include_skill_pool: false,
    },
    agent_count: 0,
  };
  const onRefresh = vi.fn();
  const user = userEvent.setup();
  render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <BackupTable
        backups={[backup]}
        searchQuery=""
        onRestore={vi.fn()}
        onRefresh={onRefresh}
      />
    </ConfigProvider>,
  );

  const [trigger] = screen.getAllByRole("button", {
    name: "backup.deleteConfirm Test backup (backup-1)",
  });
  await user.click(trigger);
  expect(
    screen.getByRole("group", {
      name: "backup.deleteConfirm Test backup (backup-1)",
    }),
  ).toHaveTextContent("Test backup (backup-1)");
  const confirm = await screen.findByRole("button", {
    name: "confirmation.deleteBackup",
  });
  await user.click(confirm);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "confirmation.deleteFailed",
  );
  expect(success).not.toHaveBeenCalled();
  expect(onRefresh).not.toHaveBeenCalled();

  await user.click(confirm);
  expect(deleteBackups).toHaveBeenCalledTimes(2);
  expect(deleteBackups).toHaveBeenLastCalledWith(["backup-1"]);
  expect(success).toHaveBeenCalledOnce();
  expect(onRefresh).toHaveBeenCalledOnce();
});
