import { Tooltip, Button } from "antd";
import { SunOutlined, MoonOutlined } from "@ant-design/icons";
import { useTheme } from "../../contexts/ThemeContext";
import styles from "./index.module.less";

/**
 * ThemeToggleButton - toggles between light and dark theme.
 * Displays a sun icon in dark mode and a moon icon in light mode.
 */
export default function ThemeToggleButton() {
  const { isDark, toggleTheme } = useTheme();

  return (
    <Tooltip title={isDark ? "Light mode" : "Dark mode"}>
      <Button
        className={styles.toggleBtn}
        onClick={toggleTheme}
        aria-label={isDark ? "Switch to light mode" : "Switch to dark mode"}
        type="text"
        icon={isDark ? <SunOutlined /> : <MoonOutlined />}
      >
        {isDark ? "Light" : "Dark"}
      </Button>
    </Tooltip>
  );
}
