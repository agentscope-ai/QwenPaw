import { renderWithProviders } from "@/test/common_setup";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FileBreadcrumbs from "./FileBreadcrumbs";

const mocks = vi.hoisted(() => ({
  listDirectory: vi.fn(),
}));

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    listDirectory: mocks.listDirectory,
  },
}));

describe("FileBreadcrumbs", () => {
  beforeEach(() => {
    mocks.listDirectory.mockReset();
    mocks.listDirectory.mockResolvedValue({
      directory: "src",
      entries: [
        {
          name: "codex",
          path: "src/codex",
          kind: "directory",
          size: null,
          modified_at: "",
          preview_kind: "binary",
        },
        {
          name: "adapter.py",
          path: "src/adapter.py",
          kind: "file",
          size: 20,
          modified_at: "",
          preview_kind: "text",
        },
      ],
      next_cursor: null,
      has_more: false,
    });
  });

  it("loads one directory only after its breadcrumb opens", async () => {
    const user = userEvent.setup();
    const onOpenFile = vi.fn();
    renderWithProviders(
      <FileBreadcrumbs
        path="src/codex/discovery.py"
        root="project"
        chatId="chat-1"
        onOpenFile={onOpenFile}
      />,
    );

    expect(mocks.listDirectory).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "src" }));

    await waitFor(() =>
      expect(mocks.listDirectory).toHaveBeenCalledWith(
        "src",
        undefined,
        200,
        "chat-1",
        "project",
        undefined,
      ),
    );
    await user.click(await screen.findByRole("button", { name: "adapter.py" }));
    expect(onOpenFile).toHaveBeenCalledWith("src/adapter.py", "project");
  });

  it("navigates into a child directory without mounting the full tree", async () => {
    const user = userEvent.setup();
    mocks.listDirectory
      .mockResolvedValueOnce({
        directory: "src",
        entries: [
          {
            name: "codex",
            path: "src/codex",
            kind: "directory",
            size: null,
            modified_at: "",
            preview_kind: "binary",
          },
        ],
        next_cursor: null,
        has_more: false,
      })
      .mockResolvedValueOnce({
        directory: "src/codex",
        entries: [],
        next_cursor: null,
        has_more: false,
      });

    renderWithProviders(
      <FileBreadcrumbs path="src/codex/discovery.py" onOpenFile={vi.fn()} />,
    );
    await user.click(screen.getByRole("button", { name: "src" }));
    await user.click(await screen.findByRole("button", { name: "codex" }));

    await waitFor(() =>
      expect(mocks.listDirectory).toHaveBeenLastCalledWith(
        "src/codex",
        undefined,
        200,
        undefined,
        "project",
        undefined,
      ),
    );
  });
});
