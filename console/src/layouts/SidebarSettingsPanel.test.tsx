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
    const onOpenAbout = vi.fn();

    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          version="2.2.0b3"
          onClose={onClose}
          onOpenSettings={onOpenSettings}
          onOpenAbout={onOpenAbout}
        />
      </ThemeProvider>,
    );

    expect(screen.getByText("QwenPaw v2.2.0b3")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Settings" }));
    expect(onClose).toHaveBeenCalledOnce();
    expect(onOpenSettings).toHaveBeenCalledOnce();

    await userEvent.click(
      screen.getByRole("button", { name: "About QwenPaw" }),
    );
    expect(onOpenAbout).toHaveBeenCalledOnce();
  });

  it("opens appearance and GitHub submenus", async () => {
    renderWithProviders(
      <ThemeProvider>
        <SidebarSettingsPanel
          version="2.2.0b3"
          onOpenSettings={vi.fn()}
          onOpenAbout={vi.fn()}
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
    expect(appearance.getByLabelText("theme.light")).toBeInTheDocument();
    expect(appearance.getByLabelText("theme.dark")).toBeInTheDocument();
    expect(appearance.getByLabelText("theme.system")).toBeInTheDocument();

    const githubButton = screen.getByRole("button", { name: "GitHub" });
    await userEvent.click(githubButton);
    expect(githubButton).toHaveClass("ant-popover-open");
    const repository = last(await screen.findAllByText("Repository"));
    const github = within(repository.closest(".ant-popover")!);
    const issues = github.getByRole("button", { name: "Issues" });
    expect(
      github.getByRole("button", { name: "Repository" }),
    ).toBeInTheDocument();
    expect(
      github.getByRole("button", { name: "Releases" }),
    ).toBeInTheDocument();

    await userEvent.click(issues);
    expect(mocks.openExternalLink).toHaveBeenCalledWith(`${GITHUB_URL}/issues`);
  });
});
