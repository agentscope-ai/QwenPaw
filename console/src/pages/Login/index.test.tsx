import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { authApi } from "../../api/modules/auth";
import LoginPage from ".";

const navigate = vi.fn();
const changeLanguage = vi.fn();

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: {
      language: "en",
      resolvedLanguage: "en",
      changeLanguage,
    },
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => navigate,
  useSearchParams: () => [new URLSearchParams()],
}));

vi.mock("../../api/modules/auth", () => ({
  authApi: {
    getStatus: vi.fn(),
    login: vi.fn(),
    register: vi.fn(),
  },
}));

vi.mock("../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));

vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({
    message: {
      error: vi.fn(),
      info: vi.fn(),
      success: vi.fn(),
    },
  }),
}));

describe("LoginPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("resumes login after accepting terms in Hub mode", async () => {
    vi.mocked(authApi.getStatus).mockResolvedValue({
      enabled: true,
      has_users: true,
      mode: "hub",
    });
    vi.mocked(authApi.login).mockResolvedValue({
      token: "hub-token",
      username: "ray",
    });

    render(<LoginPage />);

    expect(
      await screen.findByText("login.hubDisclaimerTitle"),
    ).toBeInTheDocument();
    expect(screen.getByText("login.hubDisclaimerPoint1")).toBeInTheDocument();
    expect(screen.getByText("login.hubDisclaimerPoint2")).toBeInTheDocument();
    expect(screen.getByText("login.hubDisclaimerPoint3")).toBeInTheDocument();
    const languageSwitcher = screen.getByRole("button", {
      name: "login.switchLanguage",
    });
    expect(languageSwitcher).toHaveTextContent("简体中文");
    fireEvent.click(languageSwitcher);
    expect(changeLanguage).toHaveBeenCalledWith("zh");
    expect(localStorage.getItem("language")).toBe("zh");
    const disclaimer = screen.getByText("login.hubDisclaimerTitle")
      .parentElement?.parentElement;
    expect(disclaimer?.querySelector("a")).toBeNull();
    expect(
      screen.getByRole("navigation", { name: "login.hubLinks" }),
    ).toContainElement(screen.getByRole("link", { name: /GitHub/ }));
    const submit = screen.getByRole("button", { name: "login.submit" });
    expect(submit).toBeEnabled();

    fireEvent.change(screen.getByPlaceholderText("login.usernamePlaceholder"), {
      target: { value: "ray" },
    });
    fireEvent.change(screen.getByPlaceholderText("login.passwordPlaceholder"), {
      target: { value: "password" },
    });
    fireEvent.click(submit);

    expect(authApi.login).not.toHaveBeenCalled();
    const agree = await screen.findByRole("button", {
      name: "login.hubTermsAgree",
    });
    expect(agree).toBeDisabled();
    const terms = screen.getByText("login.hubTermsLead").parentElement;
    expect(terms).not.toBeNull();
    Object.defineProperties(terms, {
      scrollHeight: { configurable: true, value: 1000 },
      clientHeight: { configurable: true, value: 400 },
      scrollTop: { configurable: true, value: 600 },
    });
    fireEvent.scroll(terms!);

    expect(agree).toBeEnabled();
    fireEvent.click(agree);

    await waitFor(() =>
      expect(authApi.login).toHaveBeenCalledWith("ray", "password"),
    );
    expect(
      screen.getByRole("checkbox", {
        name: "login.hubDisclaimerAccept",
      }),
    ).toBeChecked();
    expect(screen.getByRole("link", { name: /GitHub/ })).toHaveAttribute(
      "href",
      "https://github.com/agentscope-ai/QwenPaw",
    );
  });

  it("does not change the standard app login", async () => {
    vi.mocked(authApi.getStatus).mockResolvedValue({
      enabled: true,
      has_users: true,
    });

    render(<LoginPage />);

    await waitFor(() => expect(authApi.getStatus).toHaveBeenCalledOnce());
    expect(
      screen.queryByText("login.hubDisclaimerTitle"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "login.switchLanguage" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "login.submit" })).toBeEnabled();
  });
});
