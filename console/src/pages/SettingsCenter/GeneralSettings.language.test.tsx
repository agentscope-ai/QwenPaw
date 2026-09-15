import { screen, fireEvent, waitFor } from "@testing-library/react";
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

import GeneralSettings from "./GeneralSettings";

describe("GeneralSettings language persistence", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.removeItem("language");
  });

  it("surfaces a rejected remote write to the user", async () => {
    mocks.updateLanguage.mockRejectedValue(new Error("HTTP 400"));
    const errorSpy = vi
      .spyOn(message, "error")
      .mockImplementation(() => ({}) as never);
    vi.spyOn(console, "error").mockImplementation(() => {});

    renderWithProviders(<GeneralSettings />);

    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(await screen.findByText("Tiếng Việt"));

    expect(mocks.changeLanguage).toHaveBeenCalledWith("vi");
    expect(mocks.updateLanguage).toHaveBeenCalledWith("vi");
    // The selector still switched locally, so without this toast the
    // user has no way to learn the server kept the old preference.
    expect(localStorage.getItem("language")).toBe("vi");
    await waitFor(() =>
      expect(errorSpy).toHaveBeenCalledWith("agentConfig.languageSaveFailed"),
    );
  });
});
