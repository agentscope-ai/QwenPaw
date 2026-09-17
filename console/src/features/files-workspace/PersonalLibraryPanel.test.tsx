import { render, screen } from "@testing-library/react";
import { message } from "antd";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import PersonalLibraryPanel from "./PersonalLibraryPanel";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  upload: vi.fn(),
}));

vi.mock("../../api/modules/personalLibrary", () => ({
  personalLibraryApi: mocks,
}));

describe("PersonalLibraryPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("zh");
    mocks.list.mockReset();
    mocks.upload.mockReset();
    mocks.list.mockResolvedValue([]);
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

    expect(await screen.findByRole("button", { name: "上传文件" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "新建 Markdown" })).not.toBeInTheDocument();
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
    const error = vi.spyOn(message, "error").mockImplementation(() => undefined as never);
    mocks.upload.mockRejectedValueOnce(new Error("upload rejected"));
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);

    await user.upload(await screen.findByLabelText("上传文件"), new File(["x"], "guide.txt"));

    expect(error).toHaveBeenCalledWith("upload rejected");
    error.mockRestore();
  });

  it("explains a same-name upload conflict in user-facing language", async () => {
    const user = userEvent.setup();
    const error = vi.spyOn(message, "error").mockImplementation(() => undefined as never);
    mocks.upload.mockRejectedValueOnce(new Error('library_document_exists - {"detail":"library_document_exists"}'));
    render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);

    await user.upload(await screen.findByLabelText("上传文件"), new File(["x"], "guide.txt"));

    expect(error).toHaveBeenCalledWith("个人资料库中已存在同名文件，请先刷新并更换文件名后重试。");
    error.mockRestore();
  });

  it("does not show the previous agent's late list response", async () => {
    let resolveAgentA!: (value: unknown[]) => void;
    mocks.list
      .mockImplementationOnce(() => new Promise((resolve) => { resolveAgentA = resolve; }))
      .mockResolvedValueOnce([{ id: "doc-b", name: "agent-b.md", relative_path: "agent-b.md" }]);
    const { rerender } = render(<PersonalLibraryPanel requestContext={{ agentId: "agent-a" }} />);

    rerender(<PersonalLibraryPanel requestContext={{ agentId: "agent-b" }} />);
    expect((await screen.findAllByText("agent-b.md"))[0]).toBeVisible();
    resolveAgentA([{ id: "doc-a", name: "agent-a.md", relative_path: "agent-a.md" }]);

    await vi.waitFor(() => expect(screen.queryByText("agent-a.md")).not.toBeInTheDocument());
    expect(mocks.list).toHaveBeenNthCalledWith(1, "", { agentId: "agent-a" });
    expect(mocks.list).toHaveBeenNthCalledWith(2, "", { agentId: "agent-b" });
  });
});
