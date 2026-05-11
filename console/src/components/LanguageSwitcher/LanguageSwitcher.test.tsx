import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "@/test/common_setup";
import LanguageSwitcher from "./index";

// vi.hoisted ensures variables are initialized before vi.mock hoisting
const { mockChangeLanguage, mockUpdateLanguage } = vi.hoisted(() => ({
  mockChangeLanguage: vi.fn(),
  mockUpdateLanguage: vi.fn().mockResolvedValue(undefined),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    i18n: {
      language: "en",
      resolvedLanguage: "en",
      changeLanguage: mockChangeLanguage,
    },
    t: (k: string) => k,
  }),
}));

vi.mock("@/api/modules/language", () => ({
  languageApi: { updateLanguage: mockUpdateLanguage },
}));

vi.mock("@agentscope-ai/design", () => ({
  Dropdown: ({
    children,
    menu,
  }: {
    children: React.ReactNode;
    menu: { items: Array<{ key: string; label: string; onClick: () => void }> };
  }) => (
    <div>
      {children}
      <ul role="menu">
        {menu.items?.map((item) => (
          <li key={item.key} role="menuitem" onClick={item.onClick}>
            {item.label}
          </li>
        ))}
      </ul>
    </div>
  ),
}));

describe("LanguageSwitcher", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.clearAllMocks());

  it("renders the language switcher button", () => {
    renderWithProviders(<LanguageSwitcher />);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("shows 4 language options", () => {
    renderWithProviders(<LanguageSwitcher />);
    expect(screen.getByText("English")).toBeInTheDocument();
    expect(screen.getByText("简体中文")).toBeInTheDocument();
    expect(screen.getByText("日本語")).toBeInTheDocument();
    expect(screen.getByText("Русский")).toBeInTheDocument();
  });

  it("calls i18n.changeLanguage when a language option is clicked", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LanguageSwitcher />);
    await user.click(screen.getByText("简体中文"));
    expect(mockChangeLanguage).toHaveBeenCalledWith("zh");
  });

  it("writes selected language to localStorage", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LanguageSwitcher />);
    await user.click(screen.getByText("日本語"));
    expect(localStorage.getItem("language")).toBe("ja");
  });

  it("calls languageApi.updateLanguage after switching language", async () => {
    const user = userEvent.setup();
    renderWithProviders(<LanguageSwitcher />);
    await user.click(screen.getByText("English"));
    expect(mockUpdateLanguage).toHaveBeenCalledWith("en");
  });
});
