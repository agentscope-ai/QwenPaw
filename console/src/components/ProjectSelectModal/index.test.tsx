// @vitest-environment jsdom
/**
 * ProjectSelectModal render tests — regression family: settings
 * round-trip (selected project must survive the confirm flow) and
 * coding-mode entry paths.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import React from "react";
import { renderWithProviders } from "@/test/common_setup";

// ---- Hoisted mocks ---------------------------------------------------------

const mocks = vi.hoisted(() => ({
  cloneStream: vi.fn(),
  uploadZip: vi.fn(),
  browseDirs: vi.fn(),
  create: vi.fn(),
  list: vi.fn(),
  get: vi.fn(),
  set: vi.fn(),
  setProjectDir: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../api/modules/projectDirectory", () => ({
  projectDirectoryApi: {
    cloneStream: (...args: unknown[]) => mocks.cloneStream(...args),
    uploadZip: (...args: unknown[]) => mocks.uploadZip(...args),
    browseDirs: (...args: unknown[]) => mocks.browseDirs(...args),
    create: (...args: unknown[]) => mocks.create(...args),
    list: (...args: unknown[]) => mocks.list(...args),
    get: (...args: unknown[]) => mocks.get(...args),
    set: (...args: unknown[]) => mocks.set(...args),
  },
}));

vi.mock("../../stores/projectDirectoryStore", () => ({
  useProjectDir: () => ({ setProjectDir: mocks.setProjectDir }),
}));

// antd's Modal fires afterOpenChange only after the open animation runs,
// which never happens in jsdom. Replace Modal with a stub that renders
// children synchronously and calls afterOpenChange on mount.
vi.mock("antd", async () => {
  const actual = await vi.importActual<Record<string, unknown>>("antd");
  const ModalStub = ({
    open,
    children,
    afterOpenChange,
    title,
  }: {
    open?: boolean;
    children?: React.ReactNode;
    afterOpenChange?: (open: boolean) => void;
    title?: React.ReactNode;
  }) => {
    React.useEffect(() => {
      if (open && afterOpenChange) afterOpenChange(true);
    }, [open, afterOpenChange]);
    if (!open) return null;
    return React.createElement(
      "div",
      { "data-testid": "project-modal" },
      React.createElement("div", null, title),
      children,
    );
  };
  return { ...actual, Modal: ModalStub };
});

vi.mock("lucide-react", () => {
  const make = (name: string) =>
    function Icon() {
      return React.createElement("span", { "data-testid": `icon-${name}` });
    };
  return {
    ChevronRight: make("chevron"),
    Eye: make("eye"),
    EyeOff: make("eye-off"),
    Folder: make("folder"),
    FolderOpen: make("folder-open"),
    FolderSymlink: make("folder-symlink"),
    GitBranch: make("git-branch"),
    HardDrive: make("hard-drive"),
    Home: make("home"),
    PlusCircle: make("plus-circle"),
    RotateCcw: make("rotate"),
    X: make("x"),
  };
});

import ProjectSelectModal from "./index";

// ---- Helpers ---------------------------------------------------------------

function renderModal(open = true) {
  const onConfirm = vi.fn();
  const onClose = vi.fn();
  renderWithProviders(
    <ProjectSelectModal open={open} onClose={onClose} onConfirm={onConfirm} />,
  );
  return { onConfirm, onClose };
}

function sseResponse(
  events: Array<{ type: string; [key: string]: unknown }>,
): Response {
  // Trailing "\n\n" is required: the parser splits on blank-line delimiters
  // and drops any remainder left in the buffer when the stream ends.
  const body =
    events.map((e) => `data: ${JSON.stringify(e)}`).join("\n\n") + "\n\n";
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body));
      controller.close();
    },
  });
  return new Response(stream, { status: 200 });
}

beforeEach(() => {
  // jsdom does not implement Element.scrollTo/scrollIntoView; the browse
  // list scrolls to top after a fetch and the clone log box auto-scrolls
  // on new lines (real browsers support both). Polyfill.
  if (!window.HTMLElement.prototype.scrollTo) {
    window.HTMLElement.prototype.scrollTo = vi.fn();
  } else {
    vi.spyOn(window.HTMLElement.prototype, "scrollTo").mockImplementation(
      () => undefined,
    );
  }
  if (!window.HTMLElement.prototype.scrollIntoView) {
    window.HTMLElement.prototype.scrollIntoView = vi.fn();
  } else {
    vi.spyOn(window.HTMLElement.prototype, "scrollIntoView").mockImplementation(
      () => undefined,
    );
  }
  mocks.cloneStream
    .mockReset()
    .mockResolvedValue(sseResponse([{ type: "done", path: "/cloned/repo" }]));
  mocks.uploadZip.mockReset().mockResolvedValue({ path: "/uploaded" });
  mocks.browseDirs.mockReset().mockResolvedValue({
    current: "/home/user",
    parent: "/home",
    dirs: [
      { name: "projects", path: "/home/user/projects" },
      { name: "docs", path: "/home/user/docs" },
    ],
    selectable: true,
  });
  mocks.create.mockReset().mockResolvedValue({ path: "/new/project" });
  mocks.list.mockReset().mockResolvedValue([
    { name: "proj-a", path: "/proj-a", is_active: true },
    { name: "proj-b", path: "/proj-b", is_active: false },
  ]);
  mocks.get.mockReset().mockResolvedValue({ workspace_dir: "/ws" });
  mocks.set.mockReset().mockResolvedValue({});
  mocks.setProjectDir.mockClear();
});

// ---- Tests -----------------------------------------------------------------

describe("ProjectSelectModal", () => {
  it("renders the modal with tabs when open", async () => {
    renderModal();
    await waitFor(() => {
      expect(screen.getByText("codingMode.selectProject")).toBeTruthy();
    });
    expect(screen.getByText("codingMode.tabWorkspace")).toBeTruthy();
    expect(screen.getByText("codingMode.tabClone")).toBeTruthy();
  });

  it("does not render content when closed", () => {
    renderModal(false);
    expect(screen.queryByText("codingMode.selectProject")).toBeNull();
  });

  it("confirms the default workspace with a null path", async () => {
    const { onConfirm } = renderModal();
    await waitFor(() => {
      expect(screen.getByText("codingMode.confirmBtn")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("codingMode.confirmBtn"));
    await waitFor(() => {
      expect(mocks.set).toHaveBeenCalledWith(null);
      expect(onConfirm).toHaveBeenCalledWith(null);
      expect(mocks.setProjectDir).toHaveBeenCalledWith(null);
    });
  });

  it("shows the workspace directory when available", async () => {
    renderModal();
    await waitFor(() => {
      expect(screen.getByText("/ws")).toBeTruthy();
    });
  });

  it("switches to the clone tab and clones via SSE", async () => {
    const { onConfirm } = renderModal();
    await waitFor(() => {
      expect(screen.getByText("codingMode.tabClone")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("codingMode.tabClone"));
    const urlInput = screen.getByPlaceholderText(
      "codingMode.cloneUrlPlaceholder",
    );
    fireEvent.change(urlInput, {
      target: { value: "https://github.com/org/repo.git" },
    });
    fireEvent.click(screen.getByText("codingMode.cloneBtn"));
    await waitFor(() => {
      expect(mocks.cloneStream).toHaveBeenCalledWith(
        "https://github.com/org/repo.git",
        undefined,
      );
      expect(onConfirm).toHaveBeenCalledWith("/cloned/repo");
    });
  });

  it("streams log lines during cloning", async () => {
    mocks.cloneStream.mockResolvedValue(
      sseResponse([
        { type: "log", line: "Cloning into repo..." },
        { type: "log", line: "Resolving deltas" },
        { type: "done", path: "/cloned/repo" },
      ]),
    );
    renderModal();
    fireEvent.click(screen.getByText("codingMode.tabClone"));
    const urlInput = screen.getByPlaceholderText(
      "codingMode.cloneUrlPlaceholder",
    );
    fireEvent.change(urlInput, { target: { value: "https://x.com/a.git" } });
    fireEvent.click(screen.getByText("codingMode.cloneBtn"));
    await waitFor(() => {
      expect(screen.getByText("Cloning into repo...")).toBeTruthy();
      expect(screen.getByText("Resolving deltas")).toBeTruthy();
    });
  });

  it("surfaces clone errors from the SSE stream", async () => {
    mocks.cloneStream.mockResolvedValue(
      sseResponse([{ type: "error", detail: "auth required" }]),
    );
    renderModal();
    fireEvent.click(screen.getByText("codingMode.tabClone"));
    fireEvent.change(
      screen.getByPlaceholderText("codingMode.cloneUrlPlaceholder"),
      {
        target: { value: "https://x.com/a.git" },
      },
    );
    fireEvent.click(screen.getByText("codingMode.cloneBtn"));
    await waitFor(() => {
      expect(screen.getByText("auth required")).toBeTruthy();
    });
  });

  it("disables the clone button without a URL", async () => {
    renderModal();
    fireEvent.click(screen.getByText("codingMode.tabClone"));
    const btn = screen.getByText("codingMode.cloneBtn").closest("button");
    expect(btn?.disabled).toBe(true);
  });

  it("browses directories in the open-dir tab", async () => {
    renderModal();
    fireEvent.click(screen.getByText("codingMode.tabOpenDir"));
    await waitFor(() => {
      expect(mocks.browseDirs).toHaveBeenCalledWith("~", false);
      expect(screen.getByText("projects")).toBeTruthy();
      expect(screen.getByText("docs")).toBeTruthy();
    });
  });

  it("navigates into a directory and selects it", async () => {
    const { onConfirm } = renderModal();
    fireEvent.click(screen.getByText("codingMode.tabOpenDir"));
    await waitFor(() => {
      expect(screen.getByText("projects")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("projects"));
    await waitFor(() => {
      expect(mocks.browseDirs).toHaveBeenCalledWith(
        "/home/user/projects",
        false,
      );
    });
    // Select the current directory
    fireEvent.click(screen.getByText("codingMode.openDirBtn"));
    await waitFor(() => {
      expect(mocks.set).toHaveBeenCalled();
      expect(onConfirm).toHaveBeenCalled();
    });
  });

  it("toggles hidden folders and re-fetches", async () => {
    renderModal();
    fireEvent.click(screen.getByText("codingMode.tabOpenDir"));
    await waitFor(() => {
      expect(screen.getByText("projects")).toBeTruthy();
    });
    // Reset the call log so only the re-fetch triggered by the toggle remains
    mocks.browseDirs.mockClear();
    fireEvent.click(screen.getByText("codingMode.openDirHiddenFolders"));
    await waitFor(() => {
      // The toggle re-fetches the current directory with showHidden=true
      expect(
        mocks.browseDirs.mock.calls.some((call: unknown[]) => call[1] === true),
      ).toBe(true);
    });
  });

  it("shows a browse error from the API", async () => {
    mocks.browseDirs.mockRejectedValue(new Error("permission denied"));
    renderModal();
    fireEvent.click(screen.getByText("codingMode.tabOpenDir"));
    await waitFor(() => {
      expect(screen.getByText("permission denied")).toBeTruthy();
    });
  });

  it("creates a new project from the new-project tab", async () => {
    const { onConfirm } = renderModal();
    fireEvent.click(screen.getByText("codingMode.tabNew"));
    const input = screen.getByPlaceholderText("codingMode.newNamePlaceholder");
    fireEvent.change(input, { target: { value: "my-app" } });
    fireEvent.click(screen.getByText("codingMode.createBtn"));
    await waitFor(() => {
      expect(mocks.create).toHaveBeenCalledWith("my-app");
      expect(onConfirm).toHaveBeenCalledWith("/new/project");
    });
  });

  it("surfaces create errors", async () => {
    mocks.create.mockRejectedValue(new Error("name already exists"));
    renderModal();
    fireEvent.click(screen.getByText("codingMode.tabNew"));
    fireEvent.change(
      screen.getByPlaceholderText("codingMode.newNamePlaceholder"),
      {
        target: { value: "dup" },
      },
    );
    fireEvent.click(screen.getByText("codingMode.createBtn"));
    await waitFor(() => {
      expect(screen.getByText("name already exists")).toBeTruthy();
    });
  });

  it("disables the create button without a name", async () => {
    renderModal();
    fireEvent.click(screen.getByText("codingMode.tabNew"));
    const btn = screen.getByText("codingMode.createBtn").closest("button");
    expect(btn?.disabled).toBe(true);
  });

  it("lists recent projects and selects one on click", async () => {
    const { onConfirm } = renderModal();
    await waitFor(() => {
      expect(screen.getByText("proj-a")).toBeTruthy();
    });
    fireEvent.click(screen.getByText("proj-b"));
    await waitFor(() => {
      expect(mocks.set).toHaveBeenCalledWith("/proj-b");
      expect(onConfirm).toHaveBeenCalledWith("/proj-b");
    });
  });

  it("loads projects and workspace on open", async () => {
    renderModal();
    await waitFor(() => {
      expect(mocks.list).toHaveBeenCalled();
      expect(mocks.get).toHaveBeenCalled();
    });
  });
});
