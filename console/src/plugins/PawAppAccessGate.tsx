import { useEffect, useState, type ReactNode } from "react";
import { Alert, Button, Spin } from "antd";
import { useTranslation } from "react-i18next";
import { getApiToken } from "../api/config";
import { prepareBrowserSession } from "./pawapp-sdk/browserSession";
import { loadPawApp } from "./usePluginLoader";

/** Every navigation path waits for native resource authentication. */
export function PawAppAccessGate({
  appId,
  loadEntry = false,
  children,
}: {
  appId: string;
  loadEntry?: boolean;
  children: ReactNode;
}) {
  const { t } = useTranslation();
  const [ready, setReady] = useState("");
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [token, setToken] = useState(getApiToken);
  const identity = `${appId}:${token}`;

  useEffect(() => {
    const changed = () => setToken(getApiToken());
    window.addEventListener("storage", changed);
    window.addEventListener("qwenpaw:auth-changed", changed);
    return () => {
      window.removeEventListener("storage", changed);
      window.removeEventListener("qwenpaw:auth-changed", changed);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    setReady("");
    setError("");
    async function prepare() {
      try {
        const seconds = await prepareBrowserSession(appId);
        if (cancelled) return;
        if (loadEntry) await loadPawApp(appId);
        if (cancelled) return;
        setReady(identity);
        if (seconds !== null) {
          timer = setTimeout(prepare, Math.max(1, seconds - 60) * 1000);
        }
      } catch (cause) {
        if (cancelled) return;
        setReady("");
        setError(cause instanceof Error ? cause.message : String(cause));
      }
    }
    void prepare();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [appId, identity, loadEntry, retry]);

  if (error) {
    return (
      <Alert
        type="error"
        message={error}
        action={
          <Button onClick={() => setRetry((value) => value + 1)}>
            {t("common.retry", "Retry")}
          </Button>
        }
      />
    );
  }
  if (ready !== identity) return <Spin />;
  return children;
}
