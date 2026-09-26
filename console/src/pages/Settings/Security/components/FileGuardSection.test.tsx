// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { FileGuardSection } from "./FileGuardSection";

const mock = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
  t: (key: string) => key,
  message: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), destroy: vi.fn() },
}));
vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mock.t }) }));
vi.mock("@agentscope-ai/design", async () => await vi.importActual("antd"));
vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mock.message }),
}));
vi.mock("../../../../api", () => ({
  default: { getFileGuard: mock.get, updateFileGuard: mock.update },
}));

describe("FileGuardSection paths", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mock.get.mockResolvedValue({ enabled: true, paths: ["~/.ssh/"] });
    mock.update.mockResolvedValue({});
  });
  it("preserves Windows paths and flushes the new path on navigation", async () => {
    const view = render(<FileGuardSection />);
    await screen.findByText("~/.ssh/");
    fireEvent.click(
      screen.getByRole("button", { name: "security.fileGuard.add" }),
    );
    const input = screen.getByRole("textbox", {
      name: "security.fileGuard.path",
    });
    const path = String.raw`C:\Users\Alice\Documents\private file.txt`;
    fireEvent.change(input, { target: { value: path } });
    fireEvent.keyDown(input, {
      key: "Enter",
      code: "Enter",
      charCode: 13,
      keyCode: 13,
    });
    await screen.findByText(path);
    view.unmount();
    await waitFor(() =>
      expect(mock.update).toHaveBeenCalledWith({ paths: ["~/.ssh/", path] }),
    );
  });
  it("keeps configured paths visible while disabled and prevents additions", async () => {
    mock.get.mockResolvedValue({ enabled: false, paths: ["/etc/passwd"] });
    render(<FileGuardSection />);
    await screen.findByText("/etc/passwd");
    expect(
      screen.getByRole("button", { name: "security.fileGuard.add" }),
    ).toBeDisabled();
    expect(screen.getByText("common.disabled")).toBeVisible();
    expect(mock.update).not.toHaveBeenCalled();
  });
});
