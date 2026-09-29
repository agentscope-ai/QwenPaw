// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AllowNoAuthHostsTab } from "./AllowNoAuthHostsTab";
const mock = vi.hoisted(() => ({
  get: vi.fn(),
  update: vi.fn(),
  t: (key: string) => key,
  message: {
    success: vi.fn(),
    error: vi.fn(),
    warning: vi.fn(),
    destroy: vi.fn(),
  },
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: mock.t }) }));
vi.mock("@agentscope-ai/design", async () => await vi.importActual("antd"));
vi.mock("@number-flow/react", () => ({
  default: ({ value }: { value: number }) => <span>{value}</span>,
}));
vi.mock("../../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mock.message }),
}));
vi.mock("../../../../api", () => ({
  default: {
    getAllowNoAuthHosts: mock.get,
    updateAllowNoAuthHosts: mock.update,
  },
}));

describe("AllowNoAuthHostsTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mock.get.mockResolvedValue({ hosts: ["127.0.0.1", "::1"] });
    mock.update.mockResolvedValue({});
  });
  it("keeps invalid addresses visible for correction without saving", async () => {
    render(<AllowNoAuthHostsTab />);
    await screen.findByText("127.0.0.1");
    const input = screen.getByRole("textbox");
    fireEvent.change(input, { target: { value: "256.1.2.3" } });
    fireEvent.click(
      screen.getByRole("button", { name: "security.allowNoAuthHosts.add" }),
    );
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(
      screen.getByText("security.allowNoAuthHosts.invalidIP"),
    ).toBeVisible();
    expect(mock.update).not.toHaveBeenCalled();
  });
  it("preserves IPv6 and flushes on navigation", async () => {
    const view = render(<AllowNoAuthHostsTab />);
    await screen.findByText("127.0.0.1");
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "2001:db8::1" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "security.allowNoAuthHosts.add" }),
    );
    await screen.findByText("2001:db8::1");
    view.unmount();
    await waitFor(() =>
      expect(mock.update).toHaveBeenCalledWith({
        hosts: ["127.0.0.1", "::1", "2001:db8::1"],
      }),
    );
  });
  it("disables additions after load failure and retries the existing configuration", async () => {
    mock.get.mockRejectedValueOnce(new Error("offline"));
    render(<AllowNoAuthHostsTab />);
    fireEvent.click(
      await screen.findByRole("button", { name: "common.retry" }),
    );
    await screen.findByText("127.0.0.1");
    expect(mock.get).toHaveBeenCalledTimes(2);
    expect(mock.update).not.toHaveBeenCalled();
  });
});
