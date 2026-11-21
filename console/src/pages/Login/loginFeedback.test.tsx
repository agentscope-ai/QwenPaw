import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { create } from "zustand";
import { MemoryRouter, useLocation } from "react-router-dom";
import i18n from "../../i18n";
import { AuthResponseError } from "../../api/authErrors";

vi.mock("../../stores/authStore", () => ({
  useAuthStore: create(() => ({
    phase: "anonymous",
    hasUsers: true,
    login: vi.fn(),
    register: vi.fn(),
    bootstrap: vi.fn(),
  })),
}));
vi.mock("../../contexts/ThemeContext", () => ({
  useTheme: () => ({ isDark: false }),
}));
vi.mock("../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: { error: vi.fn(), success: vi.fn() } }),
}));
import LoginPage from "./index";
import { useAuthStore } from "../../stores/authStore";

beforeEach(async () => {
  await i18n.changeLanguage("zh");
  vi.clearAllMocks();
  vi.mocked(useAuthStore.getState().login).mockReset();
  useAuthStore.setState({ phase: "anonymous", hasUsers: true });
});

function show() {
  function CurrentLocation() {
    const location = useLocation();
    return <output aria-label="当前位置">{location.pathname}</output>;
  }
  render(
    <MemoryRouter>
      <LoginPage />
      <CurrentLocation />
    </MemoryRouter>,
  );
  fireEvent.change(screen.getByPlaceholderText("用户名"), {
    target: { value: "alice" },
  });
  fireEvent.change(screen.getByPlaceholderText("密码"), {
    target: { value: "wrong-password" },
  });
}

it("shows server remaining attempts and a Chinese lock countdown immediately on the fifth failure", async () => {
  const login = vi.mocked(useAuthStore.getState().login);
  for (let count = 4; count > 0; count--)
    login.mockRejectedValueOnce(
      new AuthResponseError("Invalid username or password", 401, {
        code: "invalid_credentials",
        remaining_attempts: count,
        retry_after_seconds: 0,
      }),
    );
  login.mockRejectedValueOnce(
    new AuthResponseError(
      "Account temporarily locked. Please try again later",
      423,
      { code: "account_locked", remaining_attempts: 0, retry_after_seconds: 2 },
    ),
  );
  show();
  for (let count = 4; count > 0; count--) {
    fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      `再失败 ${count} 次`,
    );
  }
  fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("登录暂时锁定"),
  );
  expect(screen.getByRole("button", { name: /登\s*录/ })).toBeDisabled();
  expect(screen.getByRole("alert")).not.toHaveTextContent(
    "Account temporarily locked",
  );
  expect(login).toHaveBeenCalledTimes(5);
  await waitFor(
    () =>
      expect(screen.getByRole("alert")).toHaveTextContent("锁定等待时间已结束"),
    { timeout: 4000 },
  );
  expect(screen.getByRole("button", { name: /登\s*录/ })).toBeEnabled();
});

it("does not carry one account's lock warning to a different username", async () => {
  vi.mocked(useAuthStore.getState().login).mockRejectedValueOnce(
    new AuthResponseError("locked", 423, {
      code: "account_locked",
      remaining_attempts: 0,
      retry_after_seconds: 900,
    }),
  );
  show();
  fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("15:00"),
  );
  await act(async () =>
    fireEvent.change(screen.getByPlaceholderText("用户名"), {
      target: { value: "bob" },
    }),
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.getByRole("button", { name: /登\s*录/ })).toBeEnabled();
});

it("lets an administrator-unlocked user retry while the server remains authoritative", async () => {
  const login = vi.mocked(useAuthStore.getState().login);
  const locked = () =>
    new AuthResponseError("账户已临时锁定", 423, {
      code: "account_locked",
      remaining_attempts: 0,
      retry_after_seconds: 900,
    });
  login
    .mockRejectedValueOnce(locked())
    .mockRejectedValueOnce(locked())
    .mockResolvedValueOnce(undefined);
  show();
  const submit = () => screen.getByRole("button", { name: /登\s*录/ });
  fireEvent.click(submit());
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("15:00"),
  );
  expect(submit()).toBeDisabled();
  // Clearing the local clock is an explicit retry; it neither logs in nor sends a request.
  fireEvent.click(
    screen.getByRole("button", { name: "管理员已解锁，重新尝试" }),
  );
  expect(screen.queryByRole("alert")).toBeNull();
  expect(submit()).toBeEnabled();
  expect(login).toHaveBeenCalledTimes(1);
  expect(screen.getByLabelText("当前位置")).not.toHaveTextContent("/chat");
  // If the server is still locked, it puts the user back into the countdown.
  fireEvent.click(submit());
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("15:00"),
  );
  expect(submit()).toBeDisabled();
  expect(login).toHaveBeenCalledTimes(2);
  // Once unlocked, a normal authenticated request can finish navigation immediately.
  fireEvent.click(
    screen.getByRole("button", { name: "管理员已解锁，重新尝试" }),
  );
  fireEvent.click(submit());
  await waitFor(() =>
    expect(screen.getByLabelText("当前位置")).toHaveTextContent("/chat"),
  );
  expect(login).toHaveBeenCalledTimes(3);
});

it("does not suggest administrator account unlock for an IP lock", async () => {
  vi.mocked(useAuthStore.getState().login).mockRejectedValueOnce(
    new AuthResponseError("当前网络登录尝试过于频繁", 423, {
      code: "ip_locked",
      retry_after_seconds: 900,
    }),
  );
  show();
  fireEvent.click(screen.getByRole("button", { name: /登\s*录/ }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("15:00"),
  );
  expect(
    screen.queryByRole("button", { name: "管理员已解锁，重新尝试" }),
  ).toBeNull();
});
