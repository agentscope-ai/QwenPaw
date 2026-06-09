import { Dropdown, Button, type MenuProps } from "antd";
import { SparkMoonLine, SparkSunLine } from "@agentscope-ai/icons";
import { useTheme, type ThemeMode } from "../../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import type { ReactNode } from "react";
import styles from "./index.module.less";

/** Sun & Moon combined icon representing "follow system" theme. */
function SunMoonIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      data-icon="SunMoonLine"
    >
      {/* Sun circle */}
      <circle cx="12" cy="12" r="4" />
      {/* Sun rays */}
      <path d="M12 2v2" />
      <path d="M12 20v2" />
      <path d="m4.93 4.93 1.41 1.41" />
      <path d="m17.66 17.66 1.41 1.41" />
      <path d="M2 12h2" />
      <path d="M20 12h2" />
      <path d="m6.34 17.66-1.41 1.41" />
      <path d="m19.07 4.93-1.41 1.41" />
      {/* Moon crescent overlay */}
      <path d="M17.7 13.7A7 7 0 0 1 10.3 6.3" />
    </svg>
  );
}

const ICONS: Record<ThemeMode, ReactNode> = {
  light: <SparkSunLine />,
  dark: <SparkMoonLine />,
  system: <SunMoonIcon />,
};

export default function ThemeToggleButton() {
  const { themeMode, isDark, setThemeMode } = useTheme();
  const { t } = useTranslation();

  const items: MenuProps["items"] = [
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
  ];

  const icon =
    themeMode === "system" ? ICONS.system : ICONS[isDark ? "dark" : "light"];

  return (
    <Dropdown
      menu={{ items, selectedKeys: [themeMode] }}
      placement="bottomRight"
      overlayClassName={styles.themeDropdown}
    >
      <Button className={styles.toggleBtn} type="text" icon={icon} />
    </Dropdown>
  );
}
