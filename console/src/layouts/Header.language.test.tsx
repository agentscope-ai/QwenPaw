import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { message } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { renderWithProviders } from "@/test/common_setup";

const mocks = vi.hoisted(() => ({
  updateLanguage: vi.fn(),
  changeLanguage: vi.fn(),
}));

vi.mock("@/api/modules/language", () => ({
  settingsApi: { updateLanguage: mocks.updateLanguage },
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: {
      language: "en",
      resolvedLanguage: "en",
      changeLanguage: mocks.changeLanguage,
    },
    t: (key: string) => key,
  }),
}));

vi.mock("../contexts/ThemeContext", () => ({
  useTheme: () => ({ themeMode: "light", setThemeMode: vi.fn() }),
}));
vi.mock("../plugins/registry/Slot", () => ({ Slot: () => null }));
vi.mock("../utils/openExternalLink", () => ({
  openExternalLink: vi.fn(),
}));
vi.mock("./AppBrand", () => ({ default: () => null }));
vi.mock("../components/ThemeToggleButton", () => ({ default: () => null }));
// Keep the real LANGUAGE_LIST so the menu is built from the same
// single source the app uses; only stub the desktop switcher itself.
vi.mock("../components/LanguageSwitcher/index", async (importActual) => {
  const actual = await importActual<Record<string, unknown>>();
  return { ...actual, default: () => null };
});

import Header from "./Header";

async function openMobileLanguageMenu() {
  const trigger = screen.getByTitle("header.resources");
  await userEvent.hover(trigger);
  const languageGroup = await screen.findByText("sidebar.settings.language");
  await userEvent.hover(languageGroup);
  return screen.findByText("Tiếng Việt");
}

describe("Header mobile language menu persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem("language");
  });

  it("persists the choice remotely, which it previously never did", async () => {
    mocks.updateLanguage.mockResolvedValue({ language: "vi" });

    renderWithProviders(<Header showBrand />);
    const option = await openMobileLanguageMenu();
    await userEvent.click(option);

    expect(mocks.changeLanguage).toHaveBeenCalledWith("vi");
    expect(localStorage.getItem("language")).toBe("vi");
    expect(mocks.updateLanguage).toHaveBeenCalledWith("vi");
  });

  it("surfaces a rejected remote write to the user", async () => {
    mocks.updateLanguage.mockRejectedValue(new Error("HTTP 400"));
    const errorSpy = vi
      .spyOn(message, "error")
      .mockImplementation(() => ({}) as never);
    vi.spyOn(console, "error").mockImplementation(() => {});

    renderWithProviders(<Header showBrand />);
    const option = await openMobileLanguageMenu();
    await userEvent.click(option);

    expect(localStorage.getItem("language")).toBe("vi");
    await waitFor(() =>
      expect(errorSpy).toHaveBeenCalledWith("agentConfig.languageSaveFailed"),
    );
  });
});
