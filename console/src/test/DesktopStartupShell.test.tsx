import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "./common_setup";
import { useMessageQueueStore } from "../stores/messageQueueStore";
import DesktopStartupShell from "../tauri/DesktopStartupShell";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, fallback?: string) => fallback ?? key,
  }),
}));

describe("DesktopStartupShell", () => {
  beforeEach(() => {
    useMessageQueueStore.getState().clear("new");
  });

  it("persists one startup message in the existing chat queue", () => {
    renderWithProviders(<DesktopStartupShell />);

    fireEvent.change(screen.getByLabelText("First message"), {
      target: { value: "Summarize my unread work" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send message" }));

    const queue = useMessageQueueStore.getState().getQueue("new");
    expect(queue).toHaveLength(1);
    expect(queue[0]).toMatchObject({
      text: "Summarize my unread work",
      status: "pending",
    });
    expect(screen.getByRole("status")).toHaveTextContent("Message queued");
    expect(screen.getByLabelText("First message")).toBeDisabled();
  });
});
