import { InfoCircleOutlined } from "@ant-design/icons";
import { Button } from "@agentscope-ai/design";
import { Dropdown, Layout, Space, message } from "antd";
import type { MenuProps } from "antd";
import { useRef } from "react";
import { useTranslation } from "react-i18next";
import { invoke } from "@tauri-apps/api/core";

import LanguageSwitcher, {
  LANGUAGE_LIST,
} from "../components/LanguageSwitcher/index";
import ThemeToggleButton from "../components/ThemeToggleButton";
import { PRODUCT_NAME } from "../config/brand";
import { useTheme } from "../contexts/ThemeContext";
import { Slot } from "../plugins/registry/Slot";
import { isDesktopApp } from "../tauri/backendRuntime";
import styles from "./index.module.less";

const { Header: AntHeader } = Layout;

export default function Header() {
  const { t, i18n } = useTranslation();
  const { setThemeMode } = useTheme();
  const logoClicksRef = useRef<number[]>([]);

  const handleLogoClick = () => {
    if (!isDesktopApp()) return;
    const now = Date.now();
    logoClicksRef.current = logoClicksRef.current.filter(
      (time) => time > now - 3000,
    );
    logoClicksRef.current.push(now);
    if (logoClicksRef.current.length < 8) return;

    logoClicksRef.current = [];
    invoke("open_devtools")
      .then(() => message.success("DevTools opened"))
      .catch((err: unknown) => {
        const detail = err instanceof Error ? err.message : String(err);
        console.error("Failed to open DevTools:", detail);
        message.error(`DevTools error: ${detail}`);
      });
  };

  const mobileMenuItems: MenuProps["items"] = [
    {
      key: "language",
      label: t("sidebar.settings.language"),
      children: LANGUAGE_LIST.map(({ key, label }) => ({
        key,
        label,
        onClick: () => {
          void i18n.changeLanguage(key);
          localStorage.setItem("language", key);
        },
      })),
    },
    {
      key: "theme",
      label: t("sidebar.settings.theme"),
      children: [
        {
          key: "light",
          label: t("theme.light"),
          onClick: () => setThemeMode("light"),
        },
        {
          key: "dark",
          label: t("theme.dark"),
          onClick: () => setThemeMode("dark"),
        },
        {
          key: "system",
          label: t("theme.system"),
          onClick: () => setThemeMode("system"),
        },
      ],
    },
  ];

  return (
    <AntHeader className={styles.header}>
      <div className={styles.logoWrapper} onClick={handleLogoClick}>
        <Slot name="header.logo" kind="replace">
          <span className={styles.brandName}>{PRODUCT_NAME}</span>
        </Slot>
      </div>
      <Slot name="header.left" kind="fill" />
      <Space size="middle">
        <Slot name="header.right" kind="fill" />
        <span className={styles.hideOnMobile}>
          <LanguageSwitcher />
        </span>
        <span className={styles.hideOnMobile}>
          <ThemeToggleButton />
        </span>
        <Dropdown menu={{ items: mobileMenuItems }} placement="bottomRight">
          <Button
            type="text"
            icon={<InfoCircleOutlined />}
            className={styles.showOnMobile}
            title={t("sidebar.settings.title")}
          />
        </Dropdown>
      </Space>
    </AntHeader>
  );
}
