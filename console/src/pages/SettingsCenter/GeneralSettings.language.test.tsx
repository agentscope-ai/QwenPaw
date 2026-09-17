import { screen, fireEvent, waitFor, within } from "@testing-library/react";
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

import GeneralSettings from "./GeneralSettings";

describe("GeneralSettings language persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem("language");
  });

  it("surfaces a rejected remote write to the user", async () => {
    mocks.updateLanguage.mockRejectedValue(new Error("HTTP 400"));
    vi.spyOn(console, "error").mockImplementation(() => {});

    renderWithProviders(<GeneralSettings />);

    // General Settings now hosts several Select controls (language,
    // theme palette, close behaviour), so scope to the language row
    // instead of querying the first combobox on the page.
    const languageRow = screen
      .getByText("sidebar.settings.language")
      .closest("div")!;
    fireEvent.mouseDown(within(languageRow).getByRole("combobox"));
    fireEvent.click(await screen.findByText("Tiếng Việt"));

    expect(mocks.changeLanguage).toHaveBeenCalledWith("vi");
    expect(mocks.updateLanguage).toHaveBeenCalledWith("vi");
    // The selector still switched locally, so without this toast the
    // user has no way to learn the server kept the old preference.
    expect(localStorage.getItem("language")).toBe("vi");
    // Assert on the rendered notice rather than spying on a message
    // instance: the component takes message from App.useApp(), so a
    // spy on the statically imported one would miss it.
    await waitFor(() =>
      expect(
        screen.getByText("agentConfig.languageSaveFailed"),
      ).toBeInTheDocument(),
    );
  });
});
