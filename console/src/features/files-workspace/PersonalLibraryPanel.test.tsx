import { act, render, screen, within } from "@testing-library/react";
import { message } from "antd";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import PersonalLibraryPanel from "./PersonalLibraryPanel";
import { clearAccessSession } from "../../api/authSession";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  listPage: vi.fn(),
  upload: vi.fn(),
  move: vi.fn(),
  remove: vi.fn(),
  indexStatus: vi.fn(),
  rebuildIndex: vi.fn(),
}));

vi.mock("../../api/modules/personalLibrary", () => ({
  personalLibraryApi: mocks,
}));

const document = {
  id: "doc-a",
  name: "合同.md",
  relative_path: "采购/合同.md",
  size: 20,
  media_type: "text/markdown",
  sha256: "a",
  created_at: "2026-11-07T00:00:00Z",
  updated_at: "2026-11-07T00:00:00Z",
};

describe("PersonalLibraryPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("zh");
    mocks.listPage.mockReset();
    mocks.upload.mockReset();
    mocks.listPage.mockResolvedValue({ items: [], total: 0 });
    mocks.move.mockReset();
    mocks.remove.mockReset();
    mocks.list.mockReset().mockResolvedValue([]);
    mocks.indexStatus.mockReset().mockResolvedValue([]);
    mocks.rebuildIndex.mockReset().mockResolvedValue([]);
    mocks.upload.mockResolvedValue({
      id: "doc-upload",
      relative_path: "guide.pdf",
      name: "guide.pdf",
      media_type: "application/pdf",
      size: 1,
      sha256: "b".repeat(64),
      created_at: "2026-09-04T00:00:00Z",
      updated_at: "2026-09-04T00:00:00Z",
    });
  });

  it("only exposes upload instead of Markdown creation", async () => {
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);

    expect(
      await screen.findByRole("button", { name: "上传文件" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "新建 Markdown" }),
    ).not.toBeInTheDocument();
  });

  it("uploads a local file into the personal library", async () => {
    const user = userEvent.setup();
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);

    const file = new File(["guide"], "guide.pdf", { type: "application/pdf" });
    await user.upload(await screen.findByLabelText("上传文件"), file);

    expect(mocks.upload).toHaveBeenCalledWith(file, { agentId: "agent-a" });
  });

  it("shows the upload failure instead of silently ignoring it", async () => {
    const user = userEvent.setup();
    const error = vi
      .spyOn(message, "error")
      .mockImplementation(() => undefined as never);
    mocks.upload.mockRejectedValueOnce(new Error("upload rejected"));
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);

    await user.upload(
      await screen.findByLabelText("上传文件"),
      new File(["x"], "guide.txt"),
    );

    expect(error).toHaveBeenCalledWith("上传个人资料库文件失败");
    error.mockRestore();
  });

  it("explains a same-name upload conflict in user-facing language", async () => {
    const user = userEvent.setup();
    const error = vi
      .spyOn(message, "error")
      .mockImplementation(() => undefined as never);
    mocks.upload.mockRejectedValueOnce(
      new Error(
        'library_document_exists - {"detail":"library_document_exists"}',
      ),
    );
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);

    await user.upload(
      await screen.findByLabelText("上传文件"),
      new File(["x"], "guide.txt"),
    );

    expect(error).toHaveBeenCalledWith(
      "个人资料库中已存在同名文件，请先刷新并更换文件名后重试。",
    );
    error.mockRestore();
  });

  it("does not show the previous agent's late list response", async () => {
    let resolveAgentA!: (value: unknown) => void;
    mocks.listPage
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveAgentA = resolve;
          }),
      )
      .mockResolvedValueOnce({
        items: [
          { id: "doc-b", name: "agent-b.md", relative_path: "agent-b.md" },
        ],
        total: 1,
      });
    const { rerender } = render(
      <PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />,
    );

    rerender(<PersonalLibraryPanel requestContext={{ agentId: "agent-b" }} />);
    expect((await screen.findAllByText("agent-b.md"))[0]).toBeVisible();
    await act(async () =>
      resolveAgentA({
        items: [
          { id: "doc-a", name: "agent-a.md", relative_path: "agent-a.md" },
        ],
        total: 1,
      }),
    );

    await vi.waitFor(() =>
      expect(screen.queryByText("agent-a.md")).not.toBeInTheDocument(),
    );
    expect(mocks.listPage).toHaveBeenNthCalledWith(
      1,
      "",
      0,
      20,
      { agentId: "agent-a" },
      expect.any(AbortSignal),
    );
    expect(mocks.listPage).toHaveBeenNthCalledWith(
      2,
      "",
      0,
      20,
      { agentId: "agent-b" },
      expect.any(AbortSignal),
    );
  });

  it("renames within the same directory with the selected document revision", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    mocks.listPage.mockResolvedValue({ items: [document], total: 1 });
    mocks.move.mockResolvedValue({
      ...document,
      name: "正式合同.md",
      relative_path: "采购/正式合同.md",
    });
    render(
      <PersonalLibraryPanel
        requestContext={{ agentId: "agent-a" }}
        onDocumentChanged={onChanged}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "重命名" }));
    const dialog = within(screen.getByRole("dialog"));
    await user.clear(dialog.getByLabelText("保存路径"));
    await user.type(dialog.getByLabelText("保存路径"), "正式合同.md");
    await user.click(dialog.getByRole("button", { name: "确 认" }));
    expect(mocks.move).toHaveBeenCalledWith(document, "采购/正式合同.md", {
      agentId: "agent-a",
    });
    expect(onChanged).toHaveBeenCalledWith(
      "doc-a",
      expect.objectContaining({ relative_path: "采购/正式合同.md" }),
    );
  });

  it("keeps a failed move dialog open with a useful conflict message", async () => {
    const user = userEvent.setup();
    mocks.listPage.mockResolvedValue({ items: [document], total: 1 });
    mocks.move.mockRejectedValue(new Error("library_document_changed"));
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);
    await user.click(await screen.findByRole("button", { name: "移 动" }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "确 认" }),
    );
    expect(
      within(screen.getByRole("dialog")).getByRole("alert"),
    ).toHaveTextContent("文件已被修改，请取消操作并刷新列表后重试。");
  });

  it("requires confirmation to delete and returns from a now-empty last page", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    mocks.listPage
      .mockResolvedValueOnce({ items: [document], total: 21 })
      .mockResolvedValueOnce({ items: [document], total: 21 })
      .mockResolvedValueOnce({ items: [], total: 20 })
      .mockResolvedValue({
        items: [{ ...document, id: "remaining", name: "剩余.md" }],
        total: 20,
      });
    mocks.remove.mockResolvedValue(undefined);
    render(
      <PersonalLibraryPanel
        requestContext={{ agentId: "agent-a" }}
        onDocumentChanged={changed}
      />,
    );
    await user.click(await screen.findByTitle("2"));
    await user.click(await screen.findByRole("button", { name: "删 除" }));
    expect(mocks.remove).not.toHaveBeenCalled();
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "确 认" }),
    );
    expect(changed).toHaveBeenCalledWith(document.id, null);
    expect(
      await screen.findByRole("button", { name: "剩余.md" }),
    ).toBeVisible();
    expect(mocks.listPage).toHaveBeenLastCalledWith(
      "",
      0,
      20,
      { agentId: "agent-a" },
      expect.any(AbortSignal),
    );
  });

  it("searches on the server and resets pagination", async () => {
    const user = userEvent.setup();
    mocks.listPage.mockResolvedValue({ items: [document], total: 21 });
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);
    await user.click(await screen.findByTitle("2"));
    await user.type(screen.getByLabelText("搜索文件名或路径"), "合同{Enter}");
    expect(mocks.listPage).toHaveBeenLastCalledWith(
      "合同",
      0,
      20,
      { agentId: "agent-a" },
      expect.any(AbortSignal),
    );
  });

  it("discards an old scope's pending mutation and dialog after switching agents", async () => {
    const user = userEvent.setup();
    const changed = vi.fn();
    let finish!: (value: unknown) => void;
    mocks.listPage.mockResolvedValue({ items: [document], total: 1 });
    mocks.move.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { rerender } = render(
      <PersonalLibraryPanel
        requestContext={{ agentId: "agent-a" }}
        onDocumentChanged={changed}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "重命名" }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "确 认" }),
    );
    mocks.listPage.mockResolvedValue({ items: [], total: 0 });
    rerender(
      <PersonalLibraryPanel
        requestContext={{ agentId: "agent-b" }}
        onDocumentChanged={changed}
      />,
    );
    await act(async () => finish(document));
    expect(changed).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(mocks.listPage).toHaveBeenCalledTimes(2);
  });

  it("clears rows and dialogs immediately when the authenticated identity is cleared", async () => {
    const user = userEvent.setup();
    mocks.listPage
      .mockResolvedValueOnce({ items: [document], total: 1 })
      .mockResolvedValue({ items: [], total: 0 });
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);
    await user.click(await screen.findByRole("button", { name: "删 除" }));
    act(() => clearAccessSession(false));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "合同.md" }),
    ).not.toBeInTheDocument();
  });

  it("shows extraction state and rebuilds the whole library across pages", async () => {
    const user = userEvent.setup();
    const guide = {
      ...document,
      name: "guide.pdf",
      relative_path: "guide.pdf",
    };
    const other = { ...guide, id: "doc-other", name: "other.pdf" };
    mocks.listPage.mockResolvedValue({ items: [guide], total: 21 });
    mocks.list.mockResolvedValue([guide, other]);
    mocks.indexStatus.mockResolvedValue([
      { document_id: "doc-a", status: "failed" },
    ]);
    mocks.rebuildIndex.mockResolvedValue([
      { document_id: "doc-a", status: "ready" },
      { document_id: "doc-other", status: "ready" },
    ]);
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);
    expect(await screen.findByText("解析失败")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "重建索引" }));
    expect(await screen.findByText("可检索")).toBeVisible();
    expect(screen.getByRole("button", { name: "guide.pdf" })).toBeVisible();
    expect(mocks.list).toHaveBeenCalledWith("", { agentId: "agent-a" });
    expect(mocks.rebuildIndex).toHaveBeenCalledWith(
      ["doc-a", "doc-other"],
      { agentId: "agent-a" },
      expect.any(AbortSignal),
    );
  });

  it("keeps documents openable when index status fails", async () => {
    const guide = {
      ...document,
      name: "guide.pdf",
      relative_path: "guide.pdf",
    };
    mocks.listPage.mockResolvedValue({ items: [guide], total: 1 });
    mocks.indexStatus.mockRejectedValue(new Error("index offline"));
    const onOpen = vi.fn();
    render(
      <PersonalLibraryPanel
        requestContext={{ agentId: "agent-a" }}
        onOpen={onOpen}
      />,
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "guide.pdf" }),
    );
    expect(onOpen).toHaveBeenCalledWith({
      category: "library",
      agentId: "agent-a",
      stableId: "doc-a",
      relativePath: "guide.pdf",
    });
    expect(
      screen.getByText("索引状态暂不可用，仍可打开资料文件。"),
    ).toBeVisible();
  });

  it("ignores rebuild response after switching agents", async () => {
    const guide = { ...document, name: "a.pdf", relative_path: "a.pdf" };
    let finish!: (value: unknown[]) => void;
    mocks.listPage
      .mockResolvedValueOnce({ items: [guide], total: 1 })
      .mockResolvedValueOnce({
        items: [{ ...guide, id: "doc-b", name: "b.pdf" }],
        total: 1,
      });
    mocks.list.mockResolvedValue([guide]);
    mocks.rebuildIndex.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const { rerender } = render(
      <PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />,
    );
    await screen.findByRole("button", { name: "a.pdf" });
    await userEvent.click(screen.getByRole("button", { name: "重建索引" }));
    const signal = mocks.rebuildIndex.mock.calls[0][2];
    rerender(<PersonalLibraryPanel requestContext={{ agentId: "agent-b" }} />);
    await screen.findByRole("button", { name: "b.pdf" });
    expect(signal.aborted).toBe(true);
    await act(async () => finish([{ document_id: "doc-b", status: "ready" }]));
    expect(screen.queryByText("可检索")).not.toBeInTheDocument();
  });
});
