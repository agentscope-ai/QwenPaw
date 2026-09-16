import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "antd";
import i18n from "../../../i18n";
import { adminUsersApi } from "../../../api/modules/adminUsers";
import UsersPage from ".";

vi.mock("../../../api/modules/adminUsers", () => ({
  adminUsersApi: {
    list: vi.fn(),
    create: vi.fn(),
    setStatus: vi.fn(),
    setRole: vi.fn(),
    revokeSessions: vi.fn(),
    updateProfile: vi.fn(),
    resetPassword: vi.fn(),
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
});
