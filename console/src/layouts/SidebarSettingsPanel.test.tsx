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

  it("uses cascading preferences without dropdown controls", async () => {
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          version="2.2.0b3"
          onOpenDesktopMode={vi.fn()}
          onOpenSettings={vi.fn()}
        />
      </ThemeProvider>,
    );

    const preferencesButton = screen.getByRole("button", {
      name: "Preferences",
    });
    await userEvent.click(preferencesButton);
    expect(preferencesButton).toHaveClass("ant-popover-open");
    const language = last(await screen.findAllByText("Language"));
    const preferences = within(language.closest(".ant-popover")!);
    expect(preferences.getByText("Language")).toBeInTheDocument();
    expect(preferences.getByText("Theme")).toBeInTheDocument();
    expect(preferences.getByText("Content width")).toBeInTheDocument();
    expect(preferences.getByText("Desktop mode")).toBeInTheDocument();
    expect(document.querySelector(".ant-select")).not.toBeInTheDocument();
    expect(document.querySelector(".ant-segmented")).not.toBeInTheDocument();

    await userEvent.click(
      preferences.getByRole("button", { name: "Language" }),
    );
    const english = last(await screen.findAllByText("English"));
    const languages = within(english.closest(".ant-popover")!);
    expect(languages.getByText("简体中文")).toBeInTheDocument();
    expect(languages.getByText("Português")).toBeInTheDocument();
  });

  it("opens desktop mode from preferences", async () => {
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

    await userEvent.click(screen.getByRole("button", { name: "Preferences" }));
    await userEvent.click(
      last(await screen.findAllByRole("button", { name: "Desktop mode" })),
    );

    expect(onOpenDesktopMode).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
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
