import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "antd";
import i18n from "../../../i18n";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import UsersPage from ".";
import { useAuthStore } from "../../../stores/authStore";

vi.mock("../../../stores/authStore", async () => {
  const { create } = await import("zustand");
  return { useAuthStore: create(() => ({ user: { platform_role: "admin" } })) };
});

vi.mock("../../../api/modules/adminUsers", () => ({
  adminUsersApi: {
    list: vi.fn(),
    create: vi.fn(),
    setStatus: vi.fn(),
    setRole: vi.fn(),
    revokeSessions: vi.fn(),
    updateProfile: vi.fn(),
    resetPassword: vi.fn(),
    unlock: vi.fn(),
  },
}));

const users = [
  {
    id: "admin-id",
    username: "admin",
    platform_role: "admin" as const,
    status: "active" as const,
  },
  {
    id: "member-id",
    username: "member",
    platform_role: "member" as const,
    status: "active" as const,
  },
];

describe("UsersPage", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("en");
    useAuthStore.setState({ user: { platform_role: "admin" } as never });
    vi.clearAllMocks();
    vi.mocked(adminUsersApi.list).mockResolvedValue(users);
    vi.mocked(adminUsersApi.create).mockResolvedValue({
      id: "new-id",
      username: "new-member",
      platform_role: "member",
      status: "active",
    });
  });

  it("shows platform users and their roles", async () => {
    render(
      <App>
        <UsersPage />
      </App>,
    );

    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(screen.getByText("member")).toBeInTheDocument();
    expect(screen.getByText("User Management")).toBeInTheDocument();
  });

  it("creates a member from the visible user form", async () => {
    render(
      <App>
        <UsersPage />
      </App>,
    );
    await screen.findByText("admin");

    fireEvent.click(screen.getByRole("button", { name: /Create User/ }));
    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "new-member" },
    });
    fireEvent.change(screen.getByLabelText("Initial Password"), {
      target: { value: "member-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    await waitFor(() =>
      expect(adminUsersApi.create).toHaveBeenCalledWith({
        username: "new-member",
        password: "member-password",
        platform_role: "member",
      }),
    );
  });

  it("lets an administrator edit profile details and reset a password", async () => {
    render(
      <App>
        <UsersPage />
      </App>,
    );
    await screen.findByText("admin");

    expect(
      screen.getAllByRole("button", { name: "Edit Profile" }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole("button", { name: "Reset Password" }),
    ).toHaveLength(2);
  });

  it("lets an administrator unlock a temporarily locked user with Chinese confirmation", async () => {
    await i18n.changeLanguage("zh");
    vi.mocked(adminUsersApi.list).mockResolvedValueOnce([
      {
        ...users[1],
        login_locked: true,
        login_retry_after_seconds: 900,
        login_failed_attempts: 5,
      },
    ]);
    vi.mocked(adminUsersApi.unlock).mockResolvedValue({
      ...users[1],
      login_locked: false,
    });
    render(
      <App>
        <UsersPage />
      </App>,
    );
    await screen.findByText("member");
    expect(screen.getByText(/暂时锁定，剩余/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "解锁登录" }));
    expect((await screen.findAllByText("解除登录锁定"))[0]).toBeInTheDocument();
    const buttons = screen.getAllByRole("button", { name: "解锁登录" });
    const confirm = buttons[buttons.length - 1];
    fireEvent.click(confirm);
    await waitFor(() =>
      expect(adminUsersApi.unlock).toHaveBeenCalledWith("member-id"),
    );
    expect(
      await screen.findByText("登录锁定及失败次数已清除"),
    ).toBeInTheDocument();
  });

  it("does not expose user-management requests or unlock controls to a member", async () => {
    await i18n.changeLanguage("zh");
    useAuthStore.setState({ user: { platform_role: "member" } as never });
    render(
      <App>
        <UsersPage />
      </App>,
    );
    expect(screen.getByText("仅管理员可以管理用户")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "解锁登录" })).toBeNull();
    expect(adminUsersApi.list).not.toHaveBeenCalled();
    expect(adminUsersApi.unlock).not.toHaveBeenCalled();
  });

  it("keeps unlocking disabled for a disabled account", async () => {
    await i18n.changeLanguage("zh");
    vi.mocked(adminUsersApi.list).mockResolvedValueOnce([
      {
        ...users[1],
        status: "disabled",
        login_locked: true,
        login_retry_after_seconds: 900,
        login_failed_attempts: 5,
      },
    ]);
    render(
      <App>
        <UsersPage />
      </App>,
    );
    await screen.findByText("member");
    expect(screen.getByRole("button", { name: "解锁登录" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "解锁登录" }));
    expect(adminUsersApi.unlock).not.toHaveBeenCalled();
  });
});
