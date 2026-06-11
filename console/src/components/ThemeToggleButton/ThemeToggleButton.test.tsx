import { describe, it, expect, vi } from "vitest";
import { screen } from "@testing-library/react";
import ThemeToggleButton from "./index";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { render } from "@testing-library/react";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

// Wrap with real ThemeProvider, control initial theme via localStorage
function renderWithTheme(mode: "light" | "dark" | "system" = "light") {
  localStorage.setItem("qwenpaw-theme", mode);
  return render(
    <ThemeProvider>
      <ThemeToggleButton />
    </ThemeProvider>,
  );
}

describe("ThemeToggleButton", () => {
  it("renders the theme toggle button", () => {
    renderWithTheme("light");
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("shows sun icon when light mode is active", () => {
    renderWithTheme("light");
    // Component uses lucide Sun icon after shadcn migration
    expect(document.querySelector(".lucide-sun")).toBeInTheDocument();
  });

  it("shows moon icon when dark mode is active", () => {
    renderWithTheme("dark");
    // Component uses lucide Moon icon after shadcn migration
    expect(document.querySelector(".lucide-moon")).toBeInTheDocument();
  });

  it("shows sun-moon icon when system mode is active", () => {
    renderWithTheme("system");
    expect(document.querySelector(".lucide-sun-moon")).toBeInTheDocument();
  });

  it("renders without crashing", () => {
    expect(() => renderWithTheme("light")).not.toThrow();
  });
});
