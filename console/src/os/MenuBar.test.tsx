import { beforeEach, describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { useOsNotify } from "./osNotifyStore";
import { useOsWindows } from "./osWindowStore";
import MenuBar from "./MenuBar";

vi.mock("../components/LanguageSwitcher", () => ({
  default: () => <button type="button">Language switcher</button>,
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (
      key: string,
      options?: string | { approvals?: number; inbox?: number; name?: string },
    ) => {
      if (key === "os.notificationSummary" && typeof options === "object") {
        return `Approvals ${options.approvals} · Inbox ${options.inbox}`;
      }
      if (typeof options === "string") return options;
      return options?.name ?? key;
    },
  }),
}));

beforeEach(() => {
  useOsWindows.setState({
    activeId: null,
    spaceId: "default",
    missionControlOpen: false,
  });
  useOsNotify.setState({
    approvalCount: 0,
    inboxCount: 0,
    centerOpen: false,
  });
});

describe("MenuBar notification count", () => {
  it("includes the shared language switcher", () => {
    renderWithProviders(<MenuBar />);

    expect(
      screen.getByRole("button", { name: "Language switcher" }),
    ).toBeInTheDocument();
  });

  it("hides the count when there are no unread items", () => {
    renderWithProviders(<MenuBar />);

    expect(screen.queryByText("0")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Notifications: Approvals 0 · Inbox 0",
      }),
    ).toBeInTheDocument();
  });

  it("shows the combined approval and inbox count", () => {
    useOsNotify.setState({ approvalCount: 3, inboxCount: 5 });
    renderWithProviders(<MenuBar />);

    expect(screen.getByText("8")).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Notifications: Approvals 3 · Inbox 5",
      }),
    ).toBeInTheDocument();
  });

  it("caps large counts at 99+", () => {
    useOsNotify.setState({ approvalCount: 70, inboxCount: 40 });
    renderWithProviders(<MenuBar />);

    expect(screen.getByText("99+")).toBeInTheDocument();
  });
});
