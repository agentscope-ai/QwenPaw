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
import { TimePicker } from "antd";
import { useTranslation } from "react-i18next";
import type { FormInstance } from "antd";
import type { CronJobSpecOutput } from "../../../../api/types";
import { DEFAULT_FORM_VALUES } from "./constants";
import { useTimezoneOptions } from "../../../../hooks/useTimezoneOptions";
import styles from "../index.module.less";

type CronJob = CronJobSpecOutput;

interface JobDrawerProps {
  open: boolean;
  editingJob: CronJob | null;
  form: FormInstance<CronJob>;
  saving: boolean;
  onClose: () => void;
  onSubmit: (values: CronJob) => void;
}

export function JobDrawer({
  open,
  editingJob,
  form,
  saving,
  onClose,
  onSubmit,
}: JobDrawerProps) {
  const { t } = useTranslation();
  const timezoneOptions = useTimezoneOptions();

  const isEdit = !!editingJob;

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

        <Form.Item name={["schedule", "type"]} label="ScheduleType" hidden>
          <Input disabled value="cron" />
        </Form.Item>

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

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) => prev.cronType !== cur.cronType}
        >
          {({ getFieldValue }) => {
            const cronType = getFieldValue("cronType");

            if (cronType === "daily" || cronType === "weekly") {
              return (
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
              );
            }
            return null;
          }}
        </Form.Item>

        <Form.Item
          noStyle
          shouldUpdate={(prev, cur) => prev.cronType !== cur.cronType}
        >
          {({ getFieldValue }) => {
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
          shouldUpdate={(prev, cur) => prev.cronType !== cur.cronType}
        >
          {({ getFieldValue }) => {
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
          <Input placeholder="console" />
        </Form.Item>

        <Form.Item
          name={["dispatch", "target", "user_id"]}
          label={t("cronJobs.dispatchTargetUserId")}
          rules={[{ required: true, message: t("cronJobs.pleaseInputUserId") }]}
          tooltip={t("cronJobs.dispatchTargetUserIdTooltip")}
        >
          <Input placeholder="admin" />
        </Form.Item>

        <Form.Item
          name={["dispatch", "target", "session_id"]}
          label={t("cronJobs.dispatchTargetSessionId")}
          rules={[
            { required: true, message: t("cronJobs.pleaseInputSessionId") },
          ]}
          tooltip={t("cronJobs.dispatchTargetSessionIdTooltip")}
        >
          <Input placeholder="default" />
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
