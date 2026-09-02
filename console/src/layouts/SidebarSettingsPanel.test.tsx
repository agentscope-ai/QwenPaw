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
import { GITHUB_URL } from "./constants";

function last<T>(items: T[]): T {
  return items[items.length - 1];
}

describe("SidebarSettingsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem("qwenpaw_tool_display_mode");
    localStorage.removeItem("qwenpaw_assistant_message_display_mode");
    localStorage.removeItem("qwenpaw_show_thinking");
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
    await userEvent.click(appearanceButton);
    expect(appearanceButton).toHaveClass("ant-popover-open");
    const language = last(await screen.findAllByText("Language"));
    const appearance = within(language.closest(".ant-popover")!);
    expect(appearance.getByText("Language")).toBeInTheDocument();
    expect(appearance.getByText("Theme")).toBeInTheDocument();
    expect(appearance.getByText("Content width")).toBeInTheDocument();
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

  it("exposes the three message display controls", async () => {
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

    expect(messageDisplay.getByText("Tool display")).toBeInTheDocument();
    expect(
      messageDisplay.getByText("Assistant message collapse"),
    ).toBeInTheDocument();
  });

  it("expands documentation links and opens GitHub directly", async () => {
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
    expect(screen.getByRole("button", { name: "Feature demos" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Changelog" })).toBeVisible();
    expect(screen.getByRole("button", { name: "FAQ" })).toBeVisible();

    const githubButton = screen.getByRole("button", { name: "GitHub" });
    await userEvent.click(githubButton);
    expect(githubButton).not.toHaveClass("ant-popover-open");
    expect(mocks.openExternalLink).toHaveBeenCalledWith(GITHUB_URL);
  });
});
