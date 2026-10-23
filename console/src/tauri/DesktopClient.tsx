import {
  Component,
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { animate } from "motion/mini";
import { invoke } from "@tauri-apps/api/core";
import { Moon, Sun, Power, RotateCw, CircleAlert } from "lucide-react";
import { useTranslation } from "react-i18next";
import { ThemeProvider, useTheme } from "../contexts/ThemeContext";
import CloseWindowPrompt from "./CloseWindowPrompt";
import {
  connectAgentHost,
  initialHostState,
  restartAgentHost,
} from "./agentHost";
import styles from "./DesktopClient.module.less";

// Fetch/parse the application in parallel with Python startup, in this document.
let consoleModule: Promise<typeof import("../ConsoleApp")> | undefined;
const loadConsole = () => (consoleModule ??= import("../ConsoleApp"));
const ConsoleApp = lazy(loadConsole);

class ConsoleBoundary extends Component<
  {
    children: ReactNode;
    fallback: (error: string) => ReactNode;
  },
  { error: string }
> {
  state = { error: "" };
  static getDerivedStateFromError(error: unknown) {
    return { error: String(error) };
  }
  render() {
    return this.state.error
      ? this.props.fallback(this.state.error)
      : this.props.children;
  }
}

function LoadingAvatar({ active }: { active: boolean }) {
  const image = useRef<HTMLImageElement>(null);
  useEffect(() => {
    const element = image.current;
    if (!element || !active) return;
    const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
    let animation: ReturnType<typeof animate> | undefined;
    const update = () => {
      animation?.cancel();
      if (!preference.matches) {
        animation = animate(
          element,
          {
            transform: [
              "translateY(0) rotate(-3deg)",
              "translateY(-6px) rotate(3deg)",
              "translateY(0) rotate(-3deg)",
            ],
          },
          { duration: 2.4, repeat: Infinity, ease: "easeInOut" },
        );
      }
    };
    update();
    preference.addEventListener("change", update);
    return () => {
      animation?.cancel();
      preference.removeEventListener("change", update);
    };
  }, [active]);
  return (
    <div className={styles.avatar} aria-hidden="true">
      <img
        ref={image}
        src={`${import.meta.env.BASE_URL}qwenpaw.png`}
        alt=""
        width={88}
        height={88}
      />
    </div>
  );
}

export default function DesktopClient() {
  const [connected, setConnected] = useState(false);

  return (
    <ThemeProvider syncRemote={connected}>
      <CloseWindowPrompt />
      <DesktopContent connected={connected} setConnected={setConnected} />
    </ThemeProvider>
  );
}

function DesktopContent({
  connected,
  setConnected,
}: {
  connected: boolean;
  setConnected: (connected: boolean) => void;
}) {
  const { t } = useTranslation();
  const { isDark, toggleTheme } = useTheme();
  const [host, setHost] = useState(initialHostState);
  const [error, setError] = useState("");
  const [restarting, setRestarting] = useState(false);
  const [subscription, setSubscription] = useState(0);

  useEffect(() => {
    let disposed = false;
    let disconnect: (() => void) | undefined;
    void connectAgentHost((snapshot) => {
      if (disposed) return;
      setHost(snapshot);
      setError("");
      if (snapshot.phase === "ready") setConnected(true);
    })
      .then((cleanup) => {
        if (disposed) cleanup();
        else disconnect = cleanup;
      })
      .catch((reason: unknown) => {
        if (!disposed) setError(String(reason));
      });
    return () => {
      disposed = true;
      disconnect?.();
    };
  }, [subscription, setConnected]);

  useEffect(() => {
    let preload = 0;
    const frame = requestAnimationFrame(() => {
      preload = requestAnimationFrame(() => {
        void loadConsole().catch(() => undefined);
      });
    });
    return () => {
      cancelAnimationFrame(frame);
      cancelAnimationFrame(preload);
    };
  }, []);

  async function restart() {
    setRestarting(true);
    setError("");
    setSubscription((value) => value + 1);
    try {
      await restartAgentHost();
    } catch (reason) {
      setError(String(reason));
    } finally {
      setRestarting(false);
    }
  }

  const failed = host.phase === "failed" || !!error;
  const status = failed
    ? t("desktop.host.failed")
    : t("desktop.host.connecting");
  const controls = (
    <>
      {!connected && (
        <button
          type="button"
          onClick={toggleTheme}
          title={t("desktop.host.theme")}
          aria-label={t("desktop.host.theme")}
        >
          {isDark ? <Sun size={18} /> : <Moon size={18} />}
        </button>
      )}
      <button
        type="button"
        onClick={() =>
          void invoke("quit_app").catch((reason) => setError(String(reason)))
        }
      >
        <Power size={16} />
        {t("desktop.closeWindow.quitApp")}
      </button>
    </>
  );
  const connection = (
    <section className={styles.connection} aria-live="polite">
      <LoadingAvatar active={!failed} />
      <h1>QwenPaw</h1>
      <p className={styles.hint}>{status}</p>
      {(host.error || error) && (
        <details>
          <summary>{t("desktop.host.details")}</summary>
          <pre>{error || host.error}</pre>
        </details>
      )}
      {failed && (
        <button
          type="button"
          disabled={restarting}
          onClick={() => void restart()}
        >
          <RotateCw size={16} />
          {t("desktop.host.retry")}
        </button>
      )}
    </section>
  );

  if (!connected) {
    return (
      <main className={styles.shell} data-desktop-client="ready">
        <header>
          <span>QwenPaw</span>
          <nav aria-label={t("desktop.host.controls")}>{controls}</nav>
        </header>
        {connection}
      </main>
    );
  }

  const fallback = <main className={styles.shell}>{connection}</main>;
  return (
    <>
      <ConsoleBoundary
        fallback={(reason) => (
          <main className={styles.shell}>
            <header>
              <span>QwenPaw</span>
              {controls}
            </header>
            <section className={styles.connection} role="alert">
              <p>{t("desktop.host.failed")}</p>
              <pre>{reason}</pre>
              <button onClick={() => window.location.reload()}>
                {t("common.refresh")}
              </button>
            </section>
          </main>
        )}
      >
        <Suspense fallback={fallback}>
          <ConsoleApp loadingFallback={fallback} />
        </Suspense>
      </ConsoleBoundary>
      {(host.phase === "starting" || failed) && (
        <aside className={styles.banner} role="status">
          <CircleAlert size={18} />
          <span>{status}</span>
          <button
            type="button"
            disabled={restarting || host.phase === "starting"}
            onClick={() => void restart()}
          >
            <RotateCw size={16} />
            {t("desktop.host.retry")}
          </button>
          {controls}
        </aside>
      )}
    </>
  );
}
