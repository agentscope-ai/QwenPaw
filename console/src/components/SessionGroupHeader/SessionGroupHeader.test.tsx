import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderWithProviders } from "@/test/common_setup";
import type { ChatGroup } from "../../api/types/chat";
import SessionGroupHeader from "./index";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (_key: string, fallback?: string) => fallback ?? _key,
  }),
}));

const group: ChatGroup = {
  id: "project",
  name: "Project",
  order: 0,
  kind: "custom",
  pinned: false,
};

describe("SessionGroupHeader", () => {
  it("toggles from the header keyboard target and prevents space scrolling", () => {
    const onToggle = vi.fn();
    renderWithProviders(
      <SessionGroupHeader
        group={group}
        count={3}
        collapsed={false}
        onToggle={onToggle}
      />,
    );

    const header = screen.getByRole("button", { name: /Project/ });
    const event = new KeyboardEvent("keydown", {
      key: " ",
      bubbles: true,
      cancelable: true,
    });
    fireEvent(header, event);

    expect(event.defaultPrevented).toBe(true);
    expect(onToggle).toHaveBeenCalledOnce();
  });

  it("allows spaces and enter while renaming without toggling the group", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const onRename = vi.fn();
    renderWithProviders(
      <SessionGroupHeader
        group={group}
        count={3}
        collapsed={false}
        onToggle={onToggle}
        onRename={onRename}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Manage group" }));
    await user.click(await screen.findByText("Rename"));

    const input = screen.getByRole("textbox");
    await user.type(input, " Alpha");
    expect(input).toHaveValue("Project Alpha");
    expect(onToggle).not.toHaveBeenCalled();

    await user.keyboard("{Enter}");
    expect(onRename).toHaveBeenCalledWith("Project Alpha");
    expect(onToggle).not.toHaveBeenCalled();
  });
});
