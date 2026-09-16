import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { adminUsersApi } from "./adminUsers";

vi.mock("@/api/request", () => ({ request: vi.fn() }));
import { request } from "@/api/request";

describe("adminUsersApi", () => {
  beforeEach(() => vi.mocked(request).mockResolvedValue(undefined));
  afterEach(() => vi.clearAllMocks());

  it("uses the administrator user-governance endpoints", async () => {
    await adminUsersApi.list();
    await adminUsersApi.create({
      username: "member",
      password: "password",
      platform_role: "member",
    });
    await adminUsersApi.setStatus("user/id", "disabled");
    await adminUsersApi.setRole("user/id", "admin");
    await adminUsersApi.revokeSessions("user/id");
    await adminUsersApi.updateProfile("user/id", { username: "renamed" });
    await adminUsersApi.resetPassword("user/id", "new-password");

    expect(request).toHaveBeenNthCalledWith(1, "/admin/users");
    expect(request).toHaveBeenNthCalledWith(
      2,
      "/admin/users",
      expect.objectContaining({ method: "POST" }),
    );
    expect(request).toHaveBeenNthCalledWith(
      3,
      "/admin/users/user%2Fid/status",
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(request).toHaveBeenNthCalledWith(
      4,
      "/admin/users/user%2Fid/role",
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(request).toHaveBeenNthCalledWith(
      5,
      "/admin/users/user%2Fid/revoke-sessions",
      expect.objectContaining({ method: "POST" }),
    );
    expect(request).toHaveBeenNthCalledWith(
      6,
      "/admin/users/user%2Fid/profile",
      expect.objectContaining({ method: "PATCH" }),
    );
    expect(request).toHaveBeenNthCalledWith(
      7,
      "/admin/users/user%2Fid/reset-password",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
