import { NumberSlider } from "@/components/interaction/NumberSlider";
import { useAutoSave } from "@/hooks/useAutoSave";
import { Activity, Moon, Inbox, MessagesSquare } from "lucide-react";
import { InteractiveCard } from "@/components/interaction/InteractiveCard";
import { PreferenceChoice } from "@/components/interaction/PreferenceChoice";
import { RunningGlow } from "@/components/interaction/RunningGlow";
import { useEffect, useState } from "react";
import { Form, Switch } from "@agentscope-ai/design";
import { useAppMessage } from "../../../hooks/useAppMessage";
import { TimePicker, Collapse } from "antd";
import dayjs from "dayjs";
import customParseFormat from "dayjs/plugin/customParseFormat";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { useAgentStore } from "../../../stores/agentStore";
import type { HeartbeatConfig } from "../../../api/types/heartbeat";
import { parseEvery, serializeEvery } from "./parseEvery";
import { DurationWheel } from "./DurationWheel";
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

const TARGET_OPTIONS = [
  { value: "main", labelKey: "heartbeat.targetMain" },
  { value: "last", labelKey: "heartbeat.targetLast" },
  { value: "inbox", labelKey: "heartbeat.targetInbox" },
];

function HeartbeatPage() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [loading, setLoading] = useState(true);
  const [form] = Form.useForm<HeartbeatFormValues>();
  const { message } = useAppMessage();
  const intervalMinutes = Form.useWatch("intervalMinutes", form) ?? 360;
  const enabled = Form.useWatch("enabled", form) ?? false;
  const target = Form.useWatch("target", form) ?? "main";

  const fetchConfig = async () => {
    setLoading(true);
    try {
      const data = await api.getHeartbeatConfig();
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
    } catch (e) {
      console.error("Failed to load heartbeat config:", e);
      message.error(t("heartbeat.loadFailed"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchConfig();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedAgent]);

  const onFinish = async (values: HeartbeatFormValues) => {
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
    await api.updateHeartbeatConfig(body, selectedAgent || "default");
  };
  const { schedule, flush } = useAutoSave(async () => {
    const values = form.getFieldsValue(true);
    try {
      await form.validateFields();
    } catch {
      return false;
    }
    await onFinish(values);
  });

  if (loading) {
    return (
      <div className={styles.heartbeatPage}>
        <PageHeader
          items={[{ title: t("nav.control") }, { title: t("heartbeat.title") }]}
        />
        <span className={styles.description}>{t("common.loading")}</span>
      </div>
    );
  }

  return (
    <div className={styles.heartbeatPage}>
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("heartbeat.title") }]}
      />
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        onValuesChange={schedule}
        onFinish={() => void flush()}
        className={styles.schedule}
      >
        <InteractiveCard tilt={2} className={styles.pulseCard}>
          <div className={styles.pulseHeader}>
            <span className={styles.pulseIcon}>
              <Activity size={22} />
            </span>
            <div>
              <h2>{t("heartbeat.title")}</h2>
              <span>{t(enabled ? "common.enabled" : "common.disabled")}</span>
            </div>
            <Form.Item name="enabled" valuePropName="checked" noStyle>
              <Switch aria-label={t("heartbeat.enabled")} />
            </Form.Item>
          </div>
          <Form.Item
            label={t("heartbeat.every")}
            name="intervalMinutes"
            rules={[
              {
                required: true,
                type: "number",
                min: 1,
                max: 1439,
                message: t("heartbeat.intervalRange"),
              },
            ]}
          >
            <DurationWheel />
          </Form.Item>
          <div className={styles.presets}>
            {[1, 3, 6, 12].map((value) => (
              <button
                key={value}
                type="button"
                data-press
                aria-pressed={intervalMinutes === value * 60}
                onClick={() => {
                  form.setFieldsValue({ intervalMinutes: value * 60 });
                  schedule();
                }}
              >
                {value} {t("heartbeat.unitHours")}
              </button>
            ))}
          </div>
          <RunningGlow active={enabled} />
        </InteractiveCard>
        <HeartbeatInstructions
          key={selectedAgent || "default"}
          agentId={selectedAgent || "default"}
        />
        <section className={styles.delivery}>
          <h2>{t("heartbeat.target")}</h2>
          <Form.Item name="target" hidden>
            <input />
          </Form.Item>
          <div className={styles.targetChoices}>
            {TARGET_OPTIONS.map((option, index) => (
              <PreferenceChoice
                key={option.value}
                selected={target === option.value}
                label={t(option.labelKey)}
                icon={
                  index === 0 ? (
                    <Moon size={20} />
                  ) : index === 1 ? (
                    <MessagesSquare size={20} />
                  ) : (
                    <Inbox size={20} />
                  )
                }
                onSelect={() => {
                  form.setFieldValue("target", option.value);
                  schedule();
                }}
              />
            ))}
          </div>
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

          <Collapse
            ghost
            items={[
              {
                key: "timeout",
                label: t("heartbeat.timeoutSeconds"),
                forceRender: true,
                children: (
                  <>
                    {" "}
                    <Form.Item
                      name="timeoutSeconds"
                      label={t("heartbeat.timeoutSeconds")}
                      rules={[
                        {
                          required: true,
                          message: t("heartbeat.timeoutRequired"),
                        },
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
                  </>
                ),
              },
            ]}
          />
        </section>
      </Form>
    </div>
  );
}

export default HeartbeatPage;
