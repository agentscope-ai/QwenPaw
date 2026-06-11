import { describe, it, expect, vi } from "vitest";
import { screen, fireEvent } from "@testing-library/react";
import { renderWithProviders } from "@/test/common_setup";
import { ThemeProvider } from "@/contexts/ThemeContext";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import HomePage from "./index";

// ── i18n mock ────────────────────────────────────────────────────────────────
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (k: string) => k }),
}));

// ── router mock ───────────────────────────────────────────────────────────────
const mockNavigate = vi.fn();
vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useNavigate: () => mockNavigate };
});

function renderHomePage(isDark = false) {
  localStorage.setItem("qwenpaw-theme", isDark ? "dark" : "light");
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>
    </ThemeProvider>,
  );
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("HomePage — suggestion cards", () => {
  it("renders all four suggestion cards", () => {
    renderHomePage();
    // SUGGESTION_CARDS has 4 entries; each renders as a button
    const cards = screen.getAllByRole("button");
    expect(cards.length).toBeGreaterThanOrEqual(4);
  });

  it("renders cards with correct i18n title keys", () => {
    renderHomePage();
    // t() returns the key itself so the rendered text is the key
    expect(screen.getByText("home.cards.chat.title")).toBeInTheDocument();
    expect(screen.getByText("home.cards.skills.title")).toBeInTheDocument();
    expect(screen.getByText("home.cards.mcp.title")).toBeInTheDocument();
    expect(screen.getByText("home.cards.settings.title")).toBeInTheDocument();
  });

  it("renders cards with correct i18n description keys", () => {
    renderHomePage();
    expect(screen.getByText("home.cards.chat.desc")).toBeInTheDocument();
    expect(screen.getByText("home.cards.skills.desc")).toBeInTheDocument();
    expect(screen.getByText("home.cards.mcp.desc")).toBeInTheDocument();
    expect(screen.getByText("home.cards.settings.desc")).toBeInTheDocument();
  });

  it("renders hero title and subtitle with i18n keys", () => {
    renderHomePage();
    expect(screen.getByText("home.title")).toBeInTheDocument();
    expect(screen.getByText("home.subtitle")).toBeInTheDocument();
  });
});

describe("HomePage — navigation on card click", () => {
  it("navigates to /chat when Chat card is clicked", () => {
    renderHomePage();
    fireEvent.click(screen.getByText("home.cards.chat.title").closest("button")!);
    expect(mockNavigate).toHaveBeenCalledWith("/chat");
  });

  it("navigates to /skills when Skills card is clicked", () => {
    renderHomePage();
    fireEvent.click(screen.getByText("home.cards.skills.title").closest("button")!);
    expect(mockNavigate).toHaveBeenCalledWith("/skills");
  });

  it("navigates to /mcp when MCP card is clicked", () => {
    renderHomePage();
    fireEvent.click(screen.getByText("home.cards.mcp.title").closest("button")!);
    expect(mockNavigate).toHaveBeenCalledWith("/mcp");
  });

  it("navigates to /agents when Settings card is clicked", () => {
    renderHomePage();
    fireEvent.click(screen.getByText("home.cards.settings.title").closest("button")!);
    expect(mockNavigate).toHaveBeenCalledWith("/agents");
  });
});

describe("HomePage — dark-mode CSS class smoke test", () => {
  it("root html element has dark-mode class when dark theme is active", () => {
    renderHomePage(true);
    // ThemeProvider adds 'dark-mode' to document.documentElement
    expect(document.documentElement.classList.contains("dark-mode")).toBe(true);
  });

  it("root html element does NOT have dark-mode class in light mode", () => {
    renderHomePage(false);
    expect(document.documentElement.classList.contains("dark-mode")).toBe(false);
  });
});
