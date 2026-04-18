import { createContext, useContext, type ReactNode } from "react";
import type { SiteConfig } from "@/config";

const SiteConfigContext = createContext<SiteConfig | null>(null);

export function SiteConfigProvider({
  config,
  children,
}: {
  config: SiteConfig;
  children: ReactNode;
}) {
  return (
    <SiteConfigContext.Provider value={config}>
      {children}
    </SiteConfigContext.Provider>
  );
}

export function useSiteConfig(): SiteConfig {
  const ctx = useContext(SiteConfigContext);
  if (!ctx) {
    throw new Error("useSiteConfig must be used within <SiteConfigProvider>");
  }
  return ctx;
}
