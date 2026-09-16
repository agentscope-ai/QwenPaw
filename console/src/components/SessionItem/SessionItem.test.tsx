import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SessionItem from ".";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) =>
      key === "appCenter.moreActions" ? "More actions" : key,
  }),
}));

describe("SessionItem status indicator", () => {
  it.each([
    {
      name: "running takes priority",
      props: { chatStatus: "running" as const, unseenResult: true },
      label: "chat.statusInProgress",
    },
    {
      name: "completed but unseen",
      props: { chatStatus: "idle" as const, unseenResult: true },
      label: "chat.statusUnseenResult",
    },
    {
      name: "idle and seen",
      props: { chatStatus: "idle" as const, unseenResult: false },
      label: "chat.statusIdle",
    },
  ])("renders $name", ({ props, label }) => {
    render(<SessionItem sessionId="chat-1" name="Chat" {...props} />);

    expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
  });
});

describe("SessionItem actions", () => {
  it("hides the drag hint while keeping the more actions menu", async () => {
    render(<SessionItem sessionId="chat-1" name="Chat" />);

    expect(document.querySelector("svg.lucide-grip-vertical")).toBeNull();

    const moreButton = screen.getByRole("button", { name: "More actions" });
    expect(moreButton).toBeInTheDocument();
    fireEvent.click(moreButton);

    expect(
      await screen.findByRole("menuitem", {
        name: "chat.contextMenu.rename",
      }),
    ).toBeInTheDocument();
  });
});
