import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ArrowRightOutlined, RocketOutlined } from "@ant-design/icons";
import { ToolCardShell } from "../shared";
import type { BuiltinCardProps } from "./index";
import {
  answerPawAppTask,
  getPawAppTask,
  isTerminalTask,
  openPawAppSetup,
  openPawAppTask,
  pawAppArtifactUrl,
  type PawAppArtifactRef,
  type PawAppLocalizedText,
  type PawAppTaskAnswer,
  parsePawAppOpenResult,
  parsePawAppTaskResult,
  type PawAppOpenResult,
  type PawAppTask,
  type PawAppTaskExperienceSnapshot,
  type PawAppTaskInputRequest,
  type PawAppTaskResult,
} from "../../../../api/modules/pawappTasks";
import { buildAuthHeaders } from "../../../../api/authHeaders";
import { createClientMessageId } from "../../../../utils/clientMessageId";
import { addRouterBasename } from "../../../../utils/navigationMode";
import { downloadFileFromUrl } from "../../../../utils/downloadFileFromUrl";
import { usePawAppTaskSurface } from "../PawAppTaskSurfaceProvider";
import styles from "./PawAppTaskCard.module.less";
import GenericToolCard from "./GenericToolCard";

const MAX_REPORT_PREVIEW_BYTES = 2 * 1024 * 1024;

function localizedText(value: PawAppLocalizedText, language?: string): string {
  if (!language) return value.default;
  const exact = value.translations[language];
  if (exact) return exact;
  const base = language.split("-", 1)[0];
  return (
    value.translations[base] ??
    Object.entries(value.translations).find(
      ([locale]) => locale.split("-", 1)[0] === base,
    )?.[1] ??
    value.default
  );
}

function TaskExperience({
  experience,
  language,
}: {
  experience: PawAppTaskExperienceSnapshot;
  language?: string;
}) {
  const stateById = new Map(
    experience.step_states.map((state) => [state.step_id, state]),
  );
  return (
    <div className={styles.experience}>
      <ol className={styles.steps}>
        {experience.definition.steps.map((step, index) => {
          const state = stateById.get(step.id)!;
          return (
            <li
              key={step.id}
              data-status={state.status}
              aria-current={
                experience.active_step_id === step.id ? "step" : undefined
              }
            >
              <span className={styles.stepMarker} aria-hidden="true">
                {state.status === "complete" ? "✓" : index + 1}
              </span>
              <span>{localizedText(step.label, language)}</span>
            </li>
          );
        })}
      </ol>
      {!!experience.context_items.length && (
        <dl className={styles.contextItems}>
          {experience.context_items.map((item) => (
            <div key={item.id}>
              <dt>{localizedText(item.label, language)}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function navigateToApp(path: string) {
  const href = addRouterBasename(window.location.pathname, path);
  // Mark this as an inline PawApp entry so the App Center's close action
  // returns to the exact chat/session history entry that launched it.
  window.history.pushState(
    { ...(window.history.state ?? {}), pawappInline: true },
    "",
    href,
  );
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function TaskStatusOpenPrompt({ result }: { result: PawAppTaskResult }) {
  const { t, i18n } = useTranslation();
  const [opening, setOpening] = useState(false);
  const [openFailed, setOpenFailed] = useState(false);
  const task = result.task;
  const experience = task?.experience;
  const language = i18n?.resolvedLanguage ?? i18n?.language;
  const selectedView = experience?.definition.views.find(
    (view) => view.id === experience.view_id,
  );
  const openLabel = selectedView
    ? localizedText(selectedView.open_label, language)
    : t("tool.pawappTask.openTask");

  if (!task?.project_ref) return null;

  const openTask = async () => {
    setOpening(true);
    setOpenFailed(false);
    try {
      const action = await openPawAppTask(
        result.app_id,
        result.workspace_id,
        task.task_id,
      );
      navigateToApp(action.path);
    } catch {
      setOpenFailed(true);
    } finally {
      setOpening(false);
    }
  };

  return (
    <div className={styles.statusPrompt}>
      <span>{t("tool.pawappTask.openTaskPrompt")}</span>
      <button
        className={styles.openApp}
        type="button"
        disabled={opening}
        onClick={() => void openTask()}
      >
        {opening ? t("tool.pawappTask.openingTask") : openLabel}
        <ArrowRightOutlined aria-hidden="true" />
      </button>
      {openFailed && (
        <small role="alert">{t("tool.pawappTask.refreshFailed")}</small>
      )}
    </div>
  );
}

export function PawAppArtifactItem({
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
    artifact.presentation?.preview !== "none" &&
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
        <strong>
          {artifact.name}
          {artifact.presentation?.role === "primary" && (
            <small className={styles.primaryBadge}>
              {t("tool.pawappTask.primaryArtifact")}
            </small>
          )}
        </strong>
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

type AnswerDraft = {
  selectedOptions: string[];
  customText: string;
};

function TaskInputForm({
  appId,
  workspaceId,
  taskId,
  request,
  onSettled,
}: {
  appId: string;
  workspaceId: string;
  taskId: string;
  request: PawAppTaskInputRequest;
  onSettled: () => void;
}) {
  const { t } = useTranslation();
  const [drafts, setDrafts] = useState<Record<number, AnswerDraft>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<"required" | "rejected" | "failed" | null>(
    null,
  );
  const command = useRef<{ requestId: string; commandId: string } | null>(null);

  useEffect(() => {
    setDrafts({});
    setError(null);
    command.current = null;
  }, [request.request_id]);

  const updateDraft = (index: number, next: AnswerDraft) => {
    setDrafts((current) => ({ ...current, [index]: next }));
    setError(null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const answers: PawAppTaskAnswer[] = request.questions.map(
      (question, index) => {
        const draft = drafts[index] ?? { selectedOptions: [], customText: "" };
        const customText = draft.customText.trim();
        return {
          question: question.question,
          selected_options: draft.selectedOptions,
          custom_text: customText || null,
        };
      },
    );
    if (
      answers.some(
        (answer) =>
          answer.selected_options.length === 0 && answer.custom_text === null,
      )
    ) {
      setError("required");
      return;
    }
    if (command.current?.requestId !== request.request_id) {
      command.current = {
        requestId: request.request_id,
        commandId: createClientMessageId(),
      };
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await answerPawAppTask(
        appId,
        workspaceId,
        taskId,
        command.current.commandId,
        request.request_id,
        answers,
      );
      setError(result.state === "accepted" ? null : "rejected");
    } catch {
      setError("failed");
    } finally {
      setSubmitting(false);
      onSettled();
    }
  };

  return (
    <form
      className={styles.inputRequest}
      onSubmit={(event) => void submit(event)}
    >
      {request.title && <strong>{request.title}</strong>}
      {request.questions.map((question, index) => {
        const draft = drafts[index] ?? { selectedOptions: [], customText: "" };
        return (
          <fieldset key={`${index}:${question.question}`} disabled={submitting}>
            <legend>{question.question}</legend>
            {question.description && <p>{question.description}</p>}
            <div className={styles.answerOptions}>
              {question.options.map((option) => {
                const checked = draft.selectedOptions.includes(option.label);
                return (
                  <label key={option.label}>
                    <input
                      type={question.multi_select ? "checkbox" : "radio"}
                      name={`${taskId}:${request.request_id}:${index}`}
                      value={option.label}
                      checked={checked}
                      onChange={(event) => {
                        const selectedOptions = question.multi_select
                          ? event.target.checked
                            ? [...draft.selectedOptions, option.label]
                            : draft.selectedOptions.filter(
                                (label) => label !== option.label,
                              )
                          : [option.label];
                        updateDraft(index, { ...draft, selectedOptions });
                      }}
                    />
                    <span>
                      <strong>{option.label}</strong>
                      {option.description && (
                        <small>{option.description}</small>
                      )}
                    </span>
                  </label>
                );
              })}
            </div>
            <label className={styles.customAnswer}>
              <span>{t("tool.pawappTask.customAnswer")}</span>
              <input
                type="text"
                value={draft.customText}
                onChange={(event) =>
                  updateDraft(index, {
                    ...draft,
                    customText: event.target.value,
                  })
                }
              />
            </label>
          </fieldset>
        );
      })}
      {error && <p role="alert">{t(`tool.pawappTask.answerError.${error}`)}</p>}
      <button type="submit" disabled={submitting}>
        {t(
          submitting
            ? "tool.pawappTask.submittingAnswer"
            : "tool.pawappTask.submitAnswer",
        )}
      </button>
    </form>
  );
}

function TaskCard({
  content,
  isStreaming,
  result,
  statusCheckCount = 0,
}: BuiltinCardProps & {
  result: PawAppTaskResult | null;
  statusCheckCount?: number;
}) {
  const { t, i18n } = useTranslation();
  const snapshot = result?.task;
  const [task, setTask] = useState<PawAppTask | undefined>(snapshot);
  const latestTask = useRef(snapshot);
  const [unavailable, setUnavailable] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [opening, setOpening] = useState(false);
  const [openFailed, setOpenFailed] = useState(false);
  const [setupOpening, setSetupOpening] = useState(false);
  const [setupFailed, setSetupFailed] = useState(false);
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
  const language = i18n?.resolvedLanguage ?? i18n?.language;
  const experience = task?.experience ?? null;
  const title = experience
    ? localizedText(experience.definition.title, language)
    : appId === "qwenpaw-creator"
    ? t("tool.pawappTask.creatorTitle")
    : appId
    ? t("tool.pawappTask.title", { app: appId })
    : t("tool.pawappTask.defaultTitle");
  const selectedView = experience?.definition.views.find(
    (view) => view.id === experience.view_id,
  );
  const openLabel = selectedView
    ? localizedText(selectedView.open_label, language)
    : appId === "qwenpaw-creator"
    ? t("tool.pawappTask.openCreator")
    : t("tool.pawappTask.openApp");
  const openingLabel =
    appId === "qwenpaw-creator"
      ? t("tool.pawappTask.openingCreator")
      : t("tool.pawappTask.openingApp");
  const appHref = appId
    ? addRouterBasename(window.location.pathname, `/apps/${appId}`)
    : undefined;
  const chatArtifacts = (task?.output_refs ?? [])
    .filter(
      (artifact) =>
        artifact.presentation === undefined ||
        artifact.presentation === null ||
        artifact.presentation.visibility === "chat",
    )
    .sort((left, right) => {
      const roles = { primary: 0, supporting: 1, diagnostic: 2, source: 3 };
      const leftRole = left.presentation?.role;
      const rightRole = right.presentation?.role;
      return (
        (leftRole === undefined ? 1 : roles[leftRole]) -
          (rightRole === undefined ? 1 : roles[rightRole]) ||
        (left.presentation?.rank ?? 100) - (right.presentation?.rank ?? 100)
      );
    });
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
  const openSetup = async () => {
    const setupRequestId = task?.setup_request_id;
    if (!appId || !workspaceId || !setupRequestId) return;
    setSetupOpening(true);
    setSetupFailed(false);
    try {
      const action = await openPawAppSetup(appId, workspaceId, setupRequestId);
      navigateToApp(action.path);
    } catch {
      setSetupFailed(true);
    } finally {
      setSetupOpening(false);
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
            <div className={styles.actions}>
              {!blocked &&
                task?.status === "waiting_for_setup" &&
                task.setup_request_id && (
                  <button
                    className={styles.secondaryAction}
                    type="button"
                    disabled={setupOpening}
                    onClick={() => void openSetup()}
                  >
                    {t(
                      setupOpening
                        ? "tool.pawappTask.openingSetup"
                        : "tool.pawappTask.completeSetup",
                    )}
                  </button>
                )}
              {!blocked && task?.project_ref && (
                <button
                  className={styles.openApp}
                  type="button"
                  disabled={opening}
                  onClick={() => void openApp()}
                >
                  {opening ? openingLabel : openLabel}
                  <ArrowRightOutlined aria-hidden="true" />
                </button>
              )}
            </div>
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
          {setupFailed && <p>{t("tool.pawappTask.setupOpenFailed")}</p>}
          {experience && (
            <TaskExperience experience={experience} language={language} />
          )}
          {task?.input_request && appId && workspaceId && taskId && (
            <TaskInputForm
              appId={appId}
              workspaceId={workspaceId}
              taskId={taskId}
              request={task.input_request}
              onSettled={() => setRefresh((value) => value + 1)}
            />
          )}
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
          {!!chatArtifacts.length && appId && workspaceId && (
            <div>
              <div className={styles.resultLabel}>
                {t("tool.pawappTask.artifacts")}
              </div>
              <ul className={styles.artifacts}>
                {chatArtifacts.map((artifact) => (
                  <PawAppArtifactItem
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
            <details className={styles.details}>
              <summary>{t("tool.pawappTask.details")}</summary>
              <span className={styles.identifier}>
                {t("tool.pawappTask.taskId", { id: task.task_id })}
              </span>
              {statusCheckCount > 0 && (
                <span className={styles.identifier}>
                  {t("tool.pawappTask.statusChecksFolded", {
                    count: statusCheckCount,
                  })}
                </span>
              )}
            </details>
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
  const openLabel =
    result.app_id === "qwenpaw-creator"
      ? t("tool.pawappTask.openCreator")
      : t("tool.pawappTask.openApp");
  return (
    <ToolCardShell
      content={content}
      isStreaming={isStreaming}
      icon={<RocketOutlined />}
      title={
        result.app_id === "qwenpaw-creator"
          ? t("tool.pawappTask.creatorTitle")
          : t("tool.pawappTask.title", { app: result.app_id })
      }
      inlineResult={openLabel}
      defaultExpanded
    >
      <div className={styles.body}>
        <button
          className={styles.openApp}
          type="button"
          onClick={() => navigateToApp(result.action.path)}
        >
          {openLabel}
          <ArrowRightOutlined aria-hidden="true" />
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
  const surface = usePawAppTaskSurface(
    props.content.id,
    props.content.name,
    result,
  );
  if (openResult) return <OpenAppCard {...props} result={openResult} />;
  if (!result) return <GenericToolCard {...props} />;
  const surfaceResult = surface.result ?? result;
  if (surface.managed && !surface.ready) return null;
  if (surface.managed && !surface.canonical) {
    return props.content.name === "get_app_task" &&
      surface.latestStatusCheck ? (
      <TaskStatusOpenPrompt result={surfaceResult} />
    ) : null;
  }
  // A different handle must never inherit another card's state or requests.
  const key = `${surfaceResult.app_id}:${surfaceResult.workspace_id}:${surfaceResult.task?.task_id}:${surfaceResult.state}`;
  return (
    <TaskCard
      key={key}
      {...props}
      result={surfaceResult}
      statusCheckCount={surface.statusCheckCount}
    />
  );
}
