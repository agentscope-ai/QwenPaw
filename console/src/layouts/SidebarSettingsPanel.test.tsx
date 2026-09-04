import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider } from "@/contexts/ThemeContext";
import { renderWithProviders } from "@/test/common_setup";

const mocks = vi.hoisted(() => ({
  openExternalLink: vi.fn(),
  updateLanguage: vi.fn(() => Promise.resolve()),
}));

vi.mock("../utils/openExternalLink", () => ({
  openExternalLink: mocks.openExternalLink,
}));

vi.mock("../api/modules/language", () => ({
  languageApi: { updateLanguage: mocks.updateLanguage },
}));

import SidebarSettingsPanel from "./SidebarSettingsPanel";

function last<T>(items: T[]): T {
  return items[items.length - 1];
}

describe("SidebarSettingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem("qwenpaw_tool_display_mode");
    localStorage.removeItem("qwenpaw_assistant_message_display_mode");
    localStorage.removeItem("qwenpaw_show_thinking");
    localStorage.removeItem("qwenpaw_chat_wide_mode");
  });

  it("keeps Settings as an action and displays the current version", async () => {
    const onClose = vi.fn();
    const onOpenSettings = vi.fn();
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          version="2.2.0b3"
          onClose={onClose}
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={onOpenSettings}
        />
      </ThemeProvider>,
    );

    expect(screen.getByText("v2.2.0b3")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onOpenSettings).toHaveBeenCalledOnce();

    await userEvent.click(
      screen.getByRole("button", { name: /About QwenPaw/ }),
    );
    expect(mocks.openExternalLink).toHaveBeenCalledWith(
      "https://qwenpaw.agentscope.io/",
    );
  });

  it("uses cascading appearance controls without dropdowns", async () => {
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          version="2.2.0b3"
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={vi.fn()}
        />
      </ThemeProvider>,
    );

    const appearanceButton = screen.getByRole("button", {
      name: "Appearance",
    });
    expect(appearanceButton).toHaveAttribute("aria-haspopup", "menu");
    expect(appearanceButton).toHaveAttribute("aria-expanded", "false");
    await userEvent.click(appearanceButton);
    expect(appearanceButton).toHaveClass("ant-popover-open");
    expect(appearanceButton).toHaveAttribute("aria-expanded", "true");
    const language = last(await screen.findAllByText("Language"));
    const appearance = within(language.closest(".ant-popover")!);
    expect(appearance.getByText("Language")).toBeInTheDocument();
    expect(appearance.getByText("Theme")).toBeInTheDocument();
    expect(appearance.queryByText("Message width")).not.toBeInTheDocument();
    expect(appearance.getByText("Desktop mode")).toBeInTheDocument();
    expect(document.querySelector(".ant-select")).not.toBeInTheDocument();
    expect(document.querySelector(".ant-segmented")).not.toBeInTheDocument();

    await userEvent.click(appearance.getByRole("button", { name: "Language" }));
    expect(appearanceButton).toHaveClass("ant-popover-open");
    const english = last(await screen.findAllByText("English"));
    const languages = within(english.closest(".ant-popover")!);
    expect(languages.getByText("简体中文")).toBeInTheDocument();
    expect(languages.getByText("Português")).toBeInTheDocument();
  });

  it("opens cascading controls on hover", async () => {
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={vi.fn()}
        />
      </ThemeProvider>,
    );

    await userEvent.hover(screen.getByRole("button", { name: "Appearance" }));
    const language = last(
      await screen.findAllByRole("button", { name: "Language" }),
    );
    await userEvent.hover(language);

    const simplifiedChinese = last(await screen.findAllByText("简体中文"));
    expect(simplifiedChinese.closest(".ant-popover")).not.toHaveClass(
      "ant-popover-hidden",
    );
  });

  it("opens desktop mode from appearance", async () => {
    const onClose = vi.fn();
    const onOpenDesktopMode = vi.fn();
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          onClose={onClose}
          onOpenDesktopMode={onOpenDesktopMode}
          onOpenSettings={vi.fn()}
        />
      </ThemeProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Appearance" }));
    await userEvent.click(
      last(await screen.findAllByRole("button", { name: "Desktop mode" })),
    );

    expect(onOpenDesktopMode).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("exposes the four message display controls", async () => {
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={vi.fn()}
        />
      </ThemeProvider>,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Message display" }),
    );
    const thinking = last(
      await screen.findAllByRole("button", { name: "Show thinking" }),
    );
    const messageDisplay = within(thinking.closest(".ant-popover")!);

    expect(messageDisplay.getByText("Message width")).toBeInTheDocument();
    expect(messageDisplay.getByText("Tool display")).toBeInTheDocument();
    expect(
      messageDisplay.getByText("Assistant message collapse"),
    ).toBeInTheDocument();
  });

  it("persists message width changes from quick settings", async () => {
    const onClose = vi.fn();
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          onClose={onClose}
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={vi.fn()}
        />
      </ThemeProvider>,
    );

    await userEvent.hover(
      screen.getByRole("button", { name: "Message display" }),
    );
    const messageWidth = last(
      await screen.findAllByRole("button", { name: "Message width" }),
    );
    await userEvent.hover(messageWidth);
    await userEvent.click(last(await screen.findAllByText("Wide")));

    expect(localStorage.getItem("qwenpaw_chat_wide_mode")).toBe("true");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows the compact documentation links", () => {
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          version="2.2.0b3"
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={vi.fn()}
        />
      </ThemeProvider>,
    );

    expect(screen.getByRole("button", { name: "Tutorial" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Changelog" })).toBeVisible();
    expect(screen.getByRole("button", { name: "FAQ" })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Feature demos" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "GitHub" }),
    ).not.toBeInTheDocument();
  });

  it("shows account actions only when authentication is enabled", async () => {
    const onClose = vi.fn();
    const onOpenAccount = vi.fn();
    const onLogout = vi.fn();
    const { rerender } = renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          onClose={onClose}
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={vi.fn()}
        />
      </ThemeProvider>,
    );

    expect(
      screen.queryByRole("button", { name: "Account" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Logout" }),
    ).not.toBeInTheDocument();

    rerender(
      <ThemeProvider>
        <SidebarSettingsPanel
          authEnabled
          onClose={onClose}
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={vi.fn()}
          onOpenAccount={onOpenAccount}
          onLogout={onLogout}
        />
      </ThemeProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Account" }));
    expect(onOpenAccount).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();

    await userEvent.click(screen.getByRole("button", { name: "Logout" }));
    expect(onLogout).toHaveBeenCalledOnce();
  });
});
