import { NumberSlider } from "@/components/interaction/NumberSlider";
import { useAutoSave } from "@/hooks/useAutoSave";
import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button, Form, Switch } from "@agentscope-ai/design";
import { Alert, TimePicker, Segmented, Spin } from "antd";
import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";
import type { HeartbeatConfig } from "../../../api/types/heartbeat";
import { parseEvery, serializeEvery } from "./parseEvery";
import { DurationWheel } from "@/components/interaction/DurationWheel";
import { PageHeader } from "@/components/PageHeader";
import { HeartbeatInstructions } from "./HeartbeatInstructions";
import styles from "./index.module.less";

dayjs.extend(customParseFormat);

const TIME_FORMAT = "HH:mm";
const HEARTBEAT_MAX_TIMEOUT_SECONDS = 3600;

/** TimePicker that uses "HH:mm" string as value for Form. */
function TimePickerHHmm({
  value,
  onChange,
}: {
  value?: string | null;
  onChange?: (s: string) => void;
}) {
  const strVal =
    typeof value === "string" ? value : Array.isArray(value) ? value[0] : null;
  return (
    <TimePicker
      format={TIME_FORMAT}
      value={strVal ? dayjs(strVal, TIME_FORMAT) : null}
      onChange={(_, str) => {
        const s = typeof str === "string" ? str : str?.[0];
        if (s) onChange?.(s);
      }}
      minuteStep={15}
      needConfirm={false}
      style={{ width: "100%" }}
    />
  );
}

/** Form values: API shape plus flattened fields for interval and time. */
type HeartbeatFormValues = Omit<HeartbeatConfig, "every"> & {
  every?: string;
  intervalMinutes?: number;
  useActiveHours?: boolean;
  activeHoursStart?: string;
  activeHoursEnd?: string;
};

type PendingHeartbeatSave = {
  agentId: string;
  revision: number;
};

const TARGET_OPTIONS = [
  { value: "main", labelKey: "heartbeat.targetMain" },
  { value: "last", labelKey: "heartbeat.targetLast" },
  { value: "inbox", labelKey: "heartbeat.targetInbox" },
];

function HeartbeatPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [form] = Form.useForm<HeartbeatFormValues>();
  const latestRequestRef = useRef(0);
  const requestedAgentRef = useRef<string | null>(null);
  const loadedAgentRef = useRef<string | null>(null);
  const pendingSaveRef = useRef<PendingHeartbeatSave | null>(null);
  const saveRevisionRef = useRef(0);
  const agentId = selectedAgent || "default";
  const intervalMinutes = Form.useWatch("intervalMinutes", form) ?? 360;
  const enabled = Form.useWatch("enabled", form) ?? false;
  const target = Form.useWatch("target", form) ?? "main";

  const fetchConfig = useCallback(async () => {
    const requestId = ++latestRequestRef.current;
    const requestedAgent = selectedAgent || "default";
    requestedAgentRef.current = requestedAgent;
    loadedAgentRef.current = null;
    const isCurrentRequest = () =>
      requestId === latestRequestRef.current &&
      (useAgentStore.getState().selectedAgent || "default") === requestedAgent;

    if (!isCurrentRequest()) return;
    setLoading(true);
    setLoadFailed(false);
    try {
      const data = await api.getHeartbeatConfig(requestedAgent);
      if (!isCurrentRequest()) return;
      const everyParts = parseEvery(data.every ?? "6h");
      form.setFieldsValue({
        enabled: data.enabled ?? false,
        intervalMinutes: everyParts.number * (everyParts.unit === "h" ? 60 : 1),
        target: data.target ?? "main",
        timeoutSeconds: data.timeoutSeconds ?? 300,
        useActiveHours: !!data.activeHours,
        activeHoursStart: data.activeHours?.start ?? "08:00",
        activeHoursEnd: data.activeHours?.end ?? "22:00",
      });
      loadedAgentRef.current = requestedAgent;
    } catch (e) {
      if (!isCurrentRequest()) return;
      console.error("Failed to load heartbeat config:", e);
      setLoadFailed(true);
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  }, [form, selectedAgent]);

  useEffect(() => {
    void fetchConfig();
  }, [fetchConfig]);

  const onFinish = async (values: HeartbeatFormValues, saveAgentId: string) => {
    const totalMinutes = values.intervalMinutes ?? 360;
    const every = serializeEvery({
      number: totalMinutes % 60 === 0 ? totalMinutes / 60 : totalMinutes,
      unit: totalMinutes % 60 === 0 ? "h" : "m",
    });
    const body: HeartbeatConfig = {
      enabled: values.enabled ?? false,
      every,
      target: values.target ?? "main",
      timeoutSeconds: values.timeoutSeconds ?? 300,
      activeHours:
        values.useActiveHours &&
        values.activeHoursStart &&
        values.activeHoursEnd
          ? {
              start: values.activeHoursStart,
              end: values.activeHoursEnd,
            }
          : undefined,
    };
    await api.updateHeartbeatConfig(body, saveAgentId);
  };
  const isScheduleOwner = (ownerAgentId: string) =>
    loadedAgentRef.current === ownerAgentId &&
    (useAgentStore.getState().selectedAgent || "default") === ownerAgentId;
  const { schedule, flush } = useAutoSave(async () => {
    const pendingSave = pendingSaveRef.current;
    const saveIsCurrent = () =>
      pendingSaveRef.current?.agentId === pendingSave?.agentId &&
      pendingSaveRef.current?.revision === pendingSave?.revision;
    if (!pendingSave || !isScheduleOwner(pendingSave.agentId)) {
      if (saveIsCurrent()) {
        pendingSaveRef.current = null;
      }
      return true;
    }
    const values = form.getFieldsValue(true);
    try {
      await form.validateFields();
    } catch {
      return false;
    }
    if (!isScheduleOwner(pendingSave.agentId)) {
      if (saveIsCurrent()) {
        pendingSaveRef.current = null;
      }
      return true;
    }
    await onFinish(values, pendingSave.agentId);
    if (saveIsCurrent()) {
      pendingSaveRef.current = null;
    }
  });
  const scheduleCurrentAgent = () => {
    const currentAgent = useAgentStore.getState().selectedAgent || "default";
    if (!isScheduleOwner(currentAgent)) return;
    pendingSaveRef.current = {
      agentId: currentAgent,
      revision: ++saveRevisionRef.current,
    };
    schedule();
  };
  const requestMatchesAgent = requestedAgentRef.current === agentId;
  const scheduleLoading =
    loading ||
    !requestMatchesAgent ||
    (!loadFailed && loadedAgentRef.current !== agentId);
  const scheduleReady =
    !scheduleLoading && !loadFailed && loadedAgentRef.current === agentId;

  return (
    <div className={styles.heartbeatPage}>
      <PageHeader items={[{ title: t("heartbeat.title") }]} />
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        onValuesChange={scheduleCurrentAgent}
        onFinish={() => {
          if (scheduleReady) void flush();
        }}
        className={styles.schedule}
      >
        {scheduleLoading ? (
          <div className={styles.loading}>
            <Spin aria-label={t("common.loading")} />
          </div>
        ) : loadFailed ? (
          <div className={styles.loadError}>
            <Alert
              type="error"
              showIcon
              message={t("heartbeat.loadFailed")}
              action={
                <Button type="primary" onClick={() => void fetchConfig()}>
                  {t("common.retry")}
                </Button>
              }
            />
          </div>
        ) : (
          <InteractiveCard
            tilt={enabled ? 2 : 0}
            className={styles.pulseCard}
            data-disabled={!enabled}
          >
            <div className={styles.pulseHeader}>
              <h2 id="heartbeat-interval-label">{t("heartbeat.every")}</h2>
              <Form.Item name="enabled" valuePropName="checked" noStyle>
                <Switch aria-label={t("heartbeat.enabled")} />
              </Form.Item>
            </div>
            <Form.Item
              aria-labelledby="heartbeat-interval-label"
              name="intervalMinutes"
              rules={[
                {
                  required: true,
                  type: "number",
                  min: 1,
                  message: t("heartbeat.intervalRange"),
                },
              ]}
            >
              <DurationWheel
                disabled={!enabled}
                maxHours={Math.max(23, Math.floor(intervalMinutes / 60))}
              />
            </Form.Item>
            <div className={styles.presets}>
              {[1, 3, 6, 12].map((value) => (
                <button
                  key={value}
                  type="button"
                  data-press
                  disabled={!enabled}
                  aria-pressed={intervalMinutes === value * 60}
                  onClick={() => {
                    form.setFieldsValue({ intervalMinutes: value * 60 });
                    scheduleCurrentAgent();
                  }}
                >
                  {value} {t("heartbeat.unitHours")}
                </button>
              ))}
            </div>
          </InteractiveCard>
        )}
        <HeartbeatInstructions key={agentId} agentId={agentId} />
        {scheduleReady ? (
          <section className={styles.delivery}>
            <Form.Item name="target" hidden>
              <input />
            </Form.Item>
            <div className={styles.settingRow}>
              <h2>{t("heartbeat.target")}</h2>
              <Segmented
                aria-label={t("heartbeat.target")}
                value={target}
                options={TARGET_OPTIONS.map((option) => ({
                  value: option.value,
                  label: t(option.labelKey),
                }))}
                onChange={(value) => {
                  form.setFieldValue("target", value);
                  scheduleCurrentAgent();
                }}
              />
            </div>
            <div className={styles.divider} />
            <div className={styles.hoursHeader}>
              <h2>{t("heartbeat.activeHours")}</h2>
              <Form.Item name="useActiveHours" valuePropName="checked" noStyle>
                <Switch aria-label={t("heartbeat.activeHours")} />
              </Form.Item>
            </div>
            <Form.Item
              noStyle
              shouldUpdate={(prev, cur) =>
                prev.useActiveHours !== cur.useActiveHours
              }
            >
              {({ getFieldValue }) =>
                getFieldValue("useActiveHours") ? (
                  <div className={styles.activeHoursRow}>
                    <Form.Item
                      name="activeHoursStart"
                      label={t("heartbeat.activeStart")}
                    >
                      <TimePickerHHmm />
                    </Form.Item>
                    <Form.Item
                      name="activeHoursEnd"
                      label={t("heartbeat.activeEnd")}
                    >
                      <TimePickerHHmm />
                    </Form.Item>
                  </div>
                ) : null
              }
            </Form.Item>
            <div className={styles.divider} />
            <div className={styles.timeoutRow}>
              <h2>{t("heartbeat.timeoutSeconds")}</h2>
              <Form.Item
                name="timeoutSeconds"
                rules={[
                  { required: true, message: t("heartbeat.timeoutRequired") },
                  {
                    type: "number",
                    min: 1,
                    message: t("heartbeat.timeoutMin"),
                  },
                  {
                    type: "number",
                    max: HEARTBEAT_MAX_TIMEOUT_SECONDS,
                    message: t("heartbeat.timeoutMax"),
                  },
                ]}
              >
                <NumberSlider
                  min={1}
                  max={HEARTBEAT_MAX_TIMEOUT_SECONDS}
                  label={t("heartbeat.timeoutSeconds")}
                />
              </Form.Item>
            </div>
          </section>
        ) : null}
      </Form>
    </div>
  );
}

export default HeartbeatPage;
