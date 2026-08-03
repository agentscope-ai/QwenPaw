import type { ReactNode } from "react";
import { ConfigProvider, theme as antdTheme } from "antd";
import zhCN from "antd/locale/zh_CN";
import { ThemeProvider, useTheme } from "@/app/theme";

function AntdProvider({ children }: { children: ReactNode }) {
  const { resolvedTheme } = useTheme();
  return (
    <ConfigProvider
      locale={zhCN}
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
