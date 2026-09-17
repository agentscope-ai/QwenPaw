import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import type { CheckpointNode, RestoreResult } from "@/api/types/checkpoints";
import { RestoreModal } from "./RestoreModal";
import { request } from "@/api/request";

const mocks = vi.hoisted(() => ({
  navigate: vi.fn(),
  previewRestore: vi.fn(),
  restore: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mocks.navigate };
});

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

vi.mock("@/api/request", () => ({ request: vi.fn() }));

vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: { success: mocks.success, error: mocks.error },
  }),
}));

const node: CheckpointNode = {
  ref: "refs/snap/source/checkpoint",
  kind: "snap",
  session_key: "source",
  name: "checkpoint",
  commit: "a".repeat(40),
  sha: "a".repeat(12),
  timestamp_ms: 1,
  subject: "checkpoint",
  query: "before restore",
  channel: "console",
  restore_index: null,
  parent_commit: null,
  is_head: true,
  agent_id: "agent",
  user_id: "user",
  session_id: "source-session",
  session_title: "source",
};

const result = (newChatId: string | null): RestoreResult => ({
  target: node.commit,
  commit: node.commit,
  restored_paths: ["sessions/console/restored.json"],
  deleted_paths: [],
  file_paths: [],
  pre_restore_ref: null,
  dry_run: false,
  include_memory: false,
  include_files: false,
  new_session_id: newChatId ? "restored-session" : null,
  new_chat_id: newChatId,
});

describe("checkpoint restore navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(request).mockImplementation(async (url, options) => {
      const payload = JSON.parse(String(options?.body));
      if (payload.user_id !== "user")
        throw new Error("Legacy session identity mismatch");
      return url.endsWith("/preview")
        ? mocks.previewRestore(payload)
        : mocks.restore(payload);
    });
  });

  it("成功恢复后使用服务端创建的 chat id 导航", async () => {
    mocks.previewRestore.mockResolvedValue({ ...result(null), dry_run: true });
    mocks.restore.mockResolvedValue(result("restored/chat id"));
    const onClose = vi.fn();
    const onRestored = vi.fn();
    renderWithProviders(
      <RestoreModal
        open
        node={node}
        onClose={onClose}
        onRestored={onRestored}
        createsNewChat
      />,
    );

    const user = userEvent.setup();
    await user.click(screen.getByText("checkpoints.restore.preview"));
    await user.click(await screen.findByText("checkpoints.restore.confirm"));

    await waitFor(() => {
      expect(mocks.navigate).toHaveBeenCalledWith("/chat/restored%2Fchat%20id");
    });
    expect(onClose).toHaveBeenCalledOnce();
    expect(onRestored).toHaveBeenCalledOnce();
    expect(
      screen.getByText("checkpoints.restore.newChatWarning"),
    ).toBeInTheDocument();
  });

  it("恢复失败时不关闭、不刷新且不导航", async () => {
    mocks.previewRestore.mockResolvedValue({ ...result(null), dry_run: true });
    mocks.restore.mockRejectedValue(new Error("restore failed"));
    const onClose = vi.fn();
    const onRestored = vi.fn();
    renderWithProviders(
      <RestoreModal
        open
        node={node}
        onClose={onClose}
        onRestored={onRestored}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByText("checkpoints.restore.preview"));
    await user.click(await screen.findByText("checkpoints.restore.confirm"));
    await waitFor(() => expect(mocks.error).toHaveBeenCalled());
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(onRestored).not.toHaveBeenCalled();
  });

  it("Legacy 成功恢复无新 chat id 时保持原行为", async () => {
    mocks.previewRestore.mockResolvedValue({ ...result(null), dry_run: true });
    mocks.restore.mockResolvedValue(result(null));
    const onClose = vi.fn();
    const onRestored = vi.fn();
    renderWithProviders(
      <RestoreModal
        open
        node={node}
        onClose={onClose}
        onRestored={onRestored}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByText("checkpoints.restore.preview"));
    expect(
      await screen.findByText("checkpoints.restore.refreshWarning"),
    ).toBeInTheDocument();
    await user.click(screen.getByText("checkpoints.restore.confirm"));
    await waitFor(() => expect(onRestored).toHaveBeenCalledOnce());
    expect(onClose).toHaveBeenCalledOnce();
    expect(mocks.navigate).not.toHaveBeenCalled();
    expect(request).toHaveBeenCalledWith(
      "/workspace/checkpoints/restore",
      expect.objectContaining({
        body: JSON.stringify({
          commit: node.commit,
          session_id: "source-session",
          user_id: "user",
          channel: "console",
          include_memory: false,
          include_files: false,
        }),
      }),
    );
  });
});
