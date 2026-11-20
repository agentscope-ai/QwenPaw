import { renderWithProviders } from "@/test/common_setup";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AnimatePresence } from "motion/react";
import { agentsApi } from "../../api/modules/agents";
import FilesDrawer from "./FilesDrawer";
import { workspaceApi } from "../../api/modules/workspace";
import type { FileTarget } from "./types";
import { useReducer } from "react";
import { filesDrawerReducer } from "./filesDrawerState";

const clipboardMocks = vi.hoisted(() => ({
  copyText: vi.fn().mockResolvedValue(undefined),
  error: vi.fn(),
  success: vi.fn(),
}));

vi.mock("../../utils/clipboard", () => ({
  copyText: clipboardMocks.copyText,
}));

vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      error: clipboardMocks.error,
      success: clipboardMocks.success,
    },
  }),
}));

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
    getFileDownloadUrl: vi.fn((path: string) => `/api/files/download/${path}`),
    loadFile: vi.fn().mockResolvedValue({
      content: "profile content",
    }),
  },
}));

vi.mock("./FilesWorkspace", () => ({
  default: ({ initialMemoryTag }: { initialMemoryTag?: string }) => (
    <div data-testid="files-workspace" data-memory-tag={initialMemoryTag} />
  ),
}));

vi.mock("../../utils/downloadFileFromUrl", () => ({
  downloadFileFromUrl: vi.fn(),
}));

function PreviewFocusHarness() {
  const [state, dispatch] = useReducer(filesDrawerReducer, { kind: "closed" });
  return (
    <>
      <section data-testid="chat-background">
        <button
          type="button"
          onClick={(event) =>
            dispatch({
              type: "OPEN_PREVIEW",
              target: { source: "workspace", path: "readme.md" },
              trigger: event.currentTarget,
            })
          }
        >
          Open preview
        </button>
        <div className="sender">
          <textarea aria-label="Chat input" defaultValue="Draft " />
        </div>
      </section>
      <AnimatePresence initial={false}>
        {state.kind !== "closed" && (
          <FilesDrawer
            state={state}
            dispatch={dispatch}
            scope={{
              kind: "session",
              agentId: "default",
              sessionId: "session-1",
            }}
          />
        )}
      </AnimatePresence>
    </>
  );
}

describe("FilesDrawer", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(agentsApi, "getAgent").mockResolvedValue({
      id: "default",
      name: "Default",
      running: { memory_manager_backend: "remelight" },
    });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it.each(["fullscreen", "tablet"])(
    "closes the %s overlay before focusing a file mention in chat",
    async (mode) => {
      const mediaQuery = window.matchMedia("(max-width: 1024px)");
      vi.stubGlobal(
        "matchMedia",
        vi.fn((query: string) => ({
          ...mediaQuery,
          media: query,
          matches: mode === "tablet" && query === "(max-width: 1024px)",
        })),
      );
      const user = userEvent.setup();
      renderWithProviders(<PreviewFocusHarness />);
      const composer = screen.getByRole("textbox", { name: "Chat input" });
      await user.click(composer);
      await user.keyboard("{End}");
      const trigger = screen.getByRole("button", { name: "Open preview" });
      await user.click(trigger);
      await screen.findByRole("button", { name: "common.copy" });
      if (mode === "fullscreen") {
        await user.click(
          screen.getByRole("button", { name: "files.enterFullscreen" }),
        );
      }
      await user.click(
        screen.getByRole("button", { name: "files.mentionInChat" }),
      );
      await waitFor(() => {
        expect(composer).toHaveValue("Draft @ readme.md ");
        expect(composer).toHaveFocus();
        expect(screen.queryByRole("region")).not.toBeInTheDocument();
        expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
      });
      expect(trigger).not.toHaveFocus();
    },
  );

  it("cycles fullscreen focus and restores the trigger on close", async () => {
    vi.spyOn(HTMLElement.prototype, "getClientRects").mockReturnValue([
      new DOMRect(0, 0, 40, 40),
    ] as unknown as DOMRectList);
    const user = userEvent.setup();
    renderWithProviders(<PreviewFocusHarness />);
    const trigger = screen.getByRole("button", { name: "Open preview" });
    await user.click(trigger);
    const first = await screen.findByRole("button", { name: "common.copy" });
    await user.click(
      screen.getByRole("button", { name: "files.enterFullscreen" }),
    );
    expect(screen.getByRole("dialog")).toHaveAttribute("aria-modal", "true");
    const background = screen.getByTestId("chat-background");
    expect(background).toHaveAttribute("inert");
    const last = screen.getByRole("button", { name: "files.expandWorkspace" });
    last.focus();
    await user.tab();
    expect(first).toHaveFocus();
    await user.tab({ shift: true });
    expect(last).toHaveFocus();
    await user.keyboard("{Escape}");
    const fullscreen = screen.getByRole("button", {
      name: "files.enterFullscreen",
    });
    expect(fullscreen).toHaveFocus();
    expect(background).not.toHaveAttribute("inert");
    await user.click(fullscreen);
    await user.click(screen.getByRole("button", { name: "common.close" }));
    await waitFor(() => expect(trigger).toHaveFocus());
    expect(background).not.toHaveAttribute("inert");
  });

  it("restores existing background inert attributes on unmount", async () => {
    const user = userEvent.setup();
    const { unmount } = renderWithProviders(<PreviewFocusHarness />);
    await user.click(screen.getByRole("button", { name: "Open preview" }));
    await screen.findByRole("button", { name: "common.copy" });
    const background = screen.getByTestId("chat-background");
    background.setAttribute("inert", "already-inert");
    fireEvent.click(
      screen.getByRole("button", { name: "files.enterFullscreen" }),
    );
    expect(background).toHaveAttribute("inert", "");
    unmount();
    expect(background).toHaveAttribute("inert", "already-inert");
    expect(document.body).not.toHaveAttribute("inert");
  });

  it("restores the saved width after toggling fullscreen", async () => {
    localStorage.setItem("qwenpaw-files-preview-width", "480");
    const dispatch = vi.fn();
    renderWithProviders(
      <FilesDrawer
        state={{
          kind: "preview",
          target: { source: "workspace", path: "readme.md" },
          trigger: null,
        }}
        dispatch={dispatch}
        scope={{
          kind: "session",
          agentId: "default",
          sessionId: "session-1",
        }}
      />,
    );
    await screen.findByRole("button", { name: "common.copy" });
    const drawer = screen.getByRole("region");
    expect(drawer).toHaveStyle({ width: "480px" });

    fireEvent.click(
      screen.getByRole("button", { name: "files.enterFullscreen" }),
    );
    expect(drawer.className).toContain("drawerFullscreen");
    expect(drawer.style.width).toBe("");
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "files.exitFullscreen" }),
    );
    expect(drawer.className).not.toContain("drawerFullscreen");
    expect(drawer).toHaveStyle({ width: "480px" });
    expect(screen.getByRole("separator")).toBeInTheDocument();
    expect(localStorage.getItem("qwenpaw-files-preview-width")).toBe("480");
    expect(dispatch).not.toHaveBeenCalled();
  });

  it("exits fullscreen before closing the preview with Escape", async () => {
    const dispatch = vi.fn();
    renderWithProviders(
      <FilesDrawer
        state={{
          kind: "preview",
          target: { source: "workspace", path: "readme.md" },
          trigger: null,
        }}
        dispatch={dispatch}
        scope={{
          kind: "session",
          agentId: "default",
          sessionId: "session-1",
        }}
      />,
    );
    await screen.findByRole("button", { name: "common.copy" });
    const toggle = screen.getByRole("button", {
      name: "files.enterFullscreen",
    });
    toggle.focus();
    fireEvent.click(toggle);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(dispatch).not.toHaveBeenCalled();
    expect(toggle).toHaveAccessibleName("files.enterFullscreen");
    expect(toggle).toHaveFocus();

    fireEvent.keyDown(document, { key: "Escape" });
    expect(dispatch).toHaveBeenCalledExactlyOnceWith({ type: "CLOSE" });
  });

  it("keeps file actions working in fullscreen", async () => {
    const { downloadFileFromUrl } = await import(
      "../../utils/downloadFileFromUrl"
    );
    const dispatch = vi.fn();
    vi.mocked(workspaceApi.loadFileText).mockResolvedValueOnce({
      content: "# Fullscreen document",
      etag: "v1",
    });
    renderWithProviders(
      <FilesDrawer
        state={{
          kind: "preview",
          target: { source: "workspace", path: "readme.md" },
          trigger: null,
        }}
        dispatch={dispatch}
        scope={{
          kind: "session",
          agentId: "default",
          sessionId: "session-1",
        }}
      />,
    );
    const heading = await screen.findByRole("heading", {
      name: "Fullscreen document",
    });
    fireEvent.click(
      screen.getByRole("button", { name: "files.enterFullscreen" }),
    );
    expect(heading).toBeInTheDocument();
    expect(workspaceApi.loadFileText).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "common.copy" }));
    await waitFor(() => {
      expect(clipboardMocks.copyText).toHaveBeenCalledWith(
        "# Fullscreen document",
      );
    });
    fireEvent.click(screen.getByRole("button", { name: "files.download" }));
    expect(downloadFileFromUrl).toHaveBeenCalledWith(
      "/api/files/download/readme.md",
      "readme.md",
      expect.any(Object),
    );
    fireEvent.click(screen.getByRole("button", { name: "common.close" }));
    expect(dispatch).toHaveBeenCalledExactlyOnceWith({ type: "CLOSE" });
  });

  it("opens Markdown relatives in the same preview root", async () => {
    vi.mocked(workspaceApi.loadFileText).mockResolvedValueOnce({
      content: "[next](./b.md)",
      etag: "v1",
    });
    const dispatch = vi.fn();
    renderWithProviders(
      <FilesDrawer
        state={{
          kind: "preview",
          target: {
            source: "workspace",
            root: "workspace",
            path: "docs/a.md",
          },
          trigger: null,
        }}
        dispatch={dispatch}
        scope={{
          kind: "session",
          agentId: "default",
          sessionId: "session-1",
          chatId: "chat-1",
        }}
      />,
    );
    fireEvent.click(await screen.findByRole("link", { name: "next" }));
    expect(dispatch).toHaveBeenCalledWith({
      type: "OPEN_PREVIEW",
      target: { source: "workspace", root: "workspace", path: "docs/b.md" },
      trigger: null,
    });
  });

  it.each(["Escape", "close button"])(
    "restores the original trigger after Markdown navigation and %s",
    async (closeMethod) => {
      vi.mocked(workspaceApi.loadFileText)
        .mockResolvedValueOnce({ content: "[next](./b.md)", etag: "v1" })
        .mockResolvedValueOnce({ content: "# Linked document", etag: "v2" });
      const user = userEvent.setup();

      function PreviewHarness() {
        const [state, dispatch] = useReducer(filesDrawerReducer, {
          kind: "closed",
        });
        return (
          <>
            <button
              type="button"
              onClick={(event) =>
                dispatch({
                  type: "OPEN_PREVIEW",
                  target: {
                    source: "workspace",
                    root: "workspace",
                    path: "docs/a.md",
                  },
                  trigger: event.currentTarget,
                })
              }
            >
              Open preview
            </button>
            {state.kind !== "closed" && (
              <FilesDrawer
                state={state}
                dispatch={dispatch}
                scope={{
                  kind: "session",
                  agentId: "default",
                  sessionId: "session-1",
                  chatId: "chat-1",
                }}
              />
            )}
          </>
        );
      }

      renderWithProviders(<PreviewHarness />);
      const trigger = screen.getByRole("button", { name: "Open preview" });
      await user.click(trigger);
      await user.click(await screen.findByRole("link", { name: "next" }));
      expect(
        await screen.findByRole("heading", { name: "Linked document" }),
      ).toBeInTheDocument();

      if (closeMethod === "Escape") {
        await user.keyboard("{Escape}");
      } else {
        await user.click(screen.getByRole("button", { name: "common.close" }));
      }

      await waitFor(() => expect(trigger).toHaveFocus());
      expect(screen.queryByRole("region")).not.toBeInTheDocument();
    },
  );

  it.each(["adbpg", "powercontext"])(
    "keeps preview tags as text for %s",
    async (backend) => {
      vi.mocked(agentsApi.getAgent).mockResolvedValue({
        id: "default",
        name: "Default",
        running: { memory_manager_backend: backend },
      });
      vi.mocked(workspaceApi.loadFileText).mockResolvedValueOnce({
        content: "---\nmemory_tags: [Orion]\n---\n# Memory",
        etag: "v1",
      });
      renderWithProviders(
        <FilesDrawer
          state={{
            kind: "preview",
            target: {
              source: "workspace",
              root: "workspace",
              path: "memory/note.md",
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
      const tag = await screen.findByText("Orion");
      expect(tag).toBeInTheDocument();
      expect(tag.tagName).toBe("SPAN");
    },
  );

  it("expands a memory preview and carries the clicked tag into the workspace", async () => {
    vi.mocked(workspaceApi.loadFileText).mockResolvedValueOnce({
      content: "---\nmemory_tags: [赵六, Orion]\n---\n# Memory",
      etag: "v1",
    });
    function PreviewHarness() {
      const [state, dispatch] = useReducer(filesDrawerReducer, {
        kind: "preview",
        target: {
          source: "workspace",
          root: "workspace",
          path: "memory/note.md",
        },
        trigger: null,
      });
      return state.kind === "closed" ? null : (
        <FilesDrawer
          state={state}
          dispatch={dispatch}
          scope={{
            kind: "session",
            agentId: "default",
            sessionId: "session-1",
          }}
        />
      );
    }
    renderWithProviders(<PreviewHarness />);
    await waitFor(() =>
      expect(screen.getByText("Orion").tagName).toBe("BUTTON"),
    );
    fireEvent.click(screen.getByText("Orion"));
    expect(await screen.findByTestId("files-workspace")).toHaveAttribute(
      "data-memory-tag",
      "Orion",
    );
  });

  it("copies the complete text file content", async () => {
    clipboardMocks.copyText.mockClear();
    clipboardMocks.success.mockClear();
    const user = userEvent.setup();

    renderWithProviders(
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
        dispatch={vi.fn()}
        scope={{
          kind: "session",
          agentId: "default",
          sessionId: "session-1",
        }}
      />,
    );

    const copyButton = await screen.findByRole("button", {
      name: /copy|复制/i,
    });
    const downloadButton = screen.getByRole("button", {
      name: /download|下载/i,
    });

    expect(
      copyButton.compareDocumentPosition(downloadButton) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await user.click(copyButton);

    await waitFor(() => {
      expect(clipboardMocks.copyText).toHaveBeenCalledWith("hello");
      expect(clipboardMocks.success).toHaveBeenCalled();
    });
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
    vi.spyOn(drawer, "getBoundingClientRect")
      .mockReturnValueOnce({ width: 500 } as DOMRect)
      .mockReturnValue({ width: 600 } as DOMRect);
    vi.spyOn(drawer.parentElement!, "getBoundingClientRect").mockReturnValue({
      width: 1200,
    } as DOMRect);
    fireEvent.pointerDown(separator, { clientX: 420 });
    expect(drawer.className).toContain("drawerResizing");

    fireEvent.pointerMove(window, { clientX: 320 });
    fireEvent.pointerUp(window);
    await waitFor(() => {
      expect(drawer.className).not.toContain("drawerResizing");
    });
    expect(drawer).toHaveStyle({ width: "600px" });
    expect(localStorage.getItem("qwenpaw-files-workspace-width")).toBe("600");
  });

  it("uses left and right arrow keys from the right-side resize edge", async () => {
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
    vi.spyOn(drawer.parentElement!, "getBoundingClientRect").mockReturnValue({
      width: 1200,
    } as DOMRect);

    fireEvent.keyDown(separator, { key: "ArrowLeft" });
    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "664px" });
    });

    fireEvent.keyDown(separator, { key: "ArrowRight" });
    await waitFor(() => {
      expect(drawer).toHaveStyle({ width: "640px" });
    });
  });

  it("applies persisted widths when the drawer mode changes", () => {
    localStorage.setItem("qwenpaw-files-preview-width", "480");
    localStorage.setItem("qwenpaw-files-workspace-width", "720");
    const dispatch = vi.fn();
    const scope = {
      kind: "session" as const,
      agentId: "default",
      sessionId: "session-1",
    };
    const target = {
      source: "workspace",
      path: "hello.txt",
      root: "project",
    } satisfies FileTarget;
    const { rerender } = renderWithProviders(
      <FilesDrawer
        state={{ kind: "preview", target, trigger: null }}
        dispatch={dispatch}
        scope={scope}
      />,
    );

    expect(screen.getByRole("region")).toHaveStyle({ width: "480px" });

    rerender(
      <FilesDrawer
        state={{ kind: "workspace", target, trigger: null }}
        dispatch={dispatch}
        scope={scope}
      />,
    );

    expect(screen.getByRole("region")).toHaveStyle({ width: "720px" });
  });

  // -------------------------------------------------------------------------
  // Download button — regression for #4670
  // Clicking the download button in the preview header must trigger the
  // downloadFileFromUrl helper with the correct URL and filename.
  // -------------------------------------------------------------------------
  it("download button triggers downloadFileFromUrl on click (#4670)", async () => {
    const { downloadFileFromUrl } = await import(
      "../../utils/downloadFileFromUrl"
    );
    const user = userEvent.setup();

    renderWithProviders(
      <FilesDrawer
        state={{
          kind: "preview",
          target: {
            source: "workspace",
            path: "docs/readme.md",
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

    const downloadBtn = await screen.findByRole("button", {
      name: /files\.download|下载/i,
    });
    expect(downloadBtn).toBeInTheDocument();

    await user.click(downloadBtn);

    await waitFor(() => {
      expect(downloadFileFromUrl).toHaveBeenCalledOnce();
    });
    // Verify the URL and filename passed to the download helper
    expect(downloadFileFromUrl).toHaveBeenCalledWith(
      expect.stringContaining("readme.md"),
      "readme.md",
      expect.objectContaining({
        headers: expect.any(Object),
      }),
    );
  });

  it("does not show download button for profile source (#4670)", async () => {
    renderWithProviders(
      <FilesDrawer
        state={{
          kind: "preview",
          target: {
            source: "profile",
            path: "config.yaml",
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

    await waitFor(() =>
      expect(workspaceApi.loadFile).toHaveBeenCalledWith(
        "config.yaml",
        "default",
      ),
    );

    // Profile source should not have a download button
    expect(
      screen.queryByRole("button", {
        name: /files\.download|下载/i,
      }),
    ).not.toBeInTheDocument();
  });
});
