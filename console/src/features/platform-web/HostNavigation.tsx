import { useEffect } from "react";
import { useLocation } from "react-router-dom";
import { consoleHost, hostRequest } from "./context";

export function HostNavigation() {
  const { pathname, search, hash } = useLocation();
  useEffect(() => {
    if (consoleHost)
      void hostRequest("/host/navigation", { route: pathname + search + hash });
  }, [pathname, search, hash]);
  return null;
}
