import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RocketOutlined } from "@ant-design/icons";
import { ToolCardShell } from "../shared";
import type { BuiltinCardProps } from "./index";
import {
  getPawAppTask,
  isTerminalTask,
  parsePawAppTaskResult,
  type PawAppTask,
  type PawAppTaskResult,
} from "../../../../api/modules/pawappTasks";
import { addRouterBasename } from "../../../../utils/navigationMode";
import styles from "./PawAppTaskCard.module.less";
import GenericToolCard from "./GenericToolCard";

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
            {appHref && (
              <a href={appHref}>
                {t(
                  blocked
                    ? "tool.pawappTask.settings"
                    : "tool.pawappTask.openApp",
                )}
              </a>
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

export default function PawAppTaskCard(props: BuiltinCardProps) {
  const result = useMemo(
    () => parsePawAppTaskResult(props.content.result),
    [props.content.result],
  );
  if (!result) return <GenericToolCard {...props} />;
  // A different handle must never inherit another card's state or requests.
  const key = `${result?.app_id}:${result?.workspace_id}:${result?.task?.task_id}:${result?.state}`;
  return <TaskCard key={key} {...props} result={result} />;
}
