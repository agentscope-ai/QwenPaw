import { renderWithProviders } from "@/test/common_setup";
import { screen, waitFor } from "@testing-library/react";
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
    loadFileText: vi.fn().mockResolvedValue("hello"),
  },
}));

describe("FilesDrawer", () => {
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
          sessionId="session-1"
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
});
