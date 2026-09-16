import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "../i18n";
import SidebarAccountSummary from "./SidebarAccountSummary";

describe("SidebarAccountSummary", () => {
  beforeEach(async () => {
    await i18n.changeLanguage("zh");
  });

  it("shows current username and platform role", () => {
    render(
      <SidebarAccountSummary
        username="admin"
        displayName="管理员张三"
        role="admin"
        collapsed={false}
        onOpen={vi.fn()}
        onLogout={vi.fn()}
      />,
    );
    expect(screen.getByText("管理员张三")).toBeInTheDocument();
    expect(screen.getByText("管理员")).toBeInTheDocument();
  });

  it("reveals account details and logout from the account popover", async () => {
    const onOpen = vi.fn();
    const onLogout = vi.fn();
    render(
      <SidebarAccountSummary
        username="member"
        role="member"
        collapsed={false}
        onOpen={onOpen}
        onLogout={onLogout}
      />,
    );
    fireEvent.mouseEnter(
      screen.getByRole("button", { name: "member 普通用户" }),
    );
    const profileAction = await screen.findByText("用户信息");
    expect(
      document.querySelector(".ant-popover-placement-topLeft"),
    ).toBeInTheDocument();
    fireEvent.click(profileAction);
    fireEvent.click(await screen.findByText("退出登录"));
    expect(onOpen).toHaveBeenCalledOnce();
    expect(onLogout).toHaveBeenCalledOnce();
  });

  it("translates the role and logout action with the user language", async () => {
    await i18n.changeLanguage("en");
    render(
      <SidebarAccountSummary
        username="member"
        role="member"
        collapsed={false}
        onOpen={vi.fn()}
        onLogout={vi.fn()}
      />,
    );

    expect(screen.getByText("Member")).toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByRole("button", { name: "member Member" }));
    expect(await screen.findByText("Logout")).toBeInTheDocument();
  });
});
