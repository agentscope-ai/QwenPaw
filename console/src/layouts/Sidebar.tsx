import {
  Layout,
  Menu,
  Button,
  Modal,
  Input,
  Form,
  message,
  Tooltip,
  type MenuProps,
} from "antd";
import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import AgentSelector from "../components/AgentSelector";
import {
  MessageCircle,
  Wifi,
  UsersRound,
  CalendarClock,
  Activity,
  Sparkles,
  Briefcase,
  Box,
  Globe,
  Settings,
  Shield,
  Plug,
  Wrench,
  BarChart3,
  Mic,
  Bot,
  LogOut,
  UserCog,
  PanelLeftOpen,
  PanelLeftClose,
} from "lucide-react";
import { clearAuthToken } from "../api/config";
import { authApi } from "../api/modules/auth";
import styles from "./index.module.less";
import { useTheme } from "../contexts/ThemeContext";
import { KEY_TO_PATH, DEFAULT_OPEN_KEYS } from "./constants";

// ── Layout ────────────────────────────────────────────────────────────────

const { Sider } = Layout;

// ── Types ─────────────────────────────────────────────────────────────────

interface SidebarProps {
  selectedKey: string;
}

// ── Sidebar ───────────────────────────────────────────────────────────────

export default function Sidebar({ selectedKey }: SidebarProps) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { isDark } = useTheme();
  const [authEnabled, setAuthEnabled] = useState(false);
  const [accountModalOpen, setAccountModalOpen] = useState(false);
  const [accountLoading, setAccountLoading] = useState(false);
  const [accountForm] = Form.useForm();
  const [collapsed, setCollapsed] = useState(false);

  // ── Effects ──────────────────────────────────────────────────────────────

  useEffect(() => {
    authApi
      .getStatus()
      .then((res) => setAuthEnabled(res.enabled))
      .catch(() => {});
  }, []);

  // ── Handlers ──────────────────────────────────────────────────────────────

  const handleUpdateProfile = async (values: {
    currentPassword: string;
    newUsername?: string;
    newPassword?: string;
  }) => {
    const trimmedUsername = values.newUsername?.trim() || undefined;
    const trimmedPassword = values.newPassword?.trim() || undefined;

    if (values.newPassword && !trimmedPassword) {
      message.error(t("account.passwordEmpty"));
      return;
    }

    if (values.newUsername && !trimmedUsername) {
      message.error(t("account.usernameEmpty"));
      return;
    }

    if (!trimmedUsername && !trimmedPassword) {
      message.warning(t("account.nothingToUpdate"));
      return;
    }

    setAccountLoading(true);
    try {
      await authApi.updateProfile(
        values.currentPassword,
        trimmedUsername,
        trimmedPassword,
      );
      message.success(t("account.updateSuccess"));
      setAccountModalOpen(false);
      accountForm.resetFields();
      clearAuthToken();
      window.location.href = "/login";
    } catch (err: unknown) {
      const raw = err instanceof Error ? err.message : "";
      let msg = t("account.updateFailed");
      if (raw.includes("password is incorrect")) {
        msg = t("account.wrongPassword");
      } else if (raw.includes("Nothing to update")) {
        msg = t("account.nothingToUpdate");
      } else if (raw.includes("cannot be empty")) {
        msg = t("account.nothingToUpdate");
      } else if (raw) {
        msg = raw;
      }
      message.error(msg);
    } finally {
      setAccountLoading(false);
    }
  };

  // ── Collapsed nav items (all leaf pages) ──────────────────────────────

  const collapsedNavItems = [
    {
      key: "chat",
      icon: <MessageCircle size={18} />,
      path: "/chat",
      label: t("nav.chat"),
    },
    {
      key: "channels",
      icon: <Wifi size={18} />,
      path: "/channels",
      label: t("nav.channels"),
    },
    {
      key: "sessions",
      icon: <UsersRound size={18} />,
      path: "/sessions",
      label: t("nav.sessions"),
    },
    {
      key: "cron-jobs",
      icon: <CalendarClock size={18} />,
      path: "/cron-jobs",
      label: t("nav.cronJobs"),
    },
    {
      key: "heartbeat",
      icon: <Activity size={18} />,
      path: "/heartbeat",
      label: t("nav.heartbeat"),
    },
    {
      key: "workspace",
      icon: <Briefcase size={18} />,
      path: "/workspace",
      label: t("nav.workspace"),
    },
    {
      key: "skills",
      icon: <Sparkles size={18} />,
      path: "/skills",
      label: t("nav.skills"),
    },
    {
      key: "skill-pool",
      icon: <Sparkles size={18} />,
      path: "/skill-pool",
      label: t("nav.skillPool", "Skill Pool"),
    },
    {
      key: "tools",
      icon: <Wrench size={18} />,
      path: "/tools",
      label: t("nav.tools"),
    },
    { key: "mcp", icon: <Plug size={18} />, path: "/mcp", label: t("nav.mcp") },
    {
      key: "agent-config",
      icon: <Settings size={18} />,
      path: "/agent-config",
      label: t("nav.agentConfig"),
    },
    {
      key: "agents",
      icon: <Bot size={18} />,
      path: "/agents",
      label: t("nav.agents"),
    },
    {
      key: "models",
      icon: <Box size={18} />,
      path: "/models",
      label: t("nav.models"),
    },
    {
      key: "environments",
      icon: <Globe size={18} />,
      path: "/environments",
      label: t("nav.environments"),
    },
    {
      key: "security",
      icon: <Shield size={18} />,
      path: "/security",
      label: t("nav.security"),
    },
    {
      key: "token-usage",
      icon: <BarChart3 size={18} />,
      path: "/token-usage",
      label: t("nav.tokenUsage"),
    },
    {
      key: "voice-transcription",
      icon: <Mic size={18} />,
      path: "/voice-transcription",
      label: t("nav.voiceTranscription"),
    },
  ];

  // ── Menu items ────────────────────────────────────────────────────────────

  const menuItems: MenuProps["items"] = [
    {
      key: "chat",
      label: collapsed ? null : t("nav.chat"),
      icon: <MessageCircle size={16} />,
    },
    {
      key: "control-group",
      label: collapsed ? null : t("nav.control"),
      children: [
        {
          key: "channels",
          label: collapsed ? null : t("nav.channels"),
          icon: <Wifi size={16} />,
        },
        {
          key: "sessions",
          label: collapsed ? null : t("nav.sessions"),
          icon: <UsersRound size={16} />,
        },
        {
          key: "cron-jobs",
          label: collapsed ? null : t("nav.cronJobs"),
          icon: <CalendarClock size={16} />,
        },
        {
          key: "heartbeat",
          label: collapsed ? null : t("nav.heartbeat"),
          icon: <Activity size={16} />,
        },
      ],
    },
    {
      key: "agent-group",
      label: collapsed ? null : t("nav.agent"),
      children: [
        {
          key: "workspace",
          label: collapsed ? null : t("nav.workspace"),
          icon: <Briefcase size={16} />,
        },
        {
          key: "skills",
          label: collapsed ? null : t("nav.skills"),
          icon: <Sparkles size={16} />,
        },
        {
          key: "tools",
          label: collapsed ? null : t("nav.tools"),
          icon: <Wrench size={16} />,
        },
        {
          key: "mcp",
          label: collapsed ? null : t("nav.mcp"),
          icon: <Plug size={16} />,
        },
        {
          key: "agent-config",
          label: collapsed ? null : t("nav.agentConfig"),
          icon: <Settings size={16} />,
        },
      ],
    },
    {
      key: "settings-group",
      label: collapsed ? null : t("nav.settings"),
      children: [
        {
          key: "agents",
          label: collapsed ? null : t("nav.agents"),
          icon: <Bot size={16} />,
        },
        {
          key: "models",
          label: collapsed ? null : t("nav.models"),
          icon: <Box size={16} />,
        },
        {
          key: "skill-pool",
          label: collapsed ? null : t("nav.skillPool", "Skill Pool"),
          icon: <Sparkles size={16} />,
        },
        {
          key: "environments",
          label: collapsed ? null : t("nav.environments"),
          icon: <Globe size={16} />,
        },
        {
          key: "security",
          label: collapsed ? null : t("nav.security"),
          icon: <Shield size={16} />,
        },
        {
          key: "token-usage",
          label: collapsed ? null : t("nav.tokenUsage"),
          icon: <BarChart3 size={16} />,
        },
        {
          key: "voice-transcription",
          label: collapsed ? null : t("nav.voiceTranscription"),
          icon: <Mic size={16} />,
        },
      ],
    },
  ];

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <Sider
      width={collapsed ? 72 : 275}
      className={`${styles.sider}${
        collapsed ? ` ${styles.siderCollapsed}` : ""
      }${isDark ? ` ${styles.siderDark}` : ""}`}
    >
      <div className={styles.agentSelectorContainer}>
        <AgentSelector collapsed={collapsed} />
      </div>

      {collapsed ? (
        <nav className={styles.collapsedNav}>
          {collapsedNavItems.map((item) => {
            const isActive = selectedKey === item.key;
            return (
              <Tooltip
                key={item.key}
                title={item.label}
                placement="right"
                overlayInnerStyle={{
                  background: "rgba(0,0,0,0.75)",
                  color: "#fff",
                }}
              >
                <button
                  className={`${styles.collapsedNavItem} ${
                    isActive ? styles.collapsedNavItemActive : ""
                  }`}
                  onClick={() => navigate(item.path)}
                >
                  {item.icon}
                </button>
              </Tooltip>
            );
          })}
        </nav>
      ) : (
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          openKeys={DEFAULT_OPEN_KEYS}
          onClick={({ key }) => {
            const path = KEY_TO_PATH[String(key)];
            if (path) navigate(path);
          }}
          items={menuItems}
          theme={isDark ? "dark" : "light"}
          className={styles.sideMenu}
        />
      )}

      {authEnabled && !collapsed && (
        <div className={styles.authActions}>
          <Button
            type="text"
            icon={<UserCog size={16} />}
            onClick={() => {
              accountForm.resetFields();
              setAccountModalOpen(true);
            }}
            block
            className={`${styles.authBtn} ${
              collapsed ? styles.authBtnCollapsed : ""
            }`}
          >
            {!collapsed && t("account.title")}
          </Button>
          <Button
            type="text"
            icon={<LogOut size={16} />}
            onClick={() => {
              clearAuthToken();
              window.location.href = "/login";
            }}
            block
            className={`${styles.authBtn} ${
              collapsed ? styles.authBtnCollapsed : ""
            }`}
          >
            {!collapsed && t("login.logout")}
          </Button>
        </div>
      )}

      <div className={styles.collapseToggleContainer}>
        <Button
          type="text"
          icon={
            collapsed ? (
              <PanelLeftOpen size={20} />
            ) : (
              <PanelLeftClose size={20} />
            )
          }
          onClick={() => setCollapsed(!collapsed)}
          className={styles.collapseToggle}
        />
      </div>

      <Modal
        open={accountModalOpen}
        onCancel={() => setAccountModalOpen(false)}
        title={t("account.title")}
        footer={null}
        destroyOnHidden
        centered
      >
        <Form
          form={accountForm}
          layout="vertical"
          onFinish={handleUpdateProfile}
        >
          <Form.Item
            name="currentPassword"
            label={t("account.currentPassword")}
            rules={[
              { required: true, message: t("account.currentPasswordRequired") },
            ]}
          >
            <Input.Password />
          </Form.Item>
          <Form.Item name="newUsername" label={t("account.newUsername")}>
            <Input placeholder={t("account.newUsernamePlaceholder")} />
          </Form.Item>
          <Form.Item name="newPassword" label={t("account.newPassword")}>
            <Input.Password placeholder={t("account.newPasswordPlaceholder")} />
          </Form.Item>
          <Form.Item
            name="confirmPassword"
            label={t("account.confirmPassword")}
            dependencies={["newPassword"]}
            rules={[
              ({ getFieldValue }) => ({
                validator(_, value) {
                  if (!value && !getFieldValue("newPassword")) {
                    return Promise.resolve();
                  }
                  if (value === getFieldValue("newPassword")) {
                    return Promise.resolve();
                  }
                  return Promise.reject(
                    new Error(t("account.passwordMismatch")),
                  );
                },
              }),
            ]}
          >
            <Input.Password
              placeholder={t("account.confirmPasswordPlaceholder")}
            />
          </Form.Item>
          <Form.Item>
            <Button
              type="primary"
              htmlType="submit"
              loading={accountLoading}
              block
            >
              {t("account.save")}
            </Button>
          </Form.Item>
        </Form>
      </Modal>
    </Sider>
  );
}
