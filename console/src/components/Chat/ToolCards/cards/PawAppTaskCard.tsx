import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RocketOutlined } from "@ant-design/icons";
import { ToolCardShell } from "../shared";
import type { BuiltinCardProps } from "./index";
import {
  getPawAppTask,
  isTerminalTask,
  openPawAppTask,
  pawAppArtifactUrl,
  type PawAppArtifactRef,
  parsePawAppOpenResult,
  parsePawAppTaskResult,
  type PawAppOpenResult,
  type PawAppTask,
  type PawAppTaskResult,
} from "../../../../api/modules/pawappTasks";
import { buildAuthHeaders } from "../../../../api/authHeaders";
import { addRouterBasename } from "../../../../utils/navigationMode";
import { downloadFileFromUrl } from "../../../../utils/downloadFileFromUrl";
import styles from "./PawAppTaskCard.module.less";
import GenericToolCard from "./GenericToolCard";

const MAX_REPORT_PREVIEW_BYTES = 2 * 1024 * 1024;

function navigateToApp(path: string) {
  const href = addRouterBasename(window.location.pathname, path);
  window.history.pushState(window.history.state, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function ArtifactItem({
  appId,
  workspaceId,
  artifact,
}: {
  appId: string;
  workspaceId: string;
  artifact: PawAppArtifactRef;
}) {
  const { t } = useTranslation();
  const [preview, setPreview] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const canPreview =
    artifact.size_bytes <= MAX_REPORT_PREVIEW_BYTES &&
    ["text/html", "text/markdown", "text/plain"].includes(artifact.media_type);
  const url = pawAppArtifactUrl(
    appId,
    workspaceId,
    artifact.artifact_id,
    artifact.version,
  );

  const loadPreview = async () => {
    if (preview !== null) {
      setPreview(null);
      return;
    }
    setLoading(true);
    setError(false);
    try {
      const response = await fetch(url, { headers: buildAuthHeaders() });
      if (!response.ok) throw new Error(String(response.status));
      setPreview(await response.text());
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  };

  const download = async () => {
    setError(false);
    try {
      await downloadFileFromUrl(
        pawAppArtifactUrl(
          appId,
          workspaceId,
          artifact.artifact_id,
          artifact.version,
          "download",
        ),
        artifact.name,
        { headers: buildAuthHeaders(), preferResponseFilename: true },
      );
    } catch {
      setError(true);
    }
  };

  const htmlPreview =
    artifact.media_type === "text/html" && preview !== null
      ? `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">${preview}`
      : null;

  return (
    <li>
      <div className={styles.artifactHeader}>
        <strong>{artifact.name}</strong>
        <span>
          {t("tool.pawappTask.artifactMeta", {
            version: artifact.version,
            size: artifact.size_bytes,
          })}
        </span>
      </div>
      <div className={styles.artifactActions}>
        {canPreview && (
          <button type="button" onClick={() => void loadPreview()}>
            {t(
              preview === null
                ? "tool.pawappTask.previewArtifact"
                : "tool.pawappTask.hideArtifact",
            )}
          </button>
        )}
        <button type="button" onClick={() => void download()}>
          {t("tool.pawappTask.downloadArtifact")}
        </button>
      </div>
      {loading && <small>{t("tool.pawappTask.loadingArtifact")}</small>}
      {error && <small>{t("tool.pawappTask.artifactUnavailable")}</small>}
      {htmlPreview !== null && (
        <iframe
          className={styles.reportPreview}
          sandbox=""
          srcDoc={htmlPreview}
          title={artifact.name}
        />
      )}
      {preview !== null && htmlPreview === null && (
        <pre className={styles.textPreview}>{preview}</pre>
      )}
    </li>
  );
}

function TaskCard({
  content,
  isStreaming,
  result,
}: BuiltinCardProps & {
  result: PawAppTaskResult | null;
}) {
  const { t } = useTranslation();
  const snapshot = result?.task;
  const [task, setTask] = useState<PawAppTask | undefined>(snapshot);
  const latestTask = useRef(snapshot);
  const [unavailable, setUnavailable] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [opening, setOpening] = useState(false);
  const [openFailed, setOpenFailed] = useState(false);
  const taskId = result?.task?.task_id;
  const appId = result?.app_id;
  const workspaceId = result?.workspace_id;

  useEffect(() => {
    if (!taskId || !appId || !workspaceId) return;
    const acceptSnapshot = (next: PawAppTask) => {
      if (
        !latestTask.current ||
        next.event_sequence > latestTask.current.event_sequence
      ) {
        latestTask.current = next;
        setTask(next);
      }
    };
    if (snapshot) acceptSnapshot(snapshot);
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let active = true;
    const poll = async () => {
      try {
        const next = await getPawAppTask(
          appId,
          workspaceId,
          taskId,
          controller.signal,
        );
        if (!active) return;
        acceptSnapshot(next);
        setUnavailable(false);
        if (latestTask.current && !isTerminalTask(latestTask.current)) {
          timer = setTimeout(poll, 2000);
        }
      } catch {
        if (active) setUnavailable(true);
      }
    };
    void poll();
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
    };
  }, [appId, workspaceId, taskId, refresh, snapshot]);

  const blocked = result?.state === "blocked";
  const recovering =
    !!task && !isTerminalTask(task) && task.recovery_state !== "none";
  const status = unavailable
    ? "unavailable"
    : blocked
    ? "blocked"
    : recovering
    ? "recovering"
    : task?.status;
  const title = appId
    ? t("tool.pawappTask.title", { app: appId })
    : t("tool.pawappTask.defaultTitle");
  const appHref = appId
    ? addRouterBasename(window.location.pathname, `/apps/${appId}`)
    : undefined;
  const openApp = async () => {
    if (!appId || !workspaceId || !taskId) return;
    setOpening(true);
    setOpenFailed(false);
    try {
      const action = await openPawAppTask(appId, workspaceId, taskId);
      navigateToApp(action.path);
    } catch {
      setOpenFailed(true);
    } finally {
      setOpening(false);
    }
  };
  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<RocketOutlined />}
      title={title}
      inlineResult={status ? t(`tool.pawappTask.status.${status}`) : null}
      defaultExpanded={!!result}
    >
      {result && (
        <div className={styles.body}>
          <div className={styles.header}>
            <span className={styles.status} data-status={status} role="status">
              {status && t(`tool.pawappTask.status.${status}`)}
            </span>
            {blocked && appHref && (
              <a href={appHref}>{t("tool.pawappTask.settings")}</a>
            )}
            {!blocked && task?.project_ref && (
              <button
                className={styles.openApp}
                type="button"
                disabled={opening}
                onClick={() => void openApp()}
              >
                {t("tool.pawappTask.openApp")}
              </button>
            )}
          </div>
          {blocked && (
            <p>
              {t(`tool.pawappTask.reason.${result.reason}`, {
                defaultValue: t("tool.pawappTask.setupNeeded"),
              })}
            </p>
          )}
          {unavailable && (
            <p>
              {t("tool.pawappTask.refreshFailed")}{" "}
              <button
                className={styles.refresh}
                onClick={() => setRefresh((value) => value + 1)}
              >
                {t("tool.pawappTask.refresh")}
              </button>
            </p>
          )}
          {recovering && !unavailable && <p>{t("tool.pawappTask.recovery")}</p>}
          {openFailed && <p>{t("tool.pawappTask.refreshFailed")}</p>}
          {task?.text_result != null && task.text_result !== "" && (
            <div>
              <div className={styles.resultLabel}>
                {t(
                  task.status === "succeeded"
                    ? "tool.pawappTask.result"
                    : "tool.pawappTask.partialResult",
                )}
              </div>
              <pre className={styles.result}>{task.text_result}</pre>
            </div>
          )}
          {!!task?.output_refs?.length && appId && workspaceId && (
            <div>
              <div className={styles.resultLabel}>
                {t("tool.pawappTask.artifacts")}
              </div>
              <ul className={styles.artifacts}>
                {task.output_refs.map((artifact) => (
                  <ArtifactItem
                    key={`${artifact.artifact_id}:${artifact.version}`}
                    appId={appId}
                    workspaceId={workspaceId}
                    artifact={artifact}
                  />
                ))}
              </ul>
            </div>
          )}
          {task && (
            <span className={styles.identifier}>
              {t("tool.pawappTask.taskId", { id: task.task_id })}
            </span>
          )}
        </div>
      )}
    </ToolCardShell>
  );
}

function OpenAppCard({
  content,
  isStreaming,
  result,
}: BuiltinCardProps & { result: PawAppOpenResult }) {
  const { t } = useTranslation();
  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<RocketOutlined />}
      title={t("tool.pawappTask.title", { app: result.app_id })}
      inlineResult={t("tool.pawappTask.openApp")}
      defaultExpanded
    >
      <div className={styles.body}>
        <button
          className={styles.openApp}
          type="button"
          onClick={() => navigateToApp(result.action.path)}
        >
          {t("tool.pawappTask.openApp")}
        </button>
      </div>
    </ToolCardShell>
  );
}

export default function PawAppTaskCard(props: BuiltinCardProps) {
  const openResult = useMemo(
    () => parsePawAppOpenResult(props.content.result),
    [props.content.result],
  );
  const result = useMemo(
    () => parsePawAppTaskResult(props.content.result),
    [props.content.result],
  );
  if (openResult) return <OpenAppCard {...props} result={openResult} />;
  if (!result) return <GenericToolCard {...props} />;
  // A different handle must never inherit another card's state or requests.
  const key = `${result?.app_id}:${result?.workspace_id}:${result?.task?.task_id}:${result?.state}`;
  return <TaskCard key={key} {...props} result={result} />;
}
