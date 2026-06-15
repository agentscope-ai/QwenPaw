import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ConfigProvider, bailianTheme } from "@agentscope-ai/design";
import { theme as antdTheme } from "antd";
import { useTheme } from "@/contexts/ThemeContext";
import { DATA_CONNECTION_THEME_TOKENS } from "./theme";
import themeStyles from "./theme.module.less";

function readHtmlDarkMode(): boolean {
  return document.documentElement.classList.contains("dark-mode");
}

/** Resolves dark mode from ThemeContext and host `html.dark-mode` (plugin embed). */
function useDataConnectionDarkMode(): boolean {
  const { isDark: fromContext } = useTheme();
  const [htmlDark, setHtmlDark] = useState(readHtmlDarkMode);

  useEffect(() => {
    const sync = () => setHtmlDark(readHtmlDarkMode());
    const observer = new MutationObserver(sync);
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["class"],
    });
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    mq?.addEventListener("change", sync);
    window.addEventListener("storage", sync);
    return () => {
      observer.disconnect();
      mq?.removeEventListener("change", sync);
      window.removeEventListener("storage", sync);
    };
  }, []);

  return fromContext || htmlDark;
}

export function DataConnectionThemeProvider({
  children,
}: {
  children: ReactNode;
}) {
  const isDark = useDataConnectionDarkMode();
  const tokens = isDark
    ? DATA_CONNECTION_THEME_TOKENS.dark
    : DATA_CONNECTION_THEME_TOKENS.light;

  const themeConfig = useMemo(
    () => ({
      ...(bailianTheme as { theme?: Record<string, unknown> })?.theme,
      algorithm: isDark
        ? antdTheme.darkAlgorithm
        : antdTheme.defaultAlgorithm,
      token: tokens,
    }),
    [isDark, tokens],
  );

  return (
    <ConfigProvider prefix="qwenpaw" prefixCls="qwenpaw" theme={themeConfig}>
      <div
        className={themeStyles.themeRoot}
        data-datapaw-data-connection-theme={isDark ? "dark" : "light"}
      >
        {children}
      </div>
    </ConfigProvider>
  );
}
