import {
  Form,
  Input,
  InputNumber,
  Select,
  Switch,
  Button,
  Checkbox,
} from "@agentscope-ai/design";
import { AutoComplete, DatePicker, Tabs, Segmented, Radio } from "antd";
import dayjs, { type Dayjs } from "dayjs";
import { SettingsDrawer as Drawer } from "@/components/interaction/SettingsDrawer";
import InlineHelp from "@/components/InlineHelp";
import { NumberSlider } from "@/components/interaction/NumberSlider";
import { useAutoSave } from "@/hooks/useAutoSave";
import { DurationWheel } from "@/components/interaction/DurationWheel";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import {
  requiresCronLocalProjectMapping,
  requiresCronImportReview,
  type CronDispatchTargetItem,
  type CronJobSpecOutput,
} from "../../../../api/types";
import { DEFAULT_FORM_VALUES } from "./constants";
import { ExecutionModelSelect } from "./ExecutionModelSelect";
import { RequestInput } from "./RequestInput";
import { useTimezoneOptions } from "../../../../hooks/useTimezoneOptions";
import styles from "../index.module.less";

function ScheduleTime({
  value,
  onChange,
}: {
  value?: Dayjs;
  onChange?: (value: Dayjs) => void;
}) {
  return (
    <DurationWheel
      value={value ? value.hour() * 60 + value.minute() : 540}
      onChange={(minutes) =>
        onChange?.(
          (value || dayjs())
            .hour(Math.floor(minutes / 60))
            .minute(minutes % 60)
            .second(0),
        )
      }
    />
  );
}

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
  onSubmit: (values: CronJob) => void | boolean | Promise<void | boolean>;
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
  const [activeTab, setActiveTab] = useState("schedule");
  const [invalidField, setInvalidField] = useState<(string | number)[] | null>(
    null,
  );

  useEffect(() => {
    if (!invalidField) return;
    const frame = requestAnimationFrame(() => {
      form.scrollToField(invalidField, { block: "center", focus: true });
      setInvalidField(null);
    });
    return () => cancelAnimationFrame(frame);
  }, [form, invalidField, activeTab]);
  const selectedChannel = Form.useWatch(["dispatch", "channel"], form);
  const selectedTaskType = Form.useWatch("task_type", form);
  const selectedTargetUserId = Form.useWatch(
    ["dispatch", "target", "user_id"],
    form,
  );

  const isEdit = !!editingJob;
  const { schedule: scheduleSave, flush } = useAutoSave(async () => {
    if (!isEdit) return;
    const values = form.getFieldsValue(true);
    try {
      await form.validateFields();
    } catch {
      return false;
    }
    return onSubmit(values);
  });
  const close = () => {
    void flush().then((saved) => {
      if (saved) onClose();
    });
  };
  const importReviewRequired =
    editingJob !== null && requiresCronImportReview(editingJob);
  const projectMappingRequired =
    importReviewRequired &&
    editingJob !== null &&
    requiresCronLocalProjectMapping(editingJob);

  useEffect(() => {
    if (open) {
      setSaveInboxTouched(false);
      setActiveTab("schedule");
      setInvalidField(null);
      onReloadTargets().catch((error) =>
        console.error("Failed to reload cron dispatch targets", error),
      );
    }
  }, [open, editingJob?.id, onReloadTargets]);

  useEffect(() => {
    if (selectedTaskType === "text") {
      form.setFieldValue(["dispatch", "silent"], false);
    }
  }, [form, selectedTaskType]);

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
    return mergeOptions(targetChannels, selectedChannel);
  }, [selectedChannel, targetChannels]);

  const userOptions = useMemo(() => {
    const options = new Set<string>();
    targetItems.forEach((item) => {
      if (!selectedChannel || item.channel === selectedChannel) {
        options.add(item.user_id);
      }
    });
    return mergeOptions(options, selectedTargetUserId);
  }, [targetItems, selectedChannel, selectedTargetUserId]);

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
    return mergeOptions(options, selectedSessionId);
  }, [form, selectedChannel, selectedTargetUserId, targetItems]);

  return (
    <Drawer
      width={760}
      placement="right"
      title={editingJob ? t("cronJobs.editJob") : t("cronJobs.createJob")}
      open={open}
      onClose={close}
      destroyOnHidden
      footer={
        isEdit ? null : (
          <div className={styles.formActions}>
            <Button onClick={onClose}>{t("common.cancel")}</Button>
            <Button
              type="primary"
              loading={saving}
              onClick={() => form.submit()}
            >
              {t("common.create")}
            </Button>
          </div>
        )
      }
    >
      <Form
        form={form}
        layout="vertical"
        requiredMark={false}
        className={styles.jobEditor}
        onValuesChange={() => {
          if (isEdit) scheduleSave();
        }}
        onFinish={onSubmit}
        onFinishFailed={({ errorFields }) => {
          const field = errorFields[0]?.name;
          if (!field) return;
          const root = field[0];
          if (
            root === "text" ||
            root === "task_type" ||
            (root === "request" && field[1] === "input")
          ) {
            setActiveTab("content");
          } else if (
            root === "dispatch" ||
            root === "save_result_to_inbox" ||
            (root === "request" && field[1] === "model_slot_override")
          ) {
            setActiveTab("delivery");
          } else if (root === "runtime") {
            setActiveTab("runtime");
          } else if (root !== "name" && root !== "request") {
            setActiveTab("schedule");
          }
          setInvalidField(field);
        }}
        initialValues={DEFAULT_FORM_VALUES}
      >
        <Form.Item name="id" hidden>
          <Input />
        </Form.Item>

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
          tooltip={
            importReviewRequired ? t("cronJobs.importReviewBlocked") : undefined
          }
        >
          <Switch disabled={importReviewRequired} />
        </Form.Item>

        {importReviewRequired && (
          <Form.Item
            name={["request", "request_context", "project_dir"]}
            label={t("cronJobs.importReviewProjectDirLabel")}
            tooltip={t("cronJobs.importReviewProjectDirTooltip")}
            extra={t("cronJobs.importReviewProjectDirExtra")}
            rules={
              projectMappingRequired
                ? [
                    {
                      required: true,
                      whitespace: true,
                      message: t("cronJobs.importReviewProjectDirRequired"),
                    },
                  ]
                : undefined
            }
          >
            <Input
              placeholder={t("cronJobs.importReviewProjectDirPlaceholder")}
              autoComplete="off"
            />
          </Form.Item>
        )}

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

        <Tabs
          activeKey={activeTab}
          onChange={(key) => {
            setActiveTab(key);
            void flush();
          }}
          items={[
            {
              key: "schedule",
              label: t("cronJobs.scheduleType"),
              forceRender: true,
              children: (
                <>
                  <Form.Item
                    name="scheduleType"
                    label={t("cronJobs.scheduleType")}
                    rules={[
                      {
                        required: true,
                        message: t("cronJobs.pleaseSelectScheduleType"),
                      },
                    ]}
                  >
                    <Segmented
                      block
                      options={[
                        {
                          value: "cron",
                          label: t("cronJobs.scheduleTypeRecurring"),
                        },
                        {
                          value: "once",
                          label: t("cronJobs.scheduleTypeOnce"),
                        },
                      ]}
                    />
                  </Form.Item>

                  <Form.Item
                    noStyle
                    shouldUpdate={(prev, cur) =>
                      prev.scheduleType !== cur.scheduleType
                    }
                  >
                    {({ getFieldValue }) =>
                      getFieldValue("scheduleType") === "once" ? (
                        <>
                          <Form.Item
                            name="onceRunAt"
                            label={t("cronJobs.onceRunAt")}
                            rules={[
                              {
                                required: true,
                                message: t("cronJobs.pleaseInputRunAt"),
                              },
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
                      const endType =
                        getFieldValue("onceRepeatEndType") || "never";
                      return (
                        <>
                          <Form.Item label={t("cronJobs.repeatFrequency")}>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 8,
                              }}
                            >
                              <span>{t("cronJobs.repeatEveryPrefix")}</span>
                              <Form.Item
                                name="onceRepeatEveryDays"
                                noStyle
                                rules={[
                                  {
                                    required: true,
                                    message: t(
                                      "cronJobs.pleaseInputRepeatEveryDays",
                                    ),
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
                                message: t(
                                  "cronJobs.pleaseSelectRepeatEndType",
                                ),
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
                          <Form.Item label={t("cronJobs.frequency")} required>
                            <Form.Item name="cronType" noStyle>
                              <Radio.Group
                                className={styles.frequencyChoices}
                                optionType="button"
                                buttonStyle="solid"
                                options={[
                                  {
                                    value: "minutes",
                                    label: t("cronJobs.cronTypeMinutes"),
                                  },
                                  {
                                    value: "hourly",
                                    label: t("cronJobs.cronTypeHourly"),
                                  },
                                  {
                                    value: "daily",
                                    label: t("cronJobs.cronTypeDaily"),
                                  },
                                  {
                                    value: "weekly",
                                    label: t("cronJobs.cronTypeWeekly"),
                                  },
                                  {
                                    value: "monthly",
                                    label: t("cronJobs.cronTypeMonthly"),
                                  },
                                  {
                                    value: "custom",
                                    label: t("common.advancedSettings"),
                                  },
                                ]}
                              />
                            </Form.Item>
                          </Form.Item>
                          {cronType === "minutes" && (
                            <Form.Item
                              name="cronInterval"
                              initialValue={5}
                              label={t("cronJobs.intervalMinutes")}
                            >
                              <Select
                                options={[1, 2, 3, 5, 10, 15, 20, 30].map(
                                  (value) => ({
                                    value,
                                    label: t("cronJobs.everyMinutes", {
                                      count: value,
                                    }),
                                  }),
                                )}
                              />
                            </Form.Item>
                          )}
                          {cronType === "monthly" && (
                            <Form.Item
                              name="cronMonthDay"
                              initialValue={1}
                              label={t("cronJobs.monthDay")}
                              extra={t("cronJobs.shortMonthHint")}
                            >
                              <Select
                                options={Array.from(
                                  { length: 31 },
                                  (_, index) => ({
                                    value: index + 1,
                                    label: String(index + 1),
                                  }),
                                )}
                              />
                            </Form.Item>
                          )}
                          {["daily", "weekly", "monthly"].includes(
                            cronType,
                          ) && (
                            <Form.Item
                              name="cronTime"
                              label={t("cronJobs.cronTime")}
                              rules={[{ required: true }]}
                            >
                              <ScheduleTime />
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
                            rules={[
                              {
                                required: true,
                                message: t("cronJobs.selectAtLeastOneDay"),
                              },
                            ]}
                          >
                            <Checkbox.Group
                              options={[
                                {
                                  label: t("cronJobs.cronDayMon"),
                                  value: "mon",
                                },
                                {
                                  label: t("cronJobs.cronDayTue"),
                                  value: "tue",
                                },
                                {
                                  label: t("cronJobs.cronDayWed"),
                                  value: "wed",
                                },
                                {
                                  label: t("cronJobs.cronDayThu"),
                                  value: "thu",
                                },
                                {
                                  label: t("cronJobs.cronDayFri"),
                                  value: "fri",
                                },
                                {
                                  label: t("cronJobs.cronDaySat"),
                                  value: "sat",
                                },
                                {
                                  label: t("cronJobs.cronDaySun"),
                                  value: "sun",
                                },
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
                            label={
                              <span>
                                {t("cronJobs.cronCustomExpression")}{" "}
                                <InlineHelp>
                                  {t("cronJobs.cronExample")}
                                </InlineHelp>
                              </span>
                            }
                            rules={[
                              {
                                required: true,
                                message: t("cronJobs.pleaseInputCron"),
                              },
                            ]}
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
                </>
              ),
            },
            {
              key: "content",
              label: t("cronJobs.taskType"),
              forceRender: true,
              children: (
                <>
                  <Form.Item
                    name="task_type"
                    label={t("cronJobs.taskType")}
                    rules={[
                      {
                        required: true,
                        message: t("cronJobs.pleaseSelectTaskType"),
                      },
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
                    shouldUpdate={(prev, cur) =>
                      prev.task_type !== cur.task_type
                    }
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
                                      message: t(
                                        "cronJobs.pleaseInputMessageContent",
                                      ),
                                    },
                                  ]
                                : []
                            }
                            tooltip={t("cronJobs.textTooltip")}
                          >
                            <Input.TextArea
                              rows={3}
                              placeholder={t(
                                "cronJobs.taskDescriptionPlaceholder",
                              )}
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
                                      new Error(
                                        t("cronJobs.invalidJsonFormat"),
                                      ),
                                    );
                                  }
                                },
                              },
                            ]}
                            tooltip={t("cronJobs.requestInputTooltip")}
                          >
                            <RequestInput />
                          </Form.Item>
                        </>
                      );
                    }}
                  </Form.Item>
                </>
              ),
            },
            {
              key: "delivery",
              label: t("heartbeat.target"),
              forceRender: true,
              children: (
                <>
                  <Form.Item
                    name="save_result_to_inbox"
                    label={t("cronJobs.saveResultToInbox")}
                    valuePropName="checked"
                    tooltip={t("cronJobs.saveResultToInboxTooltip")}
                  >
                    <Switch onChange={() => setSaveInboxTouched(true)} />
                  </Form.Item>
                  <Form.Item
                    name={["dispatch", "type"]}
                    label="DispatchType"
                    hidden
                  >
                    <Input disabled value="channel" />
                  </Form.Item>

                  <Form.Item
                    name={["dispatch", "channel"]}
                    label={t("cronJobs.dispatchChannel")}
                    rules={[
                      {
                        required: true,
                        message: t("cronJobs.pleaseInputChannel"),
                      },
                    ]}
                    tooltip={t("cronJobs.dispatchChannelTooltip")}
                  >
                    <AutoComplete
                      notFoundContent={
                        targetsLoading ? t("common.loading") : null
                      }
                      placeholder="console"
                      options={channelOptions}
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
                    rules={[
                      {
                        required: true,
                        message: t("cronJobs.pleaseInputUserId"),
                      },
                    ]}
                    tooltip={t("cronJobs.dispatchTargetUserIdTooltip")}
                  >
                    <AutoComplete
                      notFoundContent={
                        targetsLoading ? t("common.loading") : null
                      }
                      placeholder="admin"
                      options={userOptions}
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
                      {
                        required: true,
                        message: t("cronJobs.pleaseInputSessionId"),
                      },
                    ]}
                    tooltip={t("cronJobs.dispatchTargetSessionIdTooltip")}
                  >
                    <AutoComplete
                      notFoundContent={
                        targetsLoading ? t("common.loading") : null
                      }
                      placeholder="default"
                      options={sessionOptions}
                      filterOption={(input, option) =>
                        (option?.label?.toString() || "")
                          .toLowerCase()
                          .includes(input.toLowerCase())
                      }
                    />
                  </Form.Item>

                  {selectedTaskType === "agent" && (
                    <Form.Item
                      name={["request", "model_slot_override"]}
                      label={t("cronJobs.executionModel")}
                      tooltip={t("cronJobs.executionModelTooltip")}
                    >
                      <ExecutionModelSelect />
                    </Form.Item>
                  )}

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
                    name={["dispatch", "silent"]}
                    label={t("cronJobs.silentDelivery")}
                    valuePropName="checked"
                    tooltip={t("cronJobs.silentDeliveryTooltip")}
                  >
                    <Switch disabled={selectedTaskType !== "agent"} />
                  </Form.Item>
                </>
              ),
            },
            {
              key: "runtime",
              label: t("common.advancedSettings"),
              forceRender: true,
              children: (
                <>
                  <Form.Item
                    name={["runtime", "share_session"]}
                    label={t("cronJobs.runtimeShareSession")}
                    valuePropName="checked"
                    tooltip={t("cronJobs.shareSessionTooltip")}
                  >
                    <Switch defaultChecked />
                  </Form.Item>

                  <Form.Item
                    name={["runtime", "tool_safety"]}
                    label={t("cronJobs.runtimeToolSafety")}
                    valuePropName="checked"
                    tooltip={t("cronJobs.toolSafetyTooltip")}
                  >
                    <Switch />
                  </Form.Item>

                  <Form.Item
                    name={["runtime", "max_concurrency"]}
                    label={t("cronJobs.runtimeMaxConcurrency")}
                    tooltip={t("cronJobs.maxConcurrencyTooltip")}
                  >
                    <NumberSlider
                      min={1}
                      max={10}
                      label={t("cronJobs.runtimeMaxConcurrency")}
                    />
                  </Form.Item>

                  <Form.Item
                    name={["runtime", "timeout_seconds"]}
                    label={t("cronJobs.runtimeTimeoutSeconds")}
                    tooltip={t("cronJobs.timeoutSecondsTooltip")}
                  >
                    <NumberSlider
                      min={1}
                      max={3600}
                      label={t("cronJobs.runtimeTimeoutSeconds")}
                    />
                  </Form.Item>

                  <Form.Item
                    name={["runtime", "misfire_grace_seconds"]}
                    label={t("cronJobs.runtimeMisfireGraceSeconds")}
                    tooltip={t("cronJobs.misfireGraceSecondsTooltip")}
                  >
                    <NumberSlider
                      min={0}
                      max={3600}
                      label={t("cronJobs.runtimeMisfireGraceSeconds")}
                    />
                  </Form.Item>
                </>
              ),
            },
          ]}
        />
      </Form>
    </Drawer>
  );
}
