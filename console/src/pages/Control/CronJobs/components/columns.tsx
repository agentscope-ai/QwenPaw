import { Button, Tooltip, Dropdown } from "@agentscope-ai/design";
import type { ColumnsType } from "antd/es/table";
import type { MenuProps } from "antd";
import type { CronJobSpecOutput } from "../../../../api/types";
import { CopyOutlined, MoreOutlined } from "@ant-design/icons";
import { message } from "antd";
import { TFunction } from "i18next";
import { parseCron } from "./parseCron";

type CronJob = CronJobSpecOutput;

interface ColumnHandlers {
  onToggleEnabled: (job: CronJob) => void;
  onExecuteNow: (job: CronJob) => void;
  onEdit: (job: CronJob) => void;
  onDelete: (jobId: string) => void;
  t: TFunction;
}

const createCopyToClipboard = (t: TFunction) => async (text: string) => {
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
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            fontSize: 12,
          }}
        >
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              backgroundColor: enabled ? "#52c41a" : "#d9d9d9",
            }}
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
                const dayMap: Record<number, string> = {
                  0: handlers.t("cronJobs.cronDaySun"),
                  1: handlers.t("cronJobs.cronDayMon"),
                  2: handlers.t("cronJobs.cronDayTue"),
                  3: handlers.t("cronJobs.cronDayWed"),
                  4: handlers.t("cronJobs.cronDayThu"),
                  5: handlers.t("cronJobs.cronDayFri"),
                  6: handlers.t("cronJobs.cronDaySat"),
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
                <div>Cron 表达式: {cron}</div>
                <div style={{ fontSize: 11, opacity: 0.8, marginTop: 4 }}>
                  格式: 分钟 小时 日 月 星期
                </div>
              </div>
            }
          >
            <span style={{ fontSize: 12, cursor: "help" }}>{displayText}</span>
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
      title: handlers.t("cronJobs.taskText"),
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
            <span style={{ fontSize: 12 }}>{text}</span>
          </Tooltip>
        );
      },
    },
    {
      title: "RequestInput",
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
          return <code style={{ fontSize: 12 }}>{displayText}</code>;
        }

        const truncatedText =
          displayText.length > 50
            ? displayText.substring(0, 50) + "..."
            : displayText;

        return (
          <Tooltip
            title={
              <div style={{ position: "relative" }}>
                <div
                  style={{
                    maxWidth: 400,
                    maxHeight: 300,
                    overflow: "auto",
                    whiteSpace: "pre-wrap",
                    fontSize: 12,
                    fontFamily: "monospace",
                    paddingRight: 30,
                  }}
                >
                  {fullText}
                </div>
                <Button
                  type="text"
                  icon={<CopyOutlined />}
                  size="small"
                  onClick={(e) => {
                    e.stopPropagation();
                    copyToClipboard(fullText);
                  }}
                  style={{
                    position: "absolute",
                    top: 0,
                    right: 0,
                    color: "#1890ff",
                    zIndex: 10,
                  }}
                />
              </div>
            }
            placement="topLeft"
            overlayInnerStyle={{ maxWidth: 400 }}
          >
            <code
              style={{
                fontSize: 12,
                cursor: "help",
                textDecoration: "underline dotted",
              }}
            >
              {truncatedText}
            </code>
          </Tooltip>
        );
      },
    },
    {
      title: "RequestSessionID",
      dataIndex: ["request", "session_id"],
      key: "session_id",
      width: 160,
    },
    {
      title: "RequestUserID",
      dataIndex: ["request", "user_id"],
      key: "user_id",
      width: 140,
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
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
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
