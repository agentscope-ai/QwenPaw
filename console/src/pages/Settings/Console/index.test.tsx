import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { screen } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import ConsoleSettingsPage from "./index";
import { resetHistoryPageSizeForTests } from "@/pages/Chat/sessionApi/historyPageSize";

vi.mock("@/pages/Chat/sessionApi", () => ({
  default: {
    reloadAfterPageSizeChange: vi.fn(),
  },
}));

describe("Console settings page", () => {
  beforeEach(() => {
    resetHistoryPageSizeForTests();
  });

  afterEach(() => {
    resetHistoryPageSizeForTests();
  });

  it("renders the chat history page size field", () => {
    renderWithProviders(<ConsoleSettingsPage />);
    expect(screen.getByTestId("settings-history-page-size")).toBeTruthy();
  });
});
