import { host } from "./host";
import { useTranslation } from "./locale";
const React = host.React;
const { useCallback, useEffect, useMemo, useRef, useState } = React;
const {
  Alert,
  Checkbox,
  Descriptions,
  Input,
  Modal,
  Space,
  Tooltip,
  Typography,
  message,
  Button,
} = host.antd;
const { CaretRightOutlined, PauseOutlined, PlayCircleOutlined, StopOutlined } =
  host.antdIcons;

import {
  createRecordingApi,
  type DesktopRecordingStatus,
  type LearnEvidencePreview,
  type RecordingReview,
  type ReviewedSkillDraft,
} from "./api";
import styles from "./recording.module.less";
import css from "./recording.module.less?inline";

const STATUS_POLL_MS = 2000;

type RecordingAction = "start" | "pause" | "resume" | "stop";
type LearnStage = "intent" | "consent" | "draft";

const errorCode = (error: unknown): string => {
  const text = error instanceof Error ? error.message : String(error);
  if (text.includes("input_monitoring_denied")) {
    return "inputMonitoringDenied";
  }
  if (text.includes("desktop_busy")) return "desktopBusy";
  if (text.includes("desktop_runtime_unavailable")) {
    return "runtimeUnavailable";
  }
  return "generic";
};

export function DesktopRecordingControl() {
  const agent = host.useSelectedAgent();
  return <RecordingControl key={agent.id} agentId={agent.id} />;
}

function RecordingControl({ agentId }: { agentId: string }) {
  const desktopRecordingApi = useMemo(
    () => createRecordingApi(agentId),
    [agentId],
  );
  const { t } = useTranslation();
  const [status, setStatus] = useState<DesktopRecordingStatus | null>(null);
  const [action, setAction] = useState<RecordingAction | null>(null);
  const [statusError, setStatusError] = useState(false);
  const [learnOpen, setLearnOpen] = useState(false);
  const [learnStage, setLearnStage] = useState<LearnStage>("intent");
  const [learnBusy, setLearnBusy] = useState(false);
  const [learnRecordingId, setLearnRecordingId] = useState("");
  const [goal, setGoal] = useState("");
  const [confirmedContext, setConfirmedContext] = useState("");
  const [preview, setPreview] = useState<LearnEvidencePreview | null>(null);
  const [review, setReview] = useState<RecordingReview | null>(null);
  const [selectedEventIds, setSelectedEventIds] = useState<string[]>([]);
  const [consented, setConsented] = useState(false);
  const [draft, setDraft] = useState<ReviewedSkillDraft | null>(null);
  const [draftName, setDraftName] = useState("");
  const [draftContent, setDraftContent] = useState("");
  const recoveryAttempted = useRef(new Set<string>());
  const statusEpoch = useRef(0);
  const mutating = useRef(false);
  const refreshing = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const refresh = useCallback(async () => {
    if (mutating.current || refreshing.current || !mounted.current) return;
    refreshing.current = true;
    const epoch = statusEpoch.current;
    try {
      const next = await desktopRecordingApi.getStatus();
      if (mounted.current && epoch === statusEpoch.current) {
        setStatus(next);
        setStatusError(false);
      }
    } catch {
      if (mounted.current && epoch === statusEpoch.current)
        setStatusError(true);
    } finally {
      refreshing.current = false;
    }
  }, [desktopRecordingApi]);

  useEffect(() => {
    let disposed = false;
    const update = async () => {
      if (disposed) return;
      await refresh();
    };
    void update();
    const timer = window.setInterval(() => void update(), STATUS_POLL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [refresh]);

  useEffect(() => {
    const completed = status?.last_recording;
    if (
      learnOpen ||
      completed?.state !== "completed" ||
      completed.agent_id !== agentId ||
      recoveryAttempted.current.has(completed.recording_id)
    ) {
      return;
    }
    recoveryAttempted.current.add(completed.recording_id);
    void desktopRecordingApi
      .recoverDraft(completed.recording_id)
      .then((recovered) => {
        if (recovered === null || !mounted.current) return;
        setLearnRecordingId(recovered.recording_id);
        setDraft(recovered);
        setDraftName(recovered.name);
        setDraftContent(recovered.content);
        setLearnStage("draft");
        setLearnOpen(true);
      })
      .catch(() => {
        recoveryAttempted.current.delete(completed.recording_id);
      });
  }, [learnOpen, status?.last_recording, agentId, desktopRecordingApi]);

  const run = async (nextAction: RecordingAction) => {
    if (mutating.current) return;
    mutating.current = true;
    statusEpoch.current += 1;
    setAction(nextAction);
    try {
      if (
        nextAction === "start" &&
        (status?.input_monitoring === "required" ||
          status?.accessibility === "required")
      ) {
        const permission = await desktopRecordingApi.requestPermission();
        if (!mounted.current) return;
        setStatus(permission);
        if (permission.input_monitoring !== "granted") {
          message.info(t("desktop.recording.permissionRequested"));
          return;
        }
        if (permission.accessibility !== "granted") {
          message.info(t("desktop.recording.permissionRequested"));
        }
      }
      const next = await desktopRecordingApi[nextAction]();
      if (!mounted.current) return;
      setStatus(next);
      setStatusError(false);
      if (nextAction === "start") {
        message.success(t("desktop.recording.started"));
      } else if (nextAction === "stop") {
        message.success(t("desktop.recording.saved"));
        const completed = next.last_recording;
        if (
          completed?.state === "completed" &&
          completed.agent_id === agentId &&
          completed.event_count > 0 &&
          mounted.current
        ) {
          setLearnRecordingId(completed.recording_id);
          setLearnStage("intent");
          setLearnOpen(true);
          setLearnBusy(true);
          void desktopRecordingApi
            .reviewRecording(completed.recording_id)
            .then((nextReview) => {
              setReview(nextReview);
              setSelectedEventIds(
                nextReview.events.map((event) => event.evidence_id),
              );
            })
            .catch(() => {
              message.error(t("desktop.recording.learn.failed"));
            })
            .finally(() => setLearnBusy(false));
        }
      }
    } catch (error) {
      if (mounted.current) {
        setStatusError(true);
        message.error(t(`desktop.recording.errors.${errorCode(error)}`));
      }
    } finally {
      mutating.current = false;
      if (mounted.current) setAction(null);
    }
  };

  const resetLearn = () => {
    setLearnOpen(false);
    setLearnStage("intent");
    setLearnBusy(false);
    setLearnRecordingId("");
    setGoal("");
    setConfirmedContext("");
    setPreview(null);
    setReview(null);
    setSelectedEventIds([]);
    setConsented(false);
    setDraft(null);
    setDraftName("");
    setDraftContent("");
  };

  const updateDraftName = (nextName: string) => {
    setDraftName(nextName);
    setDraftContent((current) =>
      current.replace(/^name:.*$/m, `name: ${nextName}`),
    );
  };

  const runLearn = async () => {
    if (learnBusy) return;
    setLearnBusy(true);
    try {
      if (learnStage === "intent") {
        const selectedSequences = (review?.events ?? [])
          .filter((event) => selectedEventIds.includes(event.evidence_id))
          .flatMap((event) => event.source_sequences);
        const next = await desktopRecordingApi.prepareLearn({
          recording_id: learnRecordingId,
          goal: goal.trim(),
          confirmed_context: confirmedContext.trim(),
          selected_sequences: selectedSequences,
        });
        setPreview(next);
        setConsented(false);
        setLearnStage("consent");
      } else if (learnStage === "consent" && preview !== null) {
        const next = await desktopRecordingApi.generateDraft(
          preview.consent_token,
        );
        setDraft(next);
        setDraftName(next.name);
        setDraftContent(next.content);
        setLearnStage("draft");
      } else if (learnStage === "draft" && draft !== null) {
        const result = await desktopRecordingApi.materializeSkill({
          draft_id: draft.draft_id,
          name: draftName.trim(),
          content: draftContent,
        });
        message.success(
          t("desktop.recording.learn.created", { name: result.name }),
        );
        resetLearn();
      }
    } catch (error) {
      const missingModel =
        error instanceof Error &&
        ["learn_model_unavailable", "learn_provider_unavailable"].includes(
          error.message,
        );
      message.error(
        t(
          missingModel
            ? "desktop.recording.learn.modelUnavailable"
            : "desktop.recording.learn.failed",
        ),
      );
    } finally {
      setLearnBusy(false);
    }
  };

  const available = status?.available === true && !statusError;
  const state = status?.state ?? "idle";
  const recording = state === "recording";
  const paused = state === "paused";
  const tooltip = available
    ? t("desktop.recording.title")
    : t("desktop.recording.unavailable");
  const startLabel =
    status?.input_monitoring === "required" ||
    status?.accessibility === "required"
      ? t("desktop.recording.authorize")
      : t("desktop.recording.start");

  const recordingControl =
    !recording && !paused ? (
      <Tooltip title={tooltip}>
        <span>
          <Button
            type="text"
            size="small"
            icon={<PlayCircleOutlined />}
            className={styles.startButton}
            disabled={!available}
            loading={action === "start" || status === null}
            aria-label={startLabel}
            onClick={() => void run("start")}
          >
            {startLabel}
          </Button>
        </span>
      </Tooltip>
    ) : (
      <div
        className={styles.control}
        role="group"
        aria-label={t("desktop.recording.title")}
        data-state={state}
      >
        <span className={styles.recordingLabel} role="status">
          <span className={styles.recordingDot} aria-hidden="true" />
          {paused
            ? t("desktop.recording.paused")
            : t("desktop.recording.recording")}
        </span>
        <Space size={0}>
          <Tooltip
            title={
              paused
                ? t("desktop.recording.resume")
                : t("desktop.recording.pause")
            }
          >
            <Button
              type="text"
              size="small"
              className={styles.actionButton}
              icon={paused ? <CaretRightOutlined /> : <PauseOutlined />}
              loading={action === "pause" || action === "resume"}
              disabled={action !== null}
              aria-label={
                paused
                  ? t("desktop.recording.resume")
                  : t("desktop.recording.pause")
              }
              onClick={() => void run(paused ? "resume" : "pause")}
            />
          </Tooltip>
          <Tooltip title={t("desktop.recording.stop")}>
            <Button
              type="text"
              size="small"
              className={styles.stopButton}
              icon={<StopOutlined />}
              loading={action === "stop"}
              disabled={action !== null}
              aria-label={t("desktop.recording.stop")}
              onClick={() => void run("stop")}
            />
          </Tooltip>
        </Space>
      </div>
    );

  const okDisabled =
    (learnStage === "intent" &&
      (!goal.trim() || review === null || selectedEventIds.length === 0)) ||
    (learnStage === "consent" && !consented) ||
    (learnStage === "draft" &&
      (!draftName.trim() ||
        !draftContent.trim() ||
        draft?.needs_confirmation === true));

  return (
    <>
      <style>{css}</style>
      {recordingControl}
      {state === "failed" && (
        <Typography.Text type="danger" role="alert">
          {t("desktop.recording.errors.generic")}
        </Typography.Text>
      )}
      <Modal
        open={learnOpen}
        title={t(`desktop.recording.learn.${learnStage}Title`)}
        okText={t(`desktop.recording.learn.${learnStage}Action`)}
        cancelText={t("desktop.recording.cancel")}
        confirmLoading={learnBusy}
        okButtonProps={{ disabled: okDisabled }}
        onOk={() => void runLearn()}
        onCancel={resetLearn}
        width={720}
        destroyOnHidden
      >
        {learnStage === "intent" && (
          <Space
            direction="vertical"
            size="middle"
            className={styles.learnBody}
          >
            <Typography.Text>
              {t("desktop.recording.learn.intentDescription")}
            </Typography.Text>
            <Input.TextArea
              value={goal}
              rows={3}
              maxLength={500}
              showCount
              aria-label={t("desktop.recording.learn.goal")}
              placeholder={t("desktop.recording.learn.goalPlaceholder")}
              onChange={(event) => setGoal(event.target.value)}
            />
            <Input.TextArea
              value={confirmedContext}
              rows={2}
              maxLength={2000}
              aria-label={t("desktop.recording.learn.context")}
              placeholder={t("desktop.recording.learn.contextPlaceholder")}
              onChange={(event) => setConfirmedContext(event.target.value)}
            />
            {review !== null && (
              <div className={styles.timeline}>
                <Typography.Text strong>
                  {t("desktop.recording.learn.selectEvents")}
                </Typography.Text>
                {review.events.map((event) => {
                  const target =
                    event.locator.name ||
                    event.locator.identifier ||
                    event.locator.role ||
                    t("desktop.recording.learn.noTarget");
                  const app =
                    event.locator.app_name ||
                    event.locator.bundle_id ||
                    t("desktop.recording.learn.unknownApp");
                  return (
                    <Checkbox
                      key={event.evidence_id}
                      checked={selectedEventIds.includes(event.evidence_id)}
                      onChange={(change) =>
                        setSelectedEventIds((current) =>
                          change.target.checked
                            ? [...current, event.evidence_id]
                            : current.filter(
                                (item) => item !== event.evidence_id,
                              ),
                        )
                      }
                    >
                      {app} · {target} ·{" "}
                      {t(`desktop.recording.learn.eventType.${event.type}`)} (
                      {event.source_sequences.length})
                    </Checkbox>
                  );
                })}
              </div>
            )}
          </Space>
        )}

        {learnStage === "consent" && preview !== null && (
          <Space
            direction="vertical"
            size="middle"
            className={styles.learnBody}
          >
            <Alert
              type={preview.external_transfer ? "warning" : "info"}
              showIcon
              message={
                preview.external_transfer
                  ? t("desktop.recording.learn.externalTransfer")
                  : t("desktop.recording.learn.localProcessing")
              }
              description={t("desktop.recording.learn.consentDescription")}
            />
            <Descriptions size="small" column={1} bordered>
              <Descriptions.Item label={t("desktop.recording.learn.provider")}>
                {preview.model_target.provider_id}
              </Descriptions.Item>
              <Descriptions.Item label={t("desktop.recording.learn.model")}>
                {preview.model_target.model}
              </Descriptions.Item>
              <Descriptions.Item label={t("desktop.recording.learn.events")}>
                {preview.selected_event_count} → {preview.evidence_event_count}
              </Descriptions.Item>
              <Descriptions.Item label={t("desktop.recording.learn.fields")}>
                {preview.field_scope.join(", ")}
              </Descriptions.Item>
            </Descriptions>
            <Checkbox
              checked={consented}
              onChange={(event) => setConsented(event.target.checked)}
            >
              {t("desktop.recording.learn.consent")}
            </Checkbox>
          </Space>
        )}

        {learnStage === "draft" && draft !== null && (
          <Space
            direction="vertical"
            size="middle"
            className={styles.learnBody}
          >
            {draft.needs_confirmation && (
              <Alert
                type="warning"
                showIcon
                message={t("desktop.recording.learn.ambiguities")}
                description={draft.ambiguities.join("; ")}
                action={
                  <Button size="small" onClick={() => setLearnStage("intent")}>
                    {t("desktop.recording.learn.addContext")}
                  </Button>
                }
              />
            )}
            <Typography.Text>
              {t("desktop.recording.learn.draftDescription", {
                used: draft.source_sequences.length,
                ignored: draft.ignored_source_sequences.length,
              })}
            </Typography.Text>
            <Input
              value={draftName}
              maxLength={64}
              aria-label={t("desktop.recording.learn.skillName")}
              onChange={(event) => updateDraftName(event.target.value)}
            />
            <Input.TextArea
              value={draftContent}
              rows={16}
              maxLength={100000}
              aria-label={t("desktop.recording.learn.skillContent")}
              onChange={(event) => setDraftContent(event.target.value)}
            />
          </Space>
        )}
      </Modal>
    </>
  );
}

export default DesktopRecordingControl;
