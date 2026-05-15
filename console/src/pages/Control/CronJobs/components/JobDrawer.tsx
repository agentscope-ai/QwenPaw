import {
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Button,
  Checkbox,
} from "@agentscope-ai/design";
import { DatePicker, TimePicker } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import type {
  CronDispatchTargetItem,
  CronJobSpecOutput,
} from "../../../../api/types";
import { DEFAULT_FORM_VALUES } from "./constants";
import { useTimezoneOptions } from "../../../../hooks/useTimezoneOptions";
import styles from "../index.module.less";

type CronJob = CronJobSpecOutput;
type SelectOption = { value: string; label: string };

interface JobDrawerProps {
  open: boolean;
  editingJob: CronJob | null;
  form: FormInstance<CronJob>;
  saving: boolean;
  targetItems: CronDispatchTargetItem[];
  targetChannels: string[];
  targetsLoading: boolean;
  onReloadTargets: () => Promise<void>;
  onClose: () => void;
  onSubmit: (values: CronJob) => void;
}

export function JobDrawer({
  open,
  editingJob,
  form,
  saving,
  targetItems,
  targetChannels,
  targetsLoading,
  onReloadTargets,
  onClose,
  onSubmit,
}: JobDrawerProps) {
  const { t } = useTranslation();
  const timezoneOptions = useTimezoneOptions();
  const [saveInboxTouched, setSaveInboxTouched] = useState(false);
  const [channelSearch, setChannelSearch] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [sessionSearch, setSessionSearch] = useState("");
  const selectedChannel = Form.useWatch(["dispatch", "channel"], form);
  const selectedTargetUserId = Form.useWatch(
    ["dispatch", "target", "user_id"],
    form,
  );

  const isEdit = !!editingJob;

  useEffect(() => {
    if (open) {
      setSaveInboxTouched(false);
      setChannelSearch("");
      setUserSearch("");
      setSessionSearch("");
      onReloadTargets().catch((error) =>
        console.error("Failed to reload cron dispatch targets", error),
      );
    }
  }, [open, editingJob?.id, onReloadTargets]);

  const mergeOptions = (
    values: Iterable<string>,
    selectedValue?: string,
    searchValue?: string,
  ): SelectOption[] => {
    const merged = new Set<string>();
    Array.from(values).forEach((value) => {
      if (value?.trim()) {
        merged.add(value.trim());
      }
    });
    if (selectedValue?.trim()) {
      merged.add(selectedValue.trim());
    }
    if (searchValue?.trim()) {
      merged.add(searchValue.trim());
    }
    return [...merged].sort().map((value) => ({ value, label: value }));
  };

  const channelOptions = useMemo(() => {
    return mergeOptions(targetChannels, selectedChannel, channelSearch);
  }, [channelSearch, selectedChannel, targetChannels]);

  const userOptions = useMemo(() => {
    const options = new Set<string>();
    targetItems.forEach((item) => {
      if (!selectedChannel || item.channel === selectedChannel) {
        options.add(item.user_id);
      }
    });
    return mergeOptions(options, selectedTargetUserId, userSearch);
  }, [targetItems, selectedChannel, selectedTargetUserId, userSearch]);

  const sessionOptions = useMemo(() => {
    const options = new Set<string>();
    targetItems.forEach((item) => {
      if (
        (!selectedChannel || item.channel === selectedChannel) &&
        (!selectedTargetUserId || item.user_id === selectedTargetUserId)
      ) {
        options.add(item.session_id);
      }
    });
    const selectedSessionId: string | undefined = form.getFieldValue([
      "dispatch",
      "target",
      "session_id",
    ]);
    return mergeOptions(options, selectedSessionId, sessionSearch);
  }, [form, selectedChannel, selectedTargetUserId, sessionSearch, targetItems]);

  return (
    <Drawer
      width={600}
      placement="right"
      title={editingJob ? t("cronJobs.editJob") : t("cronJobs.createJob")}
      open={open}
      onClose={onClose}
      destroyOnClose
      footer={
        <div className={styles.formActions}>
          <Button onClick={onClose}>{t("common.cancel")}</Button>
          <Button type="primary" loading={saving} onClick={() => form.submit()}>
            {t("common.save")}
          </Button>
        </div>
      }
    >
      <Form
        form={form}
        layout="vertical"
        onFinish={onSubmit}
        initialValues={DEFAULT_FORM_VALUES}
      >
        {isEdit && (
          <Form.Item
            name="id"
            label={t("cronJobs.id")}
            tooltip={t("cronJobs.idTooltip")}
          >
            <Input disabled placeholder={t("cronJobs.jobIdPlaceholder")} />
          </Form.Item>
        )}

        <Form.Item
          name="name"
          label={t("cronJobs.name")}
          rules={[{ required: true, message: t("cronJobs.pleaseInputName") }]}
          tooltip={t("cronJobs.nameTooltip")}
        >
          <Input placeholder={t("cronJobs.jobNamePlaceholder")} />
        </Form.Item>

        <Form.Item
          name="enabled"
          label={t("cronJobs.enabled")}
          valuePropName="checked"
        >
          <Switch />
        </Form.Item>

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) =>
            prev.task_type !== cur.task_type ||
            prev.scheduleType !== cur.scheduleType ||
            prev.save_result_to_inbox !== cur.save_result_to_inbox
          }
        >
          {({ getFieldValue, setFieldValue }) => {
            if (!isEdit && !saveInboxTouched) {
              const taskType = getFieldValue("task_type");
              const scheduleType = getFieldValue("scheduleType");
              const expectedDefault = !(
                taskType === "text" && scheduleType === "cron"
              );
              if (getFieldValue("save_result_to_inbox") !== expectedDefault) {
                setFieldValue("save_result_to_inbox", expectedDefault);
              }
            }
            return null;
          }}
        </Form.Item>

        <Form.Item
          name="save_result_to_inbox"
          label={t("cronJobs.saveResultToInbox")}
          valuePropName="checked"
          tooltip={t("cronJobs.saveResultToInboxTooltip")}
        >
          <Switch onChange={() => setSaveInboxTouched(true)} />
        </Form.Item>

        <Form.Item
          name="scheduleType"
          label={t("cronJobs.scheduleType")}
          rules={[
            { required: true, message: t("cronJobs.pleaseSelectScheduleType") },
          ]}
        >
          <Select>
            <Select.Option value="cron">
              {t("cronJobs.scheduleTypeRecurring")}
            </Select.Option>
            <Select.Option value="once">
              {t("cronJobs.scheduleTypeOnce")}
            </Select.Option>
          </Select>
        </Form.Item>

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) => prev.scheduleType !== cur.scheduleType}
        >
          {({ getFieldValue }) =>
            getFieldValue("scheduleType") === "once" ? (
              <>
                <Form.Item
                  name="onceRunAt"
                  label={t("cronJobs.onceRunAt")}
                  rules={[
                    { required: true, message: t("cronJobs.pleaseInputRunAt") },
                  ]}
                >
                  <DatePicker
                    showTime={{ format: "HH:mm" }}
                    format="YYYY-MM-DD HH:mm"
                    style={{ width: "100%" }}
                  />
                </Form.Item>
                <Form.Item
                  name="onceRepeatEnabled"
                  label={t("cronJobs.repeatEnabled")}
                  valuePropName="checked"
                  tooltip={t("cronJobs.repeatEnabledTooltip")}
                >
                  <Switch />
                </Form.Item>
              </>
            ) : null
          }
        </Form.Item>

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) =>
            prev.scheduleType !== cur.scheduleType ||
            prev.onceRepeatEnabled !== cur.onceRepeatEnabled ||
            prev.onceRepeatEndType !== cur.onceRepeatEndType
          }
        >
          {({ getFieldValue }) => {
            if (
              getFieldValue("scheduleType") !== "once" ||
              !getFieldValue("onceRepeatEnabled")
            ) {
              return null;
            }
            const endType = getFieldValue("onceRepeatEndType") || "never";
            return (
              <>
                <Form.Item label={t("cronJobs.repeatFrequency")}>
                  <div
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <span>{t("cronJobs.repeatEveryPrefix")}</span>
                    <Form.Item
                      name="onceRepeatEveryDays"
                      noStyle
                      rules={[
                        {
                          required: true,
                          message: t("cronJobs.pleaseInputRepeatEveryDays"),
                        },
                      ]}
                    >
                      <InputNumber min={1} style={{ width: 120 }} />
                    </Form.Item>
                    <span>{t("cronJobs.repeatEverySuffix")}</span>
                  </div>
                </Form.Item>
                <Form.Item
                  name="onceRepeatEndType"
                  label={t("cronJobs.repeatEndType")}
                  rules={[
                    {
                      required: true,
                      message: t("cronJobs.pleaseSelectRepeatEndType"),
                    },
                  ]}
                >
                  <Select>
                    <Select.Option value="never">
                      {t("cronJobs.repeatEndNever")}
                    </Select.Option>
                    <Select.Option value="until">
                      {t("cronJobs.repeatEndUntil")}
                    </Select.Option>
                    <Select.Option value="count">
                      {t("cronJobs.repeatEndCount")}
                    </Select.Option>
                  </Select>
                </Form.Item>
                {endType === "until" && (
                  <Form.Item
                    name="onceRepeatUntil"
                    label={t("cronJobs.repeatUntil")}
                    rules={[
                      {
                        required: true,
                        message: t("cronJobs.pleaseInputRepeatUntil"),
                      },
                    ]}
                  >
                    <DatePicker
                      showTime={{ format: "HH:mm" }}
                      format="YYYY-MM-DD HH:mm"
                      style={{ width: "100%" }}
                    />
                  </Form.Item>
                )}
                {endType === "count" && (
                  <Form.Item
                    name="onceRepeatCount"
                    label={t("cronJobs.repeatCount")}
                    rules={[
                      {
                        required: true,
                        message: t("cronJobs.pleaseInputRepeatCount"),
                      },
                    ]}
                  >
                    <InputNumber min={1} style={{ width: "100%" }} />
                  </Form.Item>
                )}
              </>
            );
          }}
        </Form.Item>

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) =>
            prev.scheduleType !== cur.scheduleType ||
            prev.cronType !== cur.cronType
          }
        >
          {({ getFieldValue }) => {
            if (getFieldValue("scheduleType") !== "cron") {
              return null;
            }
            const cronType = getFieldValue("cronType");
            return (
              <>
                <Form.Item
                  label={t("cronJobs.scheduleCronLabel")}
                  required
                  tooltip={t("cronJobs.cronTooltip")}
                >
                  <Form.Item name="cronType" noStyle>
                    <Select>
                      <Select.Option value="hourly">
                        {t("cronJobs.cronTypeHourly")}
                      </Select.Option>
                      <Select.Option value="daily">
                        {t("cronJobs.cronTypeDaily")}
                      </Select.Option>
                      <Select.Option value="weekly">
                        {t("cronJobs.cronTypeWeekly")}
                      </Select.Option>
                      <Select.Option value="custom">
                        {t("cronJobs.cronTypeCustom")}
                      </Select.Option>
                    </Select>
                  </Form.Item>
                </Form.Item>
                {(cronType === "daily" || cronType === "weekly") && (
                  <Form.Item
                    name="cronTime"
                    label={t("cronJobs.cronTime")}
                    rules={[{ required: true }]}
                  >
                    <TimePicker
                      format="HH:mm"
                      minuteStep={15}
                      needConfirm={false}
                      style={{ width: "100%" }}
                    />
                  </Form.Item>
                )}
              </>
            );
          }}
        </Form.Item>

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) =>
            prev.scheduleType !== cur.scheduleType ||
            prev.cronType !== cur.cronType
          }
        >
          {({ getFieldValue }) => {
            if (getFieldValue("scheduleType") !== "cron") {
              return null;
            }
            const cronType = getFieldValue("cronType");
            if (cronType === "weekly") {
              return (
                <Form.Item
                  name="cronDaysOfWeek"
                  label={t("cronJobs.cronDaysOfWeek")}
                  rules={[{ required: true, message: "请选择至少一天" }]}
                >
                  <Checkbox.Group
                    options={[
                      { label: t("cronJobs.cronDayMon"), value: "mon" },
                      { label: t("cronJobs.cronDayTue"), value: "tue" },
                      { label: t("cronJobs.cronDayWed"), value: "wed" },
                      { label: t("cronJobs.cronDayThu"), value: "thu" },
                      { label: t("cronJobs.cronDayFri"), value: "fri" },
                      { label: t("cronJobs.cronDaySat"), value: "sat" },
                      { label: t("cronJobs.cronDaySun"), value: "sun" },
                    ]}
                  />
                </Form.Item>
              );
            }
            return null;
          }}
        </Form.Item>

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) =>
            prev.scheduleType !== cur.scheduleType ||
            prev.cronType !== cur.cronType
          }
        >
          {({ getFieldValue }) => {
            if (getFieldValue("scheduleType") !== "cron") {
              return null;
            }
            const cronType = getFieldValue("cronType");

            if (cronType === "custom") {
              return (
                <Form.Item
                  name="cronCustom"
                  label={t("cronJobs.cronCustomExpression")}
                  rules={[
                    { required: true, message: t("cronJobs.pleaseInputCron") },
                  ]}
                  extra={
                    <div className={styles.formExtraText}>
                      <div style={{ marginBottom: 4 }}>
                        {t("cronJobs.cronExample")}
                      </div>
                      <div>
                        {t("cronJobs.cronHelper")}{" "}
                        <a
                          href="https://crontab.guru/"
                          target="_blank"
                          rel="noopener noreferrer"
                          className={styles.formHelperLink}
                        >
                          {t("cronJobs.cronHelperLink")} →
                        </a>
                      </div>
                    </div>
                  }
                >
                  <Input placeholder="0 9 * * *" />
                </Form.Item>
              );
            }
            return null;
          }}
        </Form.Item>

        <Form.Item name={["schedule", "cron"]} hidden>
          <Input />
        </Form.Item>

        <Form.Item
          name={["schedule", "timezone"]}
          label={t("cronJobs.scheduleTimezone")}
          tooltip={t("cronJobs.timezoneTooltip")}
        >
          <Select
            showSearch
            placeholder={t("cronJobs.selectTimezone")}
            filterOption={(input, option) =>
              (option?.label?.toString() || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
            options={timezoneOptions}
          />
        </Form.Item>

        <Form.Item
          name="task_type"
          label={t("cronJobs.taskType")}
          rules={[
            { required: true, message: t("cronJobs.pleaseSelectTaskType") },
          ]}
          tooltip={t("cronJobs.taskTypeTooltip")}
        >
          <Select>
            <Select.Option value="text">text</Select.Option>
            <Select.Option value="agent">agent</Select.Option>
          </Select>
        </Form.Item>

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) => prev.task_type !== cur.task_type}
        >
          {({ getFieldValue }) => {
            const taskType = getFieldValue("task_type");
            const textRequired = taskType === "text";
            const agentRequired = taskType === "agent";

            return (
              <>
                <Form.Item
                  name="text"
                  label={t("cronJobs.text")}
                  required={textRequired}
                  rules={
                    textRequired
                      ? [
                          {
                            required: true,
                            message: t("cronJobs.pleaseInputMessageContent"),
                          },
                        ]
                      : []
                  }
                  tooltip={t("cronJobs.textTooltip")}
                >
                  <Input.TextArea
                    rows={3}
                    placeholder={t("cronJobs.taskDescriptionPlaceholder")}
                  />
                </Form.Item>

                <Form.Item
                  name={["request", "input"]}
                  label={t("cronJobs.requestInput")}
                  required={agentRequired}
                  rules={[
                    ...(agentRequired
                      ? [
                          {
                            required: true,
                            message: t("cronJobs.pleaseInputRequest"),
                          },
                        ]
                      : []),
                    {
                      validator: (_, value) => {
                        if (!value) return Promise.resolve();
                        try {
                          JSON.parse(value);
                          return Promise.resolve();
                        } catch {
                          return Promise.reject(
                            new Error(t("cronJobs.invalidJsonFormat")),
                          );
                        }
                      },
                    },
                  ]}
                  tooltip={t("cronJobs.requestInputTooltip")}
                  extra={
                    <span className={styles.formExtraText}>
                      {t("cronJobs.requestInputExample")}
                    </span>
                  }
                >
                  <Input.TextArea
                    rows={6}
                    placeholder='[{"role":"user","content":[{"text":"Hello","type":"text"}]}]'
                    style={{ fontFamily: "monospace", fontSize: 12 }}
                  />
                </Form.Item>
              </>
            );
          }}
        </Form.Item>

        <Form.Item name={["dispatch", "type"]} label="DispatchType" hidden>
          <Input disabled value="channel" />
        </Form.Item>

        <Form.Item
          name={["dispatch", "channel"]}
          label={t("cronJobs.dispatchChannel")}
          rules={[
            { required: true, message: t("cronJobs.pleaseInputChannel") },
          ]}
          tooltip={t("cronJobs.dispatchChannelTooltip")}
        >
          <Select
            showSearch
            loading={targetsLoading}
            placeholder="console"
            options={channelOptions}
            onSearch={setChannelSearch}
            onBlur={() => setChannelSearch("")}
            notFoundContent="输入自定义值后按 Enter"
            filterOption={(input, option) =>
              (option?.label?.toString() || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <Form.Item
          name={["dispatch", "target", "user_id"]}
          label={t("cronJobs.dispatchTargetUserId")}
          rules={[{ required: true, message: t("cronJobs.pleaseInputUserId") }]}
          tooltip={t("cronJobs.dispatchTargetUserIdTooltip")}
        >
          <Select
            showSearch
            loading={targetsLoading}
            placeholder="admin"
            options={userOptions}
            onSearch={setUserSearch}
            onBlur={() => setUserSearch("")}
            notFoundContent="输入自定义值后按 Enter"
            filterOption={(input, option) =>
              (option?.label?.toString() || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <Form.Item
          name={["dispatch", "target", "session_id"]}
          label={t("cronJobs.dispatchTargetSessionId")}
          rules={[
            { required: true, message: t("cronJobs.pleaseInputSessionId") },
          ]}
          tooltip={t("cronJobs.dispatchTargetSessionIdTooltip")}
        >
          <Select
            showSearch
            loading={targetsLoading}
            placeholder="default"
            options={sessionOptions}
            onSearch={setSessionSearch}
            onBlur={() => setSessionSearch("")}
            notFoundContent="输入自定义值后按 Enter"
            filterOption={(input, option) =>
              (option?.label?.toString() || "")
                .toLowerCase()
                .includes(input.toLowerCase())
            }
          />
        </Form.Item>

        <Form.Item
          name={["dispatch", "mode"]}
          label={t("cronJobs.dispatchMode")}
          tooltip={t("cronJobs.dispatchModeTooltip")}
        >
          <Select>
            <Select.Option value="stream">stream</Select.Option>
            <Select.Option value="final">final</Select.Option>
          </Select>
        </Form.Item>

        <Form.Item
          name={["runtime", "share_session"]}
          label={t("cronJobs.runtimeShareSession")}
          valuePropName="checked"
          tooltip={t("cronJobs.shareSessionTooltip")}
        >
          <Switch defaultChecked />
        </Form.Item>

        <Form.Item
          name={["runtime", "max_concurrency"]}
          label={t("cronJobs.runtimeMaxConcurrency")}
          tooltip={t("cronJobs.maxConcurrencyTooltip")}
        >
          <InputNumber min={1} style={{ width: "100%" }} placeholder="1" />
        </Form.Item>

        <Form.Item
          name={["runtime", "timeout_seconds"]}
          label={t("cronJobs.runtimeTimeoutSeconds")}
          tooltip={t("cronJobs.timeoutSecondsTooltip")}
        >
          <InputNumber min={1} style={{ width: "100%" }} placeholder="300" />
        </Form.Item>

        <Form.Item
          name={["runtime", "misfire_grace_seconds"]}
          label={t("cronJobs.runtimeMisfireGraceSeconds")}
          tooltip={t("cronJobs.misfireGraceSecondsTooltip")}
        >
          <InputNumber min={0} style={{ width: "100%" }} placeholder="60" />
        </Form.Item>
      </Form>
    </Drawer>
  );
}
