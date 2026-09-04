import { fireEvent, render, screen } from "@testing-library/react";
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

describe("SessionItem keyboard selection", () => {
  it.each(["Enter", " "])("selects the focused session with %s", (key) => {
    const onClick = vi.fn();
    render(
      <SessionItem
        variant="drawer"
        sessionId="chat-keyboard"
        name="Keyboard chat"
        onClick={onClick}
      />,
    );
    const row = screen.getByText("Keyboard chat").closest('[role="button"]')!;
    fireEvent.keyDown(row, { key });
    fireEvent.keyDown(row, { key, repeat: true });
    expect(onClick).toHaveBeenCalledExactlyOnceWith("chat-keyboard");
  });

  it("does not select a session while submitting its rename input", () => {
    const onClick = vi.fn();
    const onEditSubmit = vi.fn();
    render(
      <SessionItem
        variant="drawer"
        sessionId="chat-editing"
        name="Original"
        editing
        editValue="Renamed"
        onClick={onClick}
        onEditSubmit={onEditSubmit}
      />,
    );
    const input = screen.getByRole("textbox");
    expect(input).toBeEnabled();
    expect(input.closest('[aria-disabled="true"]')).toBeNull();
    fireEvent.change(input, { target: { value: "Renamed" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onEditSubmit).toHaveBeenCalledOnce();
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps disabled sessions out of keyboard navigation", () => {
    const onClick = vi.fn();
    render(
      <SessionItem
        variant="drawer"
        sessionId="chat-disabled"
        name="Disabled chat"
        disabled
        onClick={onClick}
      />,
    );
    const row = screen.getByText("Disabled chat").closest('[role="button"]')!;
    expect(row).toHaveAttribute("tabindex", "-1");
    expect(row).toHaveAttribute("aria-disabled", "true");
    fireEvent.keyDown(row, { key: "Enter" });
    expect(onClick).not.toHaveBeenCalled();
  });
});
