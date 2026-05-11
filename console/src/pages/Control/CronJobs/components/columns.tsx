import { Button, Tooltip, Dropdown } from "@agentscope-ai/design";
import type { ColumnsType } from "antd/es/table";
import type { MenuProps } from "antd";
import type { CronJobSpecOutput } from "../../../../api/types";
import { CopyOutlined, MoreOutlined } from "@ant-design/icons";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { TFunction } from "i18next";
import { parseCron } from "./parseCron";
import styles from "../index.module.less";

type CronJob = CronJobSpecOutput;

interface ColumnHandlers {
  onToggleEnabled: (job: CronJob) => void;
  onExecuteNow: (job: CronJob) => void;
  onEdit: (job: CronJob) => void;
  onDelete: (jobId: string) => void;
  t: TFunction;
}

const createCopyToClipboard = (t: TFunction) => async (text: string) => {
  const { message } = useAppMessage();
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      message.success(t("common.copied"));
    } else {
      const textArea = document.createElement("textarea");
      textArea.value = text;
      textArea.style.position = "fixed";
      textArea.style.left = "-999999px";
      textArea.style.top = "-999999px";
      document.body.appendChild(textArea);
      textArea.focus();
      textArea.select();
      document.execCommand("copy");
      textArea.remove();
      message.success(t("common.copied"));
    }
  } catch (err) {
    console.error("Failed to copy text: ", err);
    message.error(t("common.copyFailed"));
  }
};

export const createColumns = (
  handlers: ColumnHandlers,
): ColumnsType<CronJob> => {
  const copyToClipboard = createCopyToClipboard(handlers.t);

  return [
    {
      title: handlers.t("cronJobs.id"),
      dataIndex: "id",
      key: "id",
      width: 250,
      fixed: "left",
    },
    {
      title: handlers.t("cronJobs.name"),
      dataIndex: "name",
      key: "name",
      width: 250,
    },
    {
      title: handlers.t("cronJobs.enabled"),
      dataIndex: "enabled",
      key: "enabled",
      width: 100,
      render: (enabled: boolean) => (
        <span className={styles.statusIndicator}>
          <span
            className={`${styles.statusDot} ${
              enabled ? styles.enabled : styles.disabled
            }`}
          />
          {enabled
            ? handlers.t("common.enabled")
            : handlers.t("common.disabled")}
        </span>
      ),
    },
    {
      title: handlers.t("cronJobs.scheduleType"),
      dataIndex: ["schedule", "type"],
      key: "schedule_type",
      width: 140,
      render: () => "cron",
    },
    {
      title: handlers.t("cronJobs.scheduleCron"),
      dataIndex: ["schedule", "cron"],
      key: "cron",
      width: 180,
      render: (cron: string) => {
        // Parse cron to friendly text
        const cronParts = parseCron(cron || "0 9 * * *");
        let displayText = "";

        switch (cronParts.type) {
          case "hourly":
            displayText = handlers.t("cronJobs.cronTypeHourly");
            break;
          case "daily":
            displayText = `${handlers.t("cronJobs.cronTypeDaily")} ${String(
              cronParts.hour,
            ).padStart(2, "0")}:${String(cronParts.minute).padStart(2, "0")}`;
            break;
          case "weekly": {
            const dayNames = (cronParts.daysOfWeek || [])
              .map((d) => {
                const dayMap: Record<string, string> = {
                  mon: handlers.t("cronJobs.cronDayMon"),
                  tue: handlers.t("cronJobs.cronDayTue"),
                  wed: handlers.t("cronJobs.cronDayWed"),
                  thu: handlers.t("cronJobs.cronDayThu"),
                  fri: handlers.t("cronJobs.cronDayFri"),
                  sat: handlers.t("cronJobs.cronDaySat"),
                  sun: handlers.t("cronJobs.cronDaySun"),
                };
                return dayMap[d] || d;
              })
              .join(",");
            displayText = `${handlers.t(
              "cronJobs.cronTypeWeekly",
            )} ${dayNames} ${String(cronParts.hour).padStart(2, "0")}:${String(
              cronParts.minute,
            ).padStart(2, "0")}`;
            break;
          }
          case "custom":
            displayText = cron;
            break;
        }

        return (
          <Tooltip
            title={
              <div>
                <div>Cron 表达式：{cron}</div>
                <div
                  className={styles.tableText}
                  style={{ opacity: 0.8, marginTop: 4 }}
                >
                  格式：分钟 小时 日 月 星期
                </div>
              </div>
            }
          >
            <span className={styles.cronText}>{displayText}</span>
          </Tooltip>
        );
      },
    },
    {
      title: handlers.t("cronJobs.scheduleTimezone"),
      dataIndex: ["schedule", "timezone"],
      key: "timezone",
      width: 170,
    },
    {
      title: "TaskType",
      dataIndex: "task_type",
      key: "task_type",
      width: 140,
    },
    {
      title: handlers.t("cronJobs.text"),
      dataIndex: "text",
      key: "text",
      width: 200,
      ellipsis: {
        showTitle: true,
      },
      render: (text: string) => {
        if (!text) return "-";
        return (
          <Tooltip title={text}>
            <span className={styles.tableText}>{text}</span>
          </Tooltip>
        );
      },
    },
    {
      title: handlers.t("cronJobs.requestInput"),
      dataIndex: ["request", "input"],
      key: "request_input",
      width: 350,
      ellipsis: true,
      render: (input: unknown) => {
        if (!input) return "-";

        let displayText: string;
        let fullText: string;

        try {
          fullText = JSON.stringify(input, null, 2);
          displayText = JSON.stringify(input);
        } catch {
          fullText = String(input);
          displayText = fullText;
        }

        if (displayText.length <= 50) {
          return <code className={styles.codeText}>{displayText}</code>;
        }

        const truncatedText =
          displayText.length > 50
            ? displayText.substring(0, 50) + "..."
            : displayText;

        return (
          <Tooltip
            title={
              <div className={styles.tooltipContent}>
                <div className={styles.tooltipJsonContent}>{fullText}</div>
                <Button
                  type="text"
                  icon={<CopyOutlined />}
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    copyToClipboard(fullText);
                  }}
                  className={styles.copyButton}
                />
              </div>
            }
            placement="topLeft"
            overlayInnerStyle={{ maxWidth: 400 }}
          >
            <code className={styles.codeLink}>{truncatedText}</code>
          </Tooltip>
        );
      },
    },
    {
      title: "DispatchType",
      dataIndex: ["dispatch", "type"],
      key: "dispatch_type",
      width: 140,
    },
    {
      title: "DispatchChannel",
      dataIndex: ["dispatch", "channel"],
      key: "channel",
      width: 150,
    },
    {
      title: "DispatchTargetUserID",
      dataIndex: ["dispatch", "target", "user_id"],
      key: "target_user_id",
      width: 190,
    },
    {
      title: "DispatchTargetSessionID",
      dataIndex: ["dispatch", "target", "session_id"],
      key: "target_session_id",
      width: 210,
    },
    {
      title: "DispatchMode",
      dataIndex: ["dispatch", "mode"],
      key: "mode",
      width: 140,
    },
    {
      title: "RuntimeMaxConcurrency",
      dataIndex: ["runtime", "max_concurrency"],
      key: "max_concurrency",
      width: 210,
    },
    {
      title: "RuntimeTimeoutSeconds",
      dataIndex: ["runtime", "timeout_seconds"],
      key: "timeout_seconds",
      width: 210,
    },
    {
      title: "RuntimeMisfireGraceSeconds",
      dataIndex: ["runtime", "misfire_grace_seconds"],
      key: "misfire_grace_seconds",
      width: 240,
    },
    {
      title: handlers.t("cronJobs.action"),
      key: "action",
      width: 240,
      fixed: "right",
      render: (_: unknown, record: CronJob) => {
        const menuItems: MenuProps["items"] = [
          {
            key: "edit",
            label: handlers.t("cronJobs.edit"),
            disabled: record.enabled,
            onClick: () => handlers.onEdit(record),
          },
          {
            key: "delete",
            label: handlers.t("cronJobs.delete"),
            disabled: record.enabled,
            danger: true,
            onClick: () => handlers.onDelete(record.id),
          },
        ];

        return (
          <div className={styles.actionColumn}>
            <Button
              type="link"
              size="small"
              onClick={() => handlers.onToggleEnabled(record)}
            >
              {record.enabled
                ? handlers.t("cronJobs.disable")
                : handlers.t("common.enable")}
            </Button>
            <Button
              type="link"
              size="small"
              onClick={() => handlers.onExecuteNow(record)}
            >
              {handlers.t("cronJobs.executeNow")}
            </Button>
            <Dropdown menu={{ items: menuItems }} placement="bottomRight">
              <Button type="text" size="small" icon={<MoreOutlined />} />
            </Dropdown>
          </div>
        );
      },
    },
  ];
};
