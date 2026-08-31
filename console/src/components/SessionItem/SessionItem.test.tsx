import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import SessionItem from ".";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
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
    render(
      <SessionItem
        variant="drawer"
        sessionId="chat-1"
        name="Chat"
        {...props}
      />,
    );

    expect(screen.getByRole("img", { name: label })).toBeInTheDocument();
  });
});
