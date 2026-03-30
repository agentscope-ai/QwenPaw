import { Tooltip, Button } from "antd";
import { SunOutlined, MoonOutlined } from "@ant-design/icons";
import { useTheme } from "../../contexts/ThemeContext";
import { useTranslation } from "react-i18next";
import styles from "./index.module.less";

/**
 * ThemeToggleButton - toggles between light and dark theme.
 * Displays a sun icon in dark mode and a moon icon in light mode.
 */
export default function ThemeToggleButton() {
  const { isDark, toggleTheme } = useTheme();
  const { t } = useTranslation();

  return (
    <Tooltip title={t(isDark ? "theme.lightMode" : "theme.darkMode")}>
      <Button
        className={styles.toggleBtn}
        onClick={toggleTheme}
        aria-label={t(isDark ? "theme.switchToLight" : "theme.switchToDark")}
        type="text"
        icon={isDark ? <SunOutlined /> : <MoonOutlined />}
      />
    </Tooltip>
  );
}
