import { expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import GovernancePanel from "./GovernancePanel";
vi.mock("@/stores/authStore", () => ({
  useAuthStore: () => ({
    mode: "multi_user",
    user: { platform_role: "admin" },
  }),
}));
vi.mock("@/api/modules/adminUsers", () => ({
  adminUsersApi: { list: async () => [] },
}));
vi.mock("@/api/request", () => ({
  request: vi.fn(async (path: string) => {
    if (path.endsWith("status")) return { enforced: false, version: 0 };
    return [];
  }),
}));
it("previews before explicit import and never implicitly enables governance", async () => {
  render(<GovernancePanel />);
  await screen.findByText(/尚未启用/);
  fireEvent.click(screen.getByRole("button", { name: "初始化预览" }));
  await screen.findByText("登记元数据");
  await waitFor(() =>
    expect(screen.getByText("登记元数据").closest("button")).not.toHaveClass(
      "ant-btn-loading",
    ),
  );
  fireEvent.click(screen.getByText("登记元数据"));
  const { request } = await import("@/api/request");
  await waitFor(() =>
    expect(request).toHaveBeenCalledWith("/model-governance/import", {
      method: "POST",
    }),
  );
  expect(
    vi
      .mocked(request)
      .mock.calls.some(([path]) => path === "/model-governance/enforcement"),
  ).toBe(false);
});
