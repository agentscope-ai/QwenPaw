import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../../i18n";
import TemporaryAttachmentsPanel from "./TemporaryAttachmentsPanel";

const mocks = vi.hoisted(() => ({ listAttachments: vi.fn(), copyAttachment: vi.fn() }));

vi.mock("../../api/modules/chat", () => ({
  chatApi: { listAttachments: mocks.listAttachments },
}));

vi.mock("../../api/modules/personalLibrary", () => ({
  personalLibraryApi: { copyAttachment: mocks.copyAttachment },
}));

describe("TemporaryAttachmentsPanel", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("zh");
    mocks.listAttachments.mockResolvedValue([
      {
        id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        agent_id: "agent-a",
        conversation_id: null,
        message_id: null,
        original_name: "report.pdf",
        media_type: "application/pdf",
        size: 128,
        lifecycle: "temporary",
        saved_path: null,
        saved_at: null,
        deleted_at: null,
        created_at: "2026-09-02T12:00:00Z",
        updated_at: "2026-09-02T12:00:00Z",
        download_url:
          "/api/console/attachments/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        can_save: true,
        can_move: false,
        can_delete: true,
      },
    ]);
  });

  it("copies a temporary attachment only after the user chooses a library destination", async () => {
    const user = userEvent.setup();
    mocks.copyAttachment.mockResolvedValue({ relative_path: "references/report.pdf" });
    render(<TemporaryAttachmentsPanel requestContext={{ agentId: "agent-a" }} />);

    expect(await screen.findByText("report.pdf")).toBeVisible();
    expect(screen.getByRole("region", { name: "临时附件" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "保存到个人资料库" }));
    const destination = screen.getByLabelText("保存路径");
    await user.clear(destination);
    await user.type(destination, "references/invoice.pdf");
    await user.click(screen.getByRole("button", { name: /确\s*认/ }));
    expect(mocks.copyAttachment).toHaveBeenCalledWith({
      attachmentId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
      destinationPath: "references/invoice.pdf",
    }, { agentId: "agent-a" });
  });
});
