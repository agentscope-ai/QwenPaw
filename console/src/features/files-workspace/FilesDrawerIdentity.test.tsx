import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import { adoptAccessSession, clearAccessSession } from "../../api/authSession";
import { workspaceApi } from "../../api/modules/workspace";
import FilesDrawer from "./FilesDrawer";

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    getFileMetadata: vi.fn(),
    loadFileText: vi.fn(),
  },
}));

afterEach(() => {
  clearAccessSession(false);
  vi.clearAllMocks();
});

it("removes a previous user's loaded text immediately even when Agent and file path stay unchanged", async () => {
  adoptAccessSession({ token: "fixture-a", username: "a" }, false);
  vi.mocked(workspaceApi.getFileMetadata).mockResolvedValue({
    path: "private.txt",
    size: 6,
    modified_at: "",
    preview_kind: "text",
    etag: "a",
  });
  vi.mocked(workspaceApi.loadFileText)
    .mockResolvedValueOnce({ content: "用户甲的私人资料", etag: "a" } as never)
    .mockImplementation(() => new Promise(() => {}));
  renderWithProviders(
    <FilesDrawer
      state={{
        kind: "preview",
        target: { source: "workspace", path: "private.txt", root: "project" },
        trigger: null,
      }}
      dispatch={vi.fn()}
      scope={{
        kind: "session",
        agentId: "same-agent",
        sessionId: "same-session",
      }}
    />,
  );
  expect(await screen.findByText("用户甲的私人资料")).toBeVisible();
  // Ordinary token renewal preserves the authenticated identity and loaded UI.
  act(() => adoptAccessSession({ token: "renewed-a", username: "a" }, false));
  expect(screen.getByText("用户甲的私人资料")).toBeVisible();
  expect(workspaceApi.loadFileText).toHaveBeenCalledTimes(1);
  act(() => {
    clearAccessSession(false);
    adoptAccessSession({ token: "fixture-b", username: "b" }, false);
  });
  expect(screen.queryByText("用户甲的私人资料")).not.toBeInTheDocument();
  await waitFor(() =>
    expect(workspaceApi.loadFileText).toHaveBeenCalledTimes(2),
  );
});
