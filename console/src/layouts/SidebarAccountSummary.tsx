import { Button, Popover, Tag } from "antd";
import { LogoutOutlined, UserOutlined } from "@ant-design/icons";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

interface SidebarAccountSummaryProps {
  username: string;
  displayName?: string | null;
  role: "admin" | "member";
  collapsed: boolean;
  onOpen: () => void;
  onLogout: () => void;
}

export default function SidebarAccountSummary({
  username,
  displayName,
  role,
  collapsed,
  onOpen,
  onLogout,
}: SidebarAccountSummaryProps) {
  const { t } = useTranslation();
  const roleLabel =
    role === "admin"
      ? t("account.roleAdmin", "管理员")
      : t("account.roleMember", "普通用户");
  const logoutLabel = t("login.logout", "退出登录");
  const profileLabel = t("account.information", "用户信息");
  const accountName = displayName?.trim() || username;
  const accountButton = (
    <Button
      type="text"
      icon={<UserOutlined />}
      block
      aria-label={`${accountName} ${roleLabel}`}
      className={`${styles.authBtn} ${
        collapsed ? styles.authBtnCollapsed : ""
      }`}
    >
      {!collapsed && (
        <span>
          <span>{accountName}</span>
          <Tag color={role === "admin" ? "orange" : "blue"}>{roleLabel}</Tag>
        </span>
      )}
    </Button>
  );

  const actions = (
    <div className={styles.accountPopoverActions}>
      <div className={styles.accountPopoverHeader}>
        <strong>{accountName}</strong>
        <span>@{username}</span>
      </div>
      <Button type="text" icon={<UserOutlined />} onClick={onOpen} block>
        {profileLabel}
      </Button>
      <Button
        type="text"
        danger
        icon={<LogoutOutlined />}
        onClick={onLogout}
        block
      >
        {logoutLabel}
      </Button>
    </div>
  );

  return (
    <div className={styles.authActions}>
      <Popover
        content={actions}
        placement="topLeft"
        trigger={["hover", "click"]}
      >
        {accountButton}
      </Popover>
    </div>
  );
}
