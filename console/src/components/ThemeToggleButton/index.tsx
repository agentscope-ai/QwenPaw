import { Dropdown, Button, type MenuProps } from "antd";
import {
  SparkMoonLine,
  SparkSunLine,
  SparkComputerLine,
} from "@agentscope-ai/icons";
import { useTheme, type ThemeMode } from "../../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

const ICONS: Record<ThemeMode, React.ReactNode> = {
  light: <SparkSunLine />,
  dark: <SparkMoonLine />,
  system: <SparkComputerLine />,
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
