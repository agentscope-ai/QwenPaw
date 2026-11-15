// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ResourceReportModal } from "./ResourceReportModal";

vi.mock("./PostComposer", () => ({
  PostComposer: ({ initialBody }: { initialBody: string }) => (
    <div data-testid="post-prefill">{initialBody}</div>
  ),
}));

const mocks = vi.hoisted(() => ({
  generate: vi.fn(),
  resolve: vi.fn(),
  copy: vi.fn(),
  open: vi.fn(),
  success: vi.fn(),
}));
vi.mock("@/api/modules/communityReport", () => ({
  generateCommunityReport: (...args: unknown[]) => mocks.generate(...args),
}));
vi.mock("@/api/modules/community", () => ({
  resolveCommunityFeedbackLink: (...args: unknown[]) => mocks.resolve(...args),
}));
vi.mock("@/utils/clipboard", () => ({
  copyText: (...args: unknown[]) => mocks.copy(...args),
}));
vi.mock("@/utils/openExternalLink", () => ({
  openExternalLink: (...args: unknown[]) => mocks.open(...args),
}));
vi.mock("@/hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { success: mocks.success } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key, i18n: { language: "en" } }),
}));

const origin = {
  provider: "agentscope-platform" as const,
  resource_type: "plugin" as const,
  resource_id: "@owner/demo",
  installed_version: "1.2",
};
function renderModal() {
  return render(
    <ResourceReportModal
      open
      onClose={vi.fn()}
      origin={origin}
      resourceName="Demo"
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.resolve.mockResolvedValue({
    url: "https://platform.agentscope.io/community/ask?relatedPluginId=demo",
  });
  mocks.copy.mockResolvedValue(undefined);
});

describe("resource report workflow", () => {
  it("keeps manual input when no model is available", async () => {
    mocks.generate.mockRejectedValue(new Error("model_not_available"));
    renderModal();
    const editor = screen.getByLabelText("communityReport.report");
    fireEvent.change(editor, { target: { value: "The menu is empty" } });
    fireEvent.click(
      screen.getByRole("button", { name: "communityReport.generate" }),
    );
    await screen.findByText("communityReport.noModel");
    expect((editor as HTMLTextAreaElement).value).toBe("The menu is empty");
  });

  it("cancels the request and ignores a late completion", async () => {
    let finish!: (value: { report: string }) => void;
    mocks.generate.mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    renderModal();
    const editor = screen.getByLabelText("communityReport.report");
    fireEvent.change(editor, { target: { value: "Keep this draft" } });
    fireEvent.click(
      screen.getByRole("button", { name: "communityReport.generate" }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "communityReport.cancelGeneration",
      }),
    );
    expect(mocks.generate.mock.calls[0][1].aborted).toBe(true);
    finish({ report: "Late completion" });
    await waitFor(() =>
      expect((editor as HTMLTextAreaElement).value).toBe("Keep this draft"),
    );
  });

  it("requires material review and sends only redacted text", async () => {
    mocks.generate.mockResolvedValue({ report: "Organized report" });
    renderModal();
    fireEvent.click(screen.getByText("communityReport.materials"));
    fireEvent.change(screen.getByLabelText("communityReport.logs"), {
      target: { value: "access_token=abc123\n503" },
    });
    expect(
      screen
        .getByRole("button", { name: "communityReport.generate" })
        .hasAttribute("disabled"),
    ).toBe(true);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "communityReport.reviewMaterials" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "communityReport.generate" }),
    );
    await waitFor(() => expect(mocks.generate).toHaveBeenCalledOnce());
    expect(mocks.generate.mock.calls[0][0].logs).not.toContain("abc123");
    expect(mocks.generate.mock.calls[0][0].materials_reviewed).toBe(true);
  });

  it("fills the reviewed report into the post form without copying", async () => {
    renderModal();
    fireEvent.change(screen.getByLabelText("communityReport.report"), {
      target: { value: "Final reviewed report" },
    });
    expect(
      screen
        .getByRole("button", { name: "communityReport.copy" })
        .hasAttribute("disabled"),
    ).toBe(true);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "communityReport.confirmReport" }),
    );
    expect(mocks.copy).not.toHaveBeenCalled();
    const next = screen.getByRole("button", {
      name: "communityReport.continue",
    });
    await waitFor(() => expect(next.hasAttribute("disabled")).toBe(false));
    fireEvent.click(next);
    expect(screen.getByTestId("post-prefill")).toHaveTextContent(
      "Final reviewed report",
    );
    expect(mocks.open).not.toHaveBeenCalled();
  });
});
