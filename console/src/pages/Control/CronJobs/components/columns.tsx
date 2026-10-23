import { Button, Popover, Dropdown, Tag, Switch } from "@agentscope-ai/design";
import type { ColumnsType } from "antd/es/table";
import type { MenuProps } from "antd";
import {
  requiresCronImportReview,
  type CronJobSpecOutput,
} from "../../../../api/types";
import { Ellipsis as MoreOutlined, Play, History } from "lucide-react";
import dayjs from "dayjs";
import { TFunction } from "i18next";
import { parseCron } from "./parseCron";
import styles from "../index.module.less";

type CronJob = CronJobSpecOutput;

interface ColumnHandlers {
  onToggleEnabled: (job: CronJob) => void;
  onExecuteNow: (job: CronJob) => void;
  onPromoteImported: (job: CronJob) => void;
  onViewHistory: (job: CronJob) => void;
  onEdit: (job: CronJob) => void;
  onDelete: (jobId: string) => void;
  promotingJobIds: Set<string>;
  t: TFunction;
}

export const createColumns = (
  handlers: ColumnHandlers,
): ColumnsType<CronJob> => {
  return [
    {
      title: handlers.t("cronJobs.name"),
      key: "name",
      width: 280,
      render: (_: unknown, record: CronJob) => (
        <button
          type="button"
          className={styles.taskName}
          onClick={() => handlers.onEdit(record)}
        >
          <strong>{record.name}</strong>
          <span>
            {record.dispatch.channel}
            {record.text ? ` · ${record.text}` : ""}
          </span>
        </button>
      ),
    },
    {
      title: handlers.t("cronJobs.enabled"),
      dataIndex: "enabled",
      key: "enabled",
      width: 100,
      render: (enabled: boolean, record: CronJob) =>
        requiresCronImportReview(record) ? (
          <Tag color="orange">{handlers.t("cronJobs.importReviewBadge")}</Tag>
        ) : (
          <Switch
            checked={enabled}
            aria-label={`${record.name} ${handlers.t("cronJobs.enabled")}`}
            onChange={() => handlers.onToggleEnabled(record)}
          />
        ),
    },
    {
      title: handlers.t("cronJobs.scheduleCron"),
      dataIndex: "schedule",
      key: "cron",
      width: 180,
      render: (schedule: CronJob["schedule"]) => {
        if (schedule?.type === "once") {
          const displayText = schedule?.run_at
            ? dayjs(schedule.run_at).format("YYYY-MM-DD HH:mm")
            : "-";
          return (
            <Popover trigger="click" content={schedule?.run_at || displayText}>
              <button type="button" className={styles.cronText}>
                {displayText}
              </button>
            </Popover>
          );
        }
        const cron = schedule?.cron || "0 9 * * *";
        // Parse cron to friendly text
        const cronParts = parseCron(cron);
        let displayText = "";

        switch (cronParts.type) {
          case "minutes":
            displayText = handlers.t("cronJobs.everyMinutes", {
              count: cronParts.intervalMinutes,
            });
            break;
          case "monthly":
            displayText = `${handlers.t("cronJobs.cronTypeMonthly")} · ${
              cronParts.dayOfMonth
            } · ${String(cronParts.hour).padStart(2, "0")}:${String(
              cronParts.minute,
            ).padStart(2, "0")}`;
            break;
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
          <Popover
            trigger="click"
            content={
              <div>
                <div>
                  {handlers.t("cronJobs.cronExpression")}: {cron}
                </div>
                <div
                  className={styles.tableText}
                  style={{ opacity: 0.8, marginTop: 4 }}
                >
                  {handlers.t("cronJobs.cronFormatHint")}
                </div>
              </div>
            }
          >
            <button type="button" className={styles.cronText}>
              {displayText}
            </button>
          </Popover>
        );
      },
    },
    {
      title: handlers.t("cronJobs.action"),
      key: "action",
      width: 148,

      render: (_: unknown, record: CronJob) => {
        const reviewRequired = requiresCronImportReview(record);
        const menuItems: MenuProps["items"] = [
          {
            key: "edit",
            label: handlers.t("cronJobs.edit"),
            onClick: () => handlers.onEdit(record),
          },
          {
            key: "delete",
            label: handlers.t("cronJobs.delete"),
            danger: true,
            onClick: () => handlers.onDelete(record.id),
          },
        ];

        return (
          <div className={styles.actionColumn}>
            {reviewRequired && (
              <Button
                type="text"
                size="small"
                loading={handlers.promotingJobIds.has(record.id)}
                onClick={() => handlers.onPromoteImported(record)}
              >
                {handlers.t("cronJobs.importReviewApprove")}
              </Button>
            )}
            <Button
              type="text"
              size="small"
              disabled={reviewRequired}
              onClick={() => handlers.onExecuteNow(record)}
              aria-label={handlers.t("cronJobs.executeNow")}
              title={handlers.t("cronJobs.executeNow")}
              icon={<Play size={16} />}
            />
            <Button
              type="text"
              size="small"
              onClick={() => handlers.onViewHistory(record)}
              aria-label={handlers.t("cronJobs.executionHistory")}
              title={handlers.t("cronJobs.executionHistory")}
              icon={<History size={16} />}
            />
            <Dropdown menu={{ items: menuItems }} placement="bottomRight">
              <Button
                type="text"
                size="small"
                aria-label={handlers.t("cronJobs.action")}
                icon={<MoreOutlined size="1em" />}
              />
            </Dropdown>
          </div>
        );
      },
    },
  ];
};
