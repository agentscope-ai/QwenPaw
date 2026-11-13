import { Progress, Spin, Steps } from "antd";
import { Button } from "@agentscope-ai/design";
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useDesktopUpdate } from "../../contexts/DesktopUpdateContext";
import styles from "./index.module.less";

export function UpdateTakeoverGate({ children }: { children: ReactNode }) {
  const { phase, isBackground } = useDesktopUpdate();
  const isActive =
    phase === "checking" ||
    phase === "downloading" ||
    phase === "installing" ||
    phase === "failed";
  const shouldTakeover = isActive && !isBackground;
  return shouldTakeover ? <UpdateTakeoverPage /> : <>{children}</>;
}

const KEY_PREFIX = "sidebar.updateModal";

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function UpdateTakeoverPage() {
  const { t } = useTranslation();
  const update = useDesktopUpdate();

  if (update.phase === "failed") {
    const errorKind = update.error?.kind ?? "other";
    return (
      <div className={styles.takeover}>
        <div className={styles.center}>
          <Progress type="circle" percent={100} status="exception" size={96} />
          <h1 className={styles.title}>{t(`${KEY_PREFIX}.failedTitle`)}</h1>
          <p className={styles.subtitle}>
            {t(`${KEY_PREFIX}.errors.${errorKind}`)}
          </p>
          {update.error?.message && (
            <pre className={styles.errorMessage}>{update.error.message}</pre>
          )}
          <div className={styles.actions}>
            <Button onClick={update.dismissFailure}>
              {t(`${KEY_PREFIX}.back`)}
            </Button>
            <Button type="primary" onClick={update.retry}>
              {t(`${KEY_PREFIX}.retry`)}
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const stepIndex =
    update.phase === "downloading" ? 1 : update.phase === "installing" ? 2 : 0;

  const isDownloading = update.phase === "downloading";
  const total = update.total ?? null;
  const percent =
    isDownloading && total && total > 0
      ? Math.min(100, Math.round((update.downloaded / total) * 100))
      : null;

  const title = t(`${KEY_PREFIX}.${update.phase}`);
  const subtitle =
    update.phase === "checking"
      ? t(`${KEY_PREFIX}.checkingHint`)
      : t(`${KEY_PREFIX}.downloadingTo`, { version: update.version });

  return (
    <div className={styles.takeover}>
      <div className={styles.center}>
        {percent !== null ? (
          <Progress type="circle" percent={percent} size={96} />
        ) : (
          <Spin size="large" />
        )}

        <h1 className={styles.title}>{title}</h1>
        <p className={styles.subtitle}>{subtitle}</p>
        <p className={styles.willRestart}>{t(`${KEY_PREFIX}.willRestart`)}</p>

        <Steps
          size="small"
          current={stepIndex}
          className={styles.steps}
          items={[
            { title: t(`${KEY_PREFIX}.stepPrepare`) },
            { title: t(`${KEY_PREFIX}.stepDownloading`) },
            { title: t(`${KEY_PREFIX}.stepInstalling`) },
          ]}
        />

        {isDownloading && (
          <p className={styles.progressLine}>
            {t(`${KEY_PREFIX}.downloadProgress`, {
              done: formatBytes(update.downloaded),
              total: total ? formatBytes(total) : "-",
              rate: `${formatBytes(update.throughputBps)}/s`,
            })}
          </p>
        )}
      </div>
    </div>
  );
}
