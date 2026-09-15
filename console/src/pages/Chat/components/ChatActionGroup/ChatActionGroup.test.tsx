import { describe, it, expect, vi } from "vitest";
import { fireEvent, screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";

import ChatActionGroup from "./index";

describe("ChatActionGroup", () => {
  it("renders without crash", () => {
    expect(() => renderWithProviders(<ChatActionGroup />)).not.toThrow();
  });

  it("does not render the former history or overflow actions", () => {
    renderWithProviders(<ChatActionGroup />);
    expect(
      document.querySelector('[data-icon="SparkHistoryLine"]'),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".anticon-more")).not.toBeInTheDocument();
  });

  it("renders the shared new task icon button", () => {
    renderWithProviders(<ChatActionGroup />);
    expect(
      document.querySelector('[data-icon="SparkNewChatLine"]'),
    ).toBeInTheDocument();
  });

  it("offers normal and Voice Chat from the new-chat split menu", async () => {
    const onCreateVoiceChat = vi.fn();
    renderWithProviders(
      <ChatActionGroup onCreateVoiceChat={onCreateVoiceChat} />,
    );

    expect(
      document.querySelector('[data-icon="SparkVoiceChat01Line"]'),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "chat.newChatMenu" }));
    fireEvent.click(
      await screen.findByRole("menuitem", {
        name: "realtimeVoice.newChat",
      }),
    );

    expect(onCreateVoiceChat).toHaveBeenCalledOnce();
  });

  it("renders the Session workspace toggle next to essential actions", () => {
    const onToggleWorkspace = vi.fn();
    renderWithProviders(
      <ChatActionGroup onToggleWorkspace={onToggleWorkspace} />,
    );

    const button = document.querySelector(
      'button[aria-label="files.openWorkspace"]',
    ) as HTMLButtonElement | null;
    expect(button).toBeInTheDocument();
    expect(button).toHaveStyle({
      width: "32px",
      height: "32px",
      padding: "0px",
    });
    expect(button?.querySelector("svg")).toHaveAttribute("width", "16");
    expect(button?.querySelector("svg")).toHaveAttribute("height", "16");
    expect(button?.querySelector("svg")).toHaveStyle({
      width: "16px",
      height: "16px",
    });
    button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    expect(onToggleWorkspace).toHaveBeenCalledOnce();
  });
});
