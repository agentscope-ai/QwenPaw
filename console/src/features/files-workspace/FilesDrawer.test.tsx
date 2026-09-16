import { renderWithProviders } from "@/test/common_setup";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import FilesDrawer from "./FilesDrawer";

vi.mock("../../api/modules/workspace", () => ({
  workspaceApi: {
    getFileMetadata: vi.fn().mockResolvedValue({
      path: "hello.txt",
      size: 5,
      modified_at: "",
      preview_kind: "text",
      etag: "etag",
    }),
    loadFileText: vi.fn().mockResolvedValue({
      content: "hello",
      etag: "etag",
    }),
  },
}));

vi.mock("./FilesWorkspace", () => ({
  default: () => <div data-testid="files-workspace" />,
}));
vi.mock("./UnifiedFileCenter", () => ({
  default: ({ initialLocator }: { initialLocator?: { stableId?: string } }) => (
    <div data-testid="unified-file-center" data-selected-item={initialLocator?.stableId} />
  ),
}));

describe("FilesDrawer", () => {
  it("expands an artifact preview into the same unified file center item", async () => {
    const dispatch = vi.fn();
    const locator = {
      category: "artifact" as const,
      agentId: "agent-a",
      stableId: "bd20d801-5fa2-4dd0-8d5e-691806601b5b",
      relativePath: "report.md",
    };
    const { rerender } = renderWithProviders(
      <FilesDrawer
        state={{ kind: "preview", locator, trigger: null }}
        dispatch={dispatch}
        scope={{ kind: "session", agentId: "agent-a", sessionId: "session-a" }}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: /在文件中心打开|Open in File Center|files\.fileCenter\.open/i }),
    );
    expect(dispatch).toHaveBeenCalledWith({ type: "EXPAND_WORKSPACE" });

    rerender(
      <FilesDrawer
        state={{ kind: "workspace", locator, trigger: null }}
        dispatch={dispatch}
        scope={{ kind: "session", agentId: "agent-a", sessionId: "session-a" }}
      />,
    );
    expect(await screen.findByTestId("unified-file-center")).toHaveAttribute(
      "data-selected-item",
      locator.stableId,
    );
    expect(screen.queryByTestId("files-workspace")).not.toBeInTheDocument();
  });

  it("does not repeat the Workspace label in the expanded header", async () => {
    renderWithProviders(
      <FilesDrawer
        state={{
          kind: "workspace",
          target: {
            source: "workspace",
            path: "hello.txt",
            root: "project",
          },
          trigger: null,
        }}
        dispatch={vi.fn()}
        scope={{
          kind: "session",
          agentId: "default",
          sessionId: "session-1",
        }}
      />,
    );

    expect(await screen.findByTestId("files-workspace")).toBeInTheDocument();
    expect(
      screen.queryByText((content) =>
        ["工作区", "Workspace", "files.workspace"].includes(content),
      ),
    ).not.toBeInTheDocument();
  });

  it("keeps Preview open after inserting a file reference", async () => {
    const dispatch = vi.fn();
    const user = userEvent.setup();
    renderWithProviders(
      <>
        <div className="sender">
          <textarea />
        </div>
        <FilesDrawer
          state={{
            kind: "preview",
            target: {
              source: "workspace",
              path: "hello.txt",
              root: "project",
            },
            trigger: null,
          }}
          dispatch={dispatch}
          scope={{
            kind: "session",
            agentId: "default",
            sessionId: "session-1",
          }}
        />
      </>,
    );

    await user.click(
      await screen.findByRole("button", {
        name: /mentionInChat|在聊天中引用/i,
      }),
    );

    await waitFor(() => {
      expect(screen.getByRole("textbox")).toHaveValue("@ hello.txt ");
    });
    expect(dispatch).not.toHaveBeenCalledWith({ type: "CLOSE" });
    expect(
      screen.getByRole("button", {
        name: /mentionInChat|在聊天中引用/i,
      }),
    ).toBeInTheDocument();
  });

  it("keeps pointer resizing direct until the gesture ends", async () => {
    renderWithProviders(
      <FilesDrawer
        state={{
          kind: "workspace",
          trigger: null,
        }}
        dispatch={vi.fn()}
        scope={{
          kind: "session",
          agentId: "default",
          sessionId: "session-1",
        }}
      />,
    );

    const drawer = screen.getByRole("region");
    const separator = screen.getByRole("separator");
    fireEvent.pointerDown(separator, { clientX: 420 });
    expect(drawer.className).toContain("drawerResizing");

    fireEvent.pointerMove(window, { clientX: 520 });
    fireEvent.pointerUp(window);
    await waitFor(() => {
      expect(drawer.className).not.toContain("drawerResizing");
    });
  });
});
