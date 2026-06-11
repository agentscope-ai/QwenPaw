import type { ColumnDef } from "@tanstack/react-table";
import type { CronJobSpecOutput } from "../../../../api/types";
import { Copy, MoreHorizontal } from "lucide-react";
import dayjs from "dayjs";
import { useAppMessage } from "../../../../hooks/useAppMessage";
import { TFunction } from "i18next";
import { parseCron } from "./parseCron";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

type CronJob = CronJobSpecOutput;

interface ColumnHandlers {
  onToggleEnabled: (job: CronJob) => void;
  onExecuteNow: (job: CronJob) => void;
  onViewHistory: (job: CronJob) => void;
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
): ColumnDef<CronJob>[] => {
  const copyToClipboard = createCopyToClipboard(handlers.t);

  return [
    {
      accessorKey: "id",
      header: handlers.t("cronJobs.id"),
      size: 250,
    },
    {
      accessorKey: "name",
      header: handlers.t("cronJobs.name"),
      size: 250,
    },
    {
      accessorKey: "enabled",
      header: handlers.t("cronJobs.enabled"),
      size: 100,
      cell: ({ row }) => {
        const enabled: boolean = row.getValue("enabled");
        return (
          <span className="flex items-center gap-1.5">
            <span
              className={`inline-block w-2 h-2 rounded-full ${
                enabled ? "bg-green-500" : "bg-gray-400"
              }`}
            />
            {enabled
              ? handlers.t("common.enabled")
              : handlers.t("common.disabled")}
          </span>
        );
      },
    },
    {
      id: "schedule_type",
      header: handlers.t("cronJobs.scheduleType"),
      size: 140,
      accessorFn: (row) => row.schedule?.type,
      cell: ({ row }) => {
        const type = row.original.schedule?.type;
        return type === "once"
          ? handlers.t("cronJobs.scheduleTypeOnce")
          : handlers.t("cronJobs.scheduleTypeRecurring");
      },
    },
    {
      id: "cron",
      header: handlers.t("cronJobs.scheduleCron"),
      size: 180,
      cell: ({ row }) => {
        const schedule = row.original.schedule as any;
        if (schedule?.type === "once") {
          const displayText = schedule?.run_at
            ? dayjs(schedule.run_at).format("YYYY-MM-DD HH:mm")
            : "-";
          return (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="truncate max-w-[160px] block cursor-default">
                  {displayText}
                </span>
              </TooltipTrigger>
              <TooltipContent>{schedule?.run_at || displayText}</TooltipContent>
            </Tooltip>
          );
        }
        const cron = schedule?.cron || "0 9 * * *";
        const cronParts = parseCron(cron);
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
            const dayMap: Record<string, string> = {
              mon: handlers.t("cronJobs.cronDayMon"),
              tue: handlers.t("cronJobs.cronDayTue"),
              wed: handlers.t("cronJobs.cronDayWed"),
              thu: handlers.t("cronJobs.cronDayThu"),
              fri: handlers.t("cronJobs.cronDayFri"),
              sat: handlers.t("cronJobs.cronDaySat"),
              sun: handlers.t("cronJobs.cronDaySun"),
            };
            const dayNames = (cronParts.daysOfWeek || [])
              .map((d) => dayMap[d] || d)
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
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="truncate max-w-[160px] block cursor-default">
                {displayText}
              </span>
            </TooltipTrigger>
            <TooltipContent>
              <div>Cron: {cron}</div>
              <div className="opacity-80 mt-1 text-xs">
                Format: min hr day month weekday
              </div>
            </TooltipContent>
          </Tooltip>
        );
      },
    },
    {
      id: "timezone",
      header: handlers.t("cronJobs.scheduleTimezone"),
      size: 170,
      accessorFn: (row) => (row.schedule as any)?.timezone,
    },
    {
      accessorKey: "task_type",
      header: "TaskType",
      size: 140,
    },
    {
      accessorKey: "text",
      header: handlers.t("cronJobs.text"),
      size: 200,
      cell: ({ row }) => {
        const text: string = row.getValue("text");
        if (!text) return "-";
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="truncate max-w-[180px] block cursor-default">
                {text}
              </span>
            </TooltipTrigger>
            <TooltipContent>{text}</TooltipContent>
          </Tooltip>
        );
      },
    },
    {
      id: "request_input",
      header: handlers.t("cronJobs.requestInput"),
      size: 350,
      accessorFn: (row) => row.request?.input,
      cell: ({ row }) => {
        const input = row.original.request?.input;
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
          return <code className="text-xs font-mono">{displayText}</code>;
        }
        const truncated = displayText.substring(0, 50) + "...";
        return (
          <Tooltip>
            <TooltipTrigger asChild>
              <code
                className="text-xs font-mono text-primary cursor-pointer"
                onClick={() => copyToClipboard(fullText)}
              >
                {truncated}
              </code>
            </TooltipTrigger>
            <TooltipContent className="max-w-[400px]">
              <div className="flex items-start gap-1">
                <pre className="text-xs whitespace-pre-wrap break-all max-h-[200px] overflow-auto">
                  {fullText}
                </pre>
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 shrink-0"
                  onClick={(e) => {
                    e.stopPropagation();
                    copyToClipboard(fullText);
                  }}
                >
                  <Copy size={12} />
                </Button>
              </div>
            </TooltipContent>
          </Tooltip>
        );
      },
    },
    {
      id: "dispatch_type",
      header: "DispatchType",
      size: 140,
      accessorFn: (row) => (row as any).dispatch?.type,
    },
    {
      id: "channel",
      header: "DispatchChannel",
      size: 150,
      accessorFn: (row) => (row as any).dispatch?.channel,
    },
    {
      id: "target_user_id",
      header: "DispatchTargetUserID",
      size: 190,
      accessorFn: (row) => (row as any).dispatch?.target?.user_id,
    },
    {
      id: "target_session_id",
      header: "DispatchTargetSessionID",
      size: 210,
      accessorFn: (row) => (row as any).dispatch?.target?.session_id,
    },
    {
      id: "mode",
      header: "DispatchMode",
      size: 140,
      accessorFn: (row) => (row as any).dispatch?.mode,
    },
    {
      id: "max_concurrency",
      header: "RuntimeMaxConcurrency",
      size: 210,
      accessorFn: (row) => (row as any).runtime?.max_concurrency,
    },
    {
      id: "timeout_seconds",
      header: "RuntimeTimeoutSeconds",
      size: 210,
      accessorFn: (row) => (row as any).runtime?.timeout_seconds,
    },
    {
      id: "misfire_grace_seconds",
      header: "RuntimeMisfireGraceSeconds",
      size: 240,
      accessorFn: (row) => (row as any).runtime?.misfire_grace_seconds,
    },
    {
      id: "action",
      header: handlers.t("cronJobs.action"),
      size: 320,
      cell: ({ row }) => {
        const record = row.original;
        return (
          <div className="flex items-center gap-1">
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => handlers.onToggleEnabled(record)}
            >
              {record.enabled
                ? handlers.t("cronJobs.disable")
                : handlers.t("common.enable")}
            </Button>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => handlers.onExecuteNow(record)}
            >
              {handlers.t("cronJobs.executeNow")}
            </Button>
            <Button
              variant="link"
              size="sm"
              className="h-auto p-0 text-xs"
              onClick={() => handlers.onViewHistory(record)}
            >
              {handlers.t("cronJobs.executionHistory")}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-6 w-6 p-0">
                  <MoreHorizontal size={14} />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  disabled={record.enabled}
                  onClick={() => handlers.onEdit(record)}
                >
                  {handlers.t("cronJobs.edit")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={record.enabled}
                  className="text-destructive focus:text-destructive"
                  onClick={() => handlers.onDelete(record.id)}
                >
                  {handlers.t("cronJobs.delete")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        );
      },
    },
  ];
};
