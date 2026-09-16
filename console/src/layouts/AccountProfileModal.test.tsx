import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import { useAuthStore } from "../stores/authStore";
import AccountProfileModal from "./AccountProfileModal";

describe("AccountProfileModal", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("zh");
    useAuthStore.setState({
      user: {
        id: "user-1",
        username: "alice",
        display_name: "Alice Chen",
        email: "alice@example.com",
        phone: null,
        department: "研发部",
        job_title: "平台工程师",
        remark: null,
        platform_role: "member",
        status: "active",
      },
      updateProfile: vi.fn().mockResolvedValue(undefined),
      changePassword: vi.fn().mockResolvedValue(undefined),
    });
  });

  it("shows only the approved enterprise profile fields", () => {
    render(
      <AccountProfileModal
        open
        onClose={vi.fn()}
        onPasswordChanged={vi.fn()}
      />,
    );

    for (const label of [
      "用户名",
      "显示名",
      "邮箱",
      "手机号",
      "部门",
      "职位",
      "备注",
    ]) {
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    }
    expect(screen.queryByText("工号")).not.toBeInTheDocument();
    expect(screen.queryByText("头像")).not.toBeInTheDocument();
    expect(screen.queryByText("直属上级")).not.toBeInTheDocument();
    expect(screen.queryByText("办公地点")).not.toBeInTheDocument();
  });

  it("does not submit when password confirmation differs", async () => {
    const user = userEvent.setup();
    const onPasswordChanged = vi.fn();
    render(
      <AccountProfileModal
        open
        onClose={vi.fn()}
        onPasswordChanged={onPasswordChanged}
      />,
    );
    await user.click(screen.getByRole("tab", { name: "修改密码" }));
    await user.type(screen.getByLabelText("旧密码"), "old");
    await user.type(screen.getByLabelText("新密码"), "new-one");
    await user.type(screen.getByLabelText("确认新密码"), "new-two");
    await user.click(screen.getByRole("button", { name: "修改密码" }));

    await waitFor(() =>
      expect(screen.getByText("两次输入的密码不一致")).toBeInTheDocument(),
    );
    expect(useAuthStore.getState().changePassword).not.toHaveBeenCalled();
    expect(onPasswordChanged).not.toHaveBeenCalled();
  });
});
