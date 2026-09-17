import type { ReactNode } from "react";
import { ConfigProvider, theme as antdTheme } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { ThemeProvider, useTheme } from "@/app/theme";
import { useLocaleStore } from "@/store/localeStore";

function AntdProvider({ children }: { children: ReactNode }) {
  const { resolvedTheme } = useTheme();
  const language = useLocaleStore((state) => state.language);
  const antdLocale = language === "en" ? enUS : zhCN;
  return (
    <ConfigProvider
      locale={antdLocale}
      theme={{
        token: {
          colorPrimary: "#FF7F16",
          colorLink: "#FF7F16",
          colorInfo: "#FF7F16",
          borderRadius: 8,
        },
        algorithm:
          resolvedTheme === "dark"
            ? antdTheme.darkAlgorithm
            : antdTheme.defaultAlgorithm,
        cssVar: { key: "antd" },
      }}
    >
      {children}
    </ConfigProvider>
  );
}

export function AppProviders({ children }: { children: ReactNode }) {
  return (
    <ThemeProvider defaultTheme="system">
      <AntdProvider>{children}</AntdProvider>
    </ThemeProvider>
  );
}
