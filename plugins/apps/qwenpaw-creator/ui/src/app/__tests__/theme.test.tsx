import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { ThemeProvider, useTheme } from "@/app/theme";

function ThemeProbe() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  return (
    <div>
      <span data-testid="theme">{theme}</span>
      <span data-testid="resolved-theme">{resolvedTheme}</span>
      <button type="button" onClick={() => setTheme("dark")}>
        dark
      </button>
    </div>
  );
}

const getItem = vi.fn();
const setItem = vi.fn();

beforeEach(() => {
  getItem.mockReset().mockReturnValue(null);
  setItem.mockReset();
  vi.stubGlobal("localStorage", { getItem, setItem });
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.classList.remove("dark", "dark-mode");
});

describe("local ThemeProvider", () => {
  it("persists and applies the selected theme in the Vite app", async () => {
    render(
      <ThemeProvider defaultTheme="light">
        <ThemeProbe />
      </ThemeProvider>,
    );

    expect(screen.getByTestId("theme")).toHaveTextContent("light");
    fireEvent.click(screen.getByRole("button", { name: "dark" }));

    await waitFor(() => {
      expect(screen.getByTestId("resolved-theme")).toHaveTextContent("dark");
      expect(document.documentElement).toHaveClass("dark", "dark-mode");
      expect(setItem).toHaveBeenCalledWith("qwenpaw-theme", "dark");
    });
  });
});
