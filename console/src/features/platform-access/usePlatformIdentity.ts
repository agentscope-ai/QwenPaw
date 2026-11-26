import { useEffect } from "react";
import { usePlatformAccess } from "./store";
import { isPlatformWebApp } from "../platform-web/client";

export function usePlatformIdentity({
  hubMode,
  localAccount,
}: {
  hubMode: boolean;
  localAccount: string;
}) {
  const refresh = usePlatformAccess((state) => state.refresh);
  useEffect(() => {
    if (isPlatformWebApp) return;
    usePlatformAccess.setState({ localAccount: hubMode ? localAccount : null });
    void refresh().catch(() => {});
    const reload = () => {
      usePlatformAccess.setState({ connection: null, panel: null });
      void refresh().catch(() => {});
    };
    window.addEventListener("qwenpaw:auth-changed", reload);
    return () => window.removeEventListener("qwenpaw:auth-changed", reload);
  }, [refresh, hubMode, localAccount]);
}
