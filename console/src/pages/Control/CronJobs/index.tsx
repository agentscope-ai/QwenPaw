import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import dayjs from "dayjs";
import timezone from "dayjs/plugin/timezone";
import utc from "dayjs/plugin/utc";
import type {
  CronDispatchTargetItem,
  CronJobExecutionRecord,
  CronJobSpecOutput,
} from "../../../api/types";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  createColumns,
  JobDrawer,
  TemplatePickerModal,
  useCronJobs,
  DEFAULT_FORM_VALUES,
} from "./components";
import { parseCron, serializeCron } from "./components/parseCron";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  useReactTable,
  getCoreRowModel,
  getPaginationRowModel,
  flexRender,
  type SortingState,
  getSortedRowModel,
} from "@tanstack/react-table";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Loader2,
  List,
  Calendar,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

type CronJob = CronJobSpecOutput;
type OneTimeCronJob = CronJob & {
  schedule: {
    type: "once";
    run_at: string;
    timezone?: string;
    repeat_every_days?: number;
    repeat_end_type?: "never" | "until" | "count";
    repeat_until?: string;
    repeat_count?: number;
  };
};
type CronViewMode = "list" | "calendar";
type ScheduleTypeFilter = "all" | "cron" | "once";
type OneTimeJobEvent = {
  job: OneTimeCronJob;
  runAtInUserTimezone: dayjs.Dayjs;
};

interface ConfirmState {
  open: boolean;
  title: string;
  description: string;
  onConfirm: () => Promise<void>;
}

dayjs.extend(utc);
dayjs.extend(timezone);

function CronJobsPage() {
  const { t } = useTranslation();
  const {
    jobs,
    loading,
    createJob,
    updateJob,
    deleteJob,
    toggleEnabled,
    executeNow,
  } = useCronJobs();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [editingJob, setEditingJob] = useState<CronJob | null>(null);
  const [saving, setSaving] = useState(false);
  const [templateModalOpen, setTemplateModalOpen] = useState(false);
  const [viewMode, setViewMode] = useState<CronViewMode>("list");
  const [scheduleTypeFilter, setScheduleTypeFilter] =
    useState<ScheduleTypeFilter>("all");
  const [calendarMonth, setCalendarMonth] = useState(dayjs());
  const [activePopoverDate, setActivePopoverDate] = useState<string | null>(
    null,
  );
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyRecords, setHistoryRecords] = useState<
    CronJobExecutionRecord[]
  >([]);
  const [historyJobName, setHistoryJobName] = useState("");
  const [expandedHistoryErrors, setExpandedHistoryErrors] = useState<
    Set<string>
  >(new Set());
  const [userTimezone, setUserTimezone] = useState("UTC");
  const [confirmState, setConfirmState] = useState<ConfirmState>({
    open: false,
    title: "",
    description: "",
    onConfirm: async () => {},
  });
  const [sorting, setSorting] = useState<SortingState>([]);
  const [pagination, setPagination] = useState({ pageIndex: 0, pageSize: 10 });

  // Form proxy — satisfies JobDrawer.form interface; JobDrawer overrides the methods internally
  const form = useRef({
    getFieldValue: (_name: string | string[]) => undefined as any,
    setFieldsValue: (_values: Record<string, any>) => {},
    resetFields: () => {},
    submit: () => {},
  });

  const userTimezoneRef = useRef("UTC");
  const [targetItems, setTargetItems] = useState<CronDispatchTargetItem[]>([]);
  const [targetChannels, setTargetChannels] = useState<string[]>(["console"]);
  const [, setTargetsLoading] = useState(false);

  const isOneTimeJob = (job: CronJob): job is OneTimeCronJob =>
    job.schedule?.type === "once" && typeof job.schedule?.run_at === "string";

  useEffect(() => {
    api
      .getUserTimezone()
      .then((res) => {
        if (res.timezone) {
          userTimezoneRef.current = res.timezone;
          setUserTimezone(res.timezone);
          setCalendarMonth(dayjs().tz(res.timezone));
        }
      })
      .catch((err) => console.error("Failed to fetch user timezone:", err));
  }, []);

  const loadDispatchTargets = useCallback(async () => {
    setTargetsLoading(true);
    try {
      const res = await api.listCronDispatchTargets();
      setTargetItems(res?.items || []);
      setTargetChannels(res?.channels?.length ? res.channels : ["console"]);
    } catch (error) {
      console.error("Failed to fetch cron dispatch targets", error);
      setTargetItems([]);
      setTargetChannels(["console"]);
    } finally {
      setTargetsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadDispatchTargets();
  }, [loadDispatchTargets]);

  const handleCreate = () => {
    setEditingJob(null);
    form.current.resetFields();
    form.current.setFieldsValue({
      ...DEFAULT_FORM_VALUES,
      schedule: {
        ...DEFAULT_FORM_VALUES.schedule,
        timezone: userTimezoneRef.current,
      },
    });
    setDrawerOpen(true);
  };

  const handleOpenTemplateModal = () => {
    setTemplateModalOpen(true);
  };

  const handleUseTemplate = (templateValues: Record<string, unknown>) => {
    setTemplateModalOpen(false);
    setEditingJob(null);
    form.current.resetFields();
    form.current.setFieldsValue({
      ...DEFAULT_FORM_VALUES,
      schedule: {
        ...DEFAULT_FORM_VALUES.schedule,
        timezone: userTimezoneRef.current,
      },
      ...templateValues,
    });
    setDrawerOpen(true);
  };

  const handleEdit = (job: CronJob) => {
    setEditingJob(job);

    const formValues: any = {
      ...job,
      request: {
        ...job.request,
        input: job.request?.input
          ? JSON.stringify(job.request.input, null, 2)
          : "",
      },
      scheduleType: job.schedule?.type || "cron",
    };

    if (job.schedule?.type === "once") {
      formValues.onceRunAt = job.schedule.run_at
        ? dayjs(job.schedule.run_at)
        : null;
      formValues.onceRepeatEnabled = Boolean(job.schedule.repeat_every_days);
      formValues.onceRepeatEveryDays = job.schedule.repeat_every_days || 1;
      formValues.onceRepeatEndType = job.schedule.repeat_end_type || "never";
      formValues.onceRepeatUntil = job.schedule.repeat_until
        ? dayjs(job.schedule.repeat_until)
        : null;
      formValues.onceRepeatCount = job.schedule.repeat_count || 2;
    } else {
      const cronParts = parseCron(job.schedule?.cron || "0 9 * * *");
      formValues.cronType = cronParts.type;

      if (cronParts.type === "daily" || cronParts.type === "weekly") {
        const h = cronParts.hour ?? 9;
        const m = cronParts.minute ?? 0;
        formValues.cronTime = dayjs().hour(h).minute(m);
      }

      if (cronParts.type === "weekly" && cronParts.daysOfWeek) {
        formValues.cronDaysOfWeek = cronParts.daysOfWeek;
      }

      if (cronParts.type === "custom" && cronParts.rawCron) {
        formValues.cronCustom = cronParts.rawCron;
      }
    }

    form.current.setFieldsValue(formValues);
    setDrawerOpen(true);
  };

  const handleDelete = (jobId: string) => {
    setConfirmState({
      open: true,
      title: t("cronJobs.confirmDelete"),
      description: t("cronJobs.deleteConfirm"),
      onConfirm: async () => {
        await deleteJob(jobId);
      },
    });
  };

  const handleToggleEnabled = async (job: CronJob) => {
    await toggleEnabled(job);
  };

  const handleExecuteNow = (job: CronJob) => {
    setConfirmState({
      open: true,
      title: t("cronJobs.executeNowTitle"),
      description: t("cronJobs.executeNowContent", { name: job.name }),
      onConfirm: async () => {
        await executeNow(job.id);
      },
    });
  };

  const handleDrawerClose = () => {
    setDrawerOpen(false);
    setEditingJob(null);
  };

  const handleViewHistory = async (job: CronJob) => {
    setHistoryJobName(job.name);
    setHistoryModalOpen(true);
    setExpandedHistoryErrors(new Set());
    setHistoryLoading(true);
    try {
      const records = await api.getCronJobHistory(job.id);
      setHistoryRecords(records || []);
    } catch (error) {
      console.error("Failed to fetch cron history", error);
      setHistoryRecords([]);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleSubmit = async (values: any) => {
    let schedule: any = values.schedule || {};
    if ((values.scheduleType || "cron") === "once") {
      const onceRepeatEnabled = Boolean(values.onceRepeatEnabled);
      const repeatEndType = values.onceRepeatEndType || "never";
      schedule = {
        type: "once",
        run_at: values.onceRunAt
          ? dayjs(values.onceRunAt).format("YYYY-MM-DDTHH:mm:00")
          : undefined,
        timezone: values.schedule?.timezone || userTimezoneRef.current,
        repeat_every_days: onceRepeatEnabled
          ? Number(values.onceRepeatEveryDays || 1)
          : undefined,
        repeat_end_type: onceRepeatEnabled ? repeatEndType : undefined,
        repeat_until:
          onceRepeatEnabled &&
          repeatEndType === "until" &&
          values.onceRepeatUntil
            ? dayjs(values.onceRepeatUntil).format("YYYY-MM-DDTHH:mm:00")
            : undefined,
        repeat_count:
          onceRepeatEnabled && repeatEndType === "count"
            ? Number(values.onceRepeatCount || 1)
            : undefined,
      };
    } else {
      const cronParts: any = {
        type: values.cronType || "daily",
      };

      if (values.cronType === "daily" || values.cronType === "weekly") {
        if (values.cronTime) {
          cronParts.hour = values.cronTime.hour();
          cronParts.minute = values.cronTime.minute();
        }
      }

      if (values.cronType === "weekly" && values.cronDaysOfWeek) {
        cronParts.daysOfWeek = values.cronDaysOfWeek;
      }

      if (values.cronType === "custom" && values.cronCustom) {
        cronParts.rawCron = values.cronCustom;
      }

      schedule = {
        ...values.schedule,
        type: "cron",
        cron: serializeCron(cronParts),
      };
    }

    const processedValues = {
      ...values,
      schedule,
    };
    delete processedValues.scheduleType;
    delete processedValues.onceRunAt;
    delete processedValues.onceRepeatEnabled;
    delete processedValues.onceRepeatEveryDays;
    delete processedValues.onceRepeatEndType;
    delete processedValues.onceRepeatUntil;
    delete processedValues.onceRepeatCount;
    delete processedValues.cronType;
    delete processedValues.cronTime;
    delete processedValues.cronDaysOfWeek;
    delete processedValues.cronCustom;

    if (processedValues.task_type === "text") {
      delete processedValues.request;
    } else if (processedValues.task_type === "agent") {
      if (!processedValues.request) {
        processedValues.request = {};
      }
      if (
        processedValues.request?.input &&
        typeof processedValues.request.input === "string"
      ) {
        try {
          processedValues.request.input = JSON.parse(
            processedValues.request.input,
          );
        } catch (error) {
          console.error("Failed to parse request.input JSON:", error);
        }
      }
    }

    let success = false;
    setSaving(true);
    try {
      if (editingJob) {
        success = await updateJob(editingJob.id, processedValues);
      } else {
        success = await createJob(processedValues);
      }
    } finally {
      setSaving(false);
    }
    if (success) {
      setDrawerOpen(false);
    }
  };

  const HISTORY_ERROR_PREVIEW_LINES = 4;
  const HISTORY_ERROR_PREVIEW_CHARS = 280;

  const shouldShowErrorToggle = (errorText: string) => {
    const lineCount = errorText.split("\n").length;
    return (
      lineCount > HISTORY_ERROR_PREVIEW_LINES ||
      errorText.length > HISTORY_ERROR_PREVIEW_CHARS
    );
  };

  const toggleHistoryError = (recordKey: string) => {
    setExpandedHistoryErrors((prev) => {
      const next = new Set(prev);
      if (next.has(recordKey)) {
        next.delete(recordKey);
      } else {
        next.add(recordKey);
      }
      return next;
    });
  };

  const parseAtInTimezone = (timeText: string, timezoneName: string) => {
    const hasOffset = /([zZ]|[+-]\d{2}:?\d{2})$/.test(timeText);
    if (hasOffset) {
      return dayjs(timeText).tz(timezoneName);
    }
    return dayjs.tz(timeText, timezoneName);
  };

  const oneTimeJobs = useMemo(() => jobs.filter(isOneTimeJob).slice(), [jobs]);

  const filteredListJobs = useMemo(() => {
    if (scheduleTypeFilter === "all") return jobs;
    return jobs.filter((job) => job.schedule?.type === scheduleTypeFilter);
  }, [jobs, scheduleTypeFilter]);

  const columns = createColumns({
    onToggleEnabled: handleToggleEnabled,
    onExecuteNow: handleExecuteNow,
    onViewHistory: handleViewHistory,
    onEdit: handleEdit,
    onDelete: handleDelete,
    t,
  });

  const table = useReactTable({
    data: filteredListJobs,
    columns,
    state: { sorting, pagination },
    onSortingChange: setSorting,
    onPaginationChange: setPagination,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getRowId: (row) => row.id,
    manualPagination: false,
  });

  const calendarDays = useMemo(() => {
    const monthStart = calendarMonth.startOf("month");
    const calendarStart = monthStart.startOf("week");
    return Array.from({ length: 42 }, (_, index) =>
      calendarStart.add(index, "day"),
    );
  }, [calendarMonth]);

  const oneTimeJobEvents = useMemo<OneTimeJobEvent[]>(() => {
    if (calendarDays.length === 0) return [];
    const rangeStartInUserTz = calendarDays[0].startOf("day");
    const rangeEndInUserTz = calendarDays[calendarDays.length - 1].endOf("day");
    const events: OneTimeJobEvent[] = [];

    oneTimeJobs.forEach((job) => {
      const scheduleTimezone = job.schedule.timezone || "UTC";
      const baseInScheduleTz = parseAtInTimezone(
        job.schedule.run_at,
        scheduleTimezone,
      );
      const rangeStartInScheduleTz = rangeStartInUserTz.tz(scheduleTimezone);
      const rangeEndInScheduleTz = rangeEndInUserTz.tz(scheduleTimezone);
      const repeatEveryDays = job.schedule.repeat_every_days;

      if (!repeatEveryDays) {
        const runAtInUserTimezone = baseInScheduleTz.tz(userTimezone);
        if (
          !runAtInUserTimezone.isBefore(rangeStartInUserTz) &&
          !runAtInUserTimezone.isAfter(rangeEndInUserTz)
        ) {
          events.push({ job, runAtInUserTimezone });
        }
        return;
      }

      const countLimit =
        job.schedule.repeat_end_type === "count"
          ? job.schedule.repeat_count ?? 0
          : null;
      if (countLimit !== null && countLimit <= 0) return;

      const untilInScheduleTz =
        job.schedule.repeat_end_type === "until" && job.schedule.repeat_until
          ? parseAtInTimezone(job.schedule.repeat_until, scheduleTimezone)
          : null;

      let startIndex = 0;
      if (baseInScheduleTz.isBefore(rangeStartInScheduleTz)) {
        const diffDays = rangeStartInScheduleTz
          .startOf("day")
          .diff(baseInScheduleTz.startOf("day"), "day");
        startIndex = Math.max(0, Math.floor(diffDays / repeatEveryDays));
      }

      let index = startIndex;
      let current = baseInScheduleTz.add(index * repeatEveryDays, "day");
      while (current.isBefore(rangeStartInScheduleTz)) {
        index += 1;
        current = baseInScheduleTz.add(index * repeatEveryDays, "day");
      }

      const maxIterations = 400;
      let iterations = 0;
      while (
        !current.isAfter(rangeEndInScheduleTz) &&
        iterations < maxIterations
      ) {
        iterations += 1;
        const runNumber = index + 1;
        if (countLimit !== null && runNumber > countLimit) break;
        if (untilInScheduleTz && current.isAfter(untilInScheduleTz)) break;

        events.push({
          job,
          runAtInUserTimezone: current.tz(userTimezone),
        });
        index += 1;
        current = baseInScheduleTz.add(index * repeatEveryDays, "day");
      }
    });

    return events.sort(
      (a, b) =>
        a.runAtInUserTimezone.valueOf() - b.runAtInUserTimezone.valueOf(),
    );
  }, [calendarDays, oneTimeJobs, userTimezone]);

  const oneTimeJobsByDate = useMemo(() => {
    return oneTimeJobEvents.reduce<Record<string, OneTimeJobEvent[]>>(
      (acc, event) => {
        const dateKey = event.runAtInUserTimezone.format("YYYY-MM-DD");
        if (!acc[dateKey]) acc[dateKey] = [];
        acc[dateKey].push(event);
        return acc;
      },
      {},
    );
  }, [oneTimeJobEvents]);

  return (
    <div className="flex flex-col h-full">
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("cronJobs.title") }]}
        extra={
          <div className="flex items-center gap-2">
            {viewMode === "list" && (
              <Select
                value={scheduleTypeFilter}
                onValueChange={(v) =>
                  setScheduleTypeFilter(v as ScheduleTypeFilter)
                }
              >
                <SelectTrigger className="w-[200px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">
                    {t("cronJobs.scheduleFilterAll")}
                  </SelectItem>
                  <SelectItem value="cron">
                    {t("cronJobs.scheduleTypeRecurring")}
                  </SelectItem>
                  <SelectItem value="once">
                    {t("cronJobs.scheduleTypeOnce")}
                  </SelectItem>
                </SelectContent>
              </Select>
            )}
            <div className="flex items-center border rounded-md overflow-hidden">
              <button
                className={`px-2.5 py-1.5 text-sm transition-colors ${
                  viewMode === "list"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
                onClick={() => setViewMode("list")}
                title={t("cronJobs.listView")}
              >
                <List size={16} />
              </button>
              <button
                className={`px-2.5 py-1.5 text-sm transition-colors ${
                  viewMode === "calendar"
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted"
                }`}
                onClick={() => setViewMode("calendar")}
                title={t("cronJobs.calendarView")}
              >
                <Calendar size={16} />
              </button>
            </div>
            <Button onClick={handleCreate}>+ {t("cronJobs.createJob")}</Button>
            <Button variant="outline" onClick={handleOpenTemplateModal}>
              {t("cronJobs.createFromTemplate")}
            </Button>
          </div>
        }
      />

      {viewMode === "list" ? (
        <Card className="flex-1 mx-4 mb-4">
          <CardContent className="p-0">
            {loading ? (
              <div className="flex items-center justify-center h-32">
                <Loader2 className="animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    {table.getHeaderGroups().map((hg) => (
                      <TableRow key={hg.id}>
                        {hg.headers.map((header) => (
                          <TableHead
                            key={header.id}
                            style={{ width: header.getSize() }}
                          >
                            {flexRender(
                              header.column.columnDef.header,
                              header.getContext(),
                            )}
                          </TableHead>
                        ))}
                      </TableRow>
                    ))}
                  </TableHeader>
                  <TableBody>
                    {table.getRowModel().rows.map((row) => (
                      <TableRow key={row.id}>
                        {row.getVisibleCells().map((cell) => (
                          <TableCell key={cell.id} className="text-sm">
                            {flexRender(
                              cell.column.columnDef.cell,
                              cell.getContext(),
                            )}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                    {table.getRowModel().rows.length === 0 && (
                      <TableRow>
                        <TableCell
                          colSpan={columns.length}
                          className="h-24 text-center text-muted-foreground"
                        >
                          {t("common.noData", "No data")}
                        </TableCell>
                      </TableRow>
                    )}
                  </TableBody>
                </Table>
                {table.getPageCount() > 1 && (
                  <div className="flex items-center justify-end gap-2 px-4 py-3 border-t text-sm">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => table.previousPage()}
                      disabled={!table.getCanPreviousPage()}
                    >
                      <ChevronLeft size={14} />
                    </Button>
                    <span className="text-muted-foreground">
                      {table.getState().pagination.pageIndex + 1} /{" "}
                      {table.getPageCount()}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => table.nextPage()}
                      disabled={!table.getCanNextPage()}
                    >
                      <ChevronRight size={14} />
                    </Button>
                  </div>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <Card className="flex-1 mx-4 mb-4">
          <CardContent className="p-4">
            <div className="flex items-center justify-center gap-4 mb-4">
              <Button
                variant="ghost"
                size="sm"
                onClick={() =>
                  setCalendarMonth((prev) => prev.subtract(1, "month"))
                }
              >
                <ChevronLeft size={16} />
              </Button>
              <span className="font-medium">
                {calendarMonth.tz(userTimezone).format("YYYY-MM")}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setCalendarMonth((prev) => prev.add(1, "month"))}
              >
                <ChevronRight size={16} />
              </Button>
            </div>

            {oneTimeJobs.length === 0 && (
              <div className="text-center text-muted-foreground text-sm py-4">
                {t("cronJobs.calendarEmptyHint")}
              </div>
            )}

            <div className="grid grid-cols-7 mb-1">
              {[0, 1, 2, 3, 4, 5, 6].map((day) => (
                <div
                  key={day}
                  className="text-center text-xs font-medium text-muted-foreground py-1"
                >
                  {dayjs().day(day).format("dd")}
                </div>
              ))}
            </div>
            <div className="grid grid-cols-7 border-l border-t">
              {calendarDays.map((day) => {
                const dateKey = day.format("YYYY-MM-DD");
                const dayEvents = oneTimeJobsByDate[dateKey] || [];
                const isCurrentMonth = day.month() === calendarMonth.month();
                const isToday = day.isSame(dayjs().tz(userTimezone), "day");
                const visibleEvents = dayEvents.slice(0, 3);
                const hiddenCount = Math.max(dayEvents.length - 3, 0);

                return (
                  <div
                    key={dateKey}
                    className={`border-r border-b min-h-[80px] p-1 ${
                      !isCurrentMonth ? "opacity-40" : ""
                    }`}
                  >
                    <div
                      className={`text-xs w-6 h-6 flex items-center justify-center rounded-full mb-1 ${
                        isToday
                          ? "bg-primary text-primary-foreground font-semibold"
                          : "text-foreground"
                      }`}
                    >
                      {day.date()}
                    </div>
                    <div className="flex flex-col gap-0.5">
                      {visibleEvents.map(({ job, runAtInUserTimezone }) => (
                        <div
                          key={job.id}
                          className={`text-[10px] px-1 rounded truncate cursor-pointer hover:opacity-80 ${
                            job.enabled
                              ? "bg-primary/20 text-primary"
                              : "bg-muted text-muted-foreground"
                          }`}
                          title={`${runAtInUserTimezone.format("HH:mm")} ${
                            job.name
                          }`}
                          onClick={() => handleEdit(job)}
                        >
                          {runAtInUserTimezone.format("HH:mm")} {job.name}
                        </div>
                      ))}
                      {hiddenCount > 0 && (
                        <Popover
                          open={activePopoverDate === dateKey}
                          onOpenChange={(open) =>
                            setActivePopoverDate(open ? dateKey : null)
                          }
                        >
                          <PopoverTrigger asChild>
                            <button className="text-[10px] text-primary hover:underline text-left px-1">
                              {t("cronJobs.calendarMoreItems", {
                                count: hiddenCount,
                              })}
                            </button>
                          </PopoverTrigger>
                          <PopoverContent
                            side="right"
                            align="start"
                            className="w-64 p-3"
                          >
                            <div className="flex items-baseline gap-2 mb-2">
                              <span className="font-semibold">
                                {day.format("D")}
                              </span>
                              <span className="text-muted-foreground text-xs">
                                {day.format("ddd")}
                              </span>
                            </div>
                            <div className="flex flex-col gap-1">
                              {dayEvents.map(({ job, runAtInUserTimezone }) => (
                                <div
                                  key={job.id}
                                  className={`text-xs flex gap-2 items-center cursor-pointer hover:opacity-70 ${
                                    job.enabled ? "" : "opacity-40"
                                  }`}
                                  onClick={() => {
                                    setActivePopoverDate(null);
                                    handleEdit(job);
                                  }}
                                >
                                  <span className="font-mono">
                                    {runAtInUserTimezone.format("HH:mm")}
                                  </span>
                                  <span className="truncate">{job.name}</span>
                                </div>
                              ))}
                            </div>
                          </PopoverContent>
                        </Popover>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      <JobDrawer
        open={drawerOpen}
        editingJob={editingJob}
        form={form.current}
        saving={saving}
        targetItems={targetItems}
        targetChannels={targetChannels}
        onReloadTargets={loadDispatchTargets}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />

      <TemplatePickerModal
        open={templateModalOpen}
        timezone={userTimezoneRef.current}
        onCancel={() => setTemplateModalOpen(false)}
        onUseTemplate={handleUseTemplate}
      />

      {/* History Dialog */}
      <Dialog
        open={historyModalOpen}
        onOpenChange={(o) => !o && setHistoryModalOpen(false)}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {t("cronJobs.historyTitle", { name: historyJobName })}
            </DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            {historyLoading ? (
              <div className="flex items-center justify-center h-24">
                <Loader2 className="animate-spin text-muted-foreground" />
              </div>
            ) : historyRecords.length === 0 ? (
              <div className="text-center text-muted-foreground py-8 text-sm">
                {t("cronJobs.historyEmpty")}
              </div>
            ) : (
              <div className="flex flex-col gap-3">
                {historyRecords.map((record, index) => {
                  const recordKey = `${record.run_at}-${index}`;
                  const expanded = expandedHistoryErrors.has(recordKey);
                  const showToggle = record.error
                    ? shouldShowErrorToggle(record.error)
                    : false;
                  return (
                    <div
                      key={recordKey}
                      className="border rounded-lg p-3 flex flex-col gap-1"
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-mono text-muted-foreground">
                          {dayjs(record.run_at)
                            .tz(userTimezone)
                            .format("YYYY-MM-DD HH:mm:ss")}
                        </span>
                        <span
                          className={`text-xs font-medium ${
                            record.status === "success"
                              ? "text-green-600"
                              : record.status === "running"
                              ? "text-blue-600"
                              : "text-destructive"
                          }`}
                        >
                          {record.status === "success"
                            ? t("cronJobs.historyStatusSuccess")
                            : record.status === "running"
                            ? t("cronJobs.historyStatusRunning")
                            : record.status === "cancelled"
                            ? t("cronJobs.historyStatusCancelled")
                            : t("cronJobs.historyStatusFailed")}
                        </span>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {record.trigger === "manual"
                          ? t("cronJobs.historyTriggerManual")
                          : t("cronJobs.historyTriggerScheduled")}
                      </div>
                      {record.error && (
                        <div>
                          <pre
                            className={`text-xs bg-muted rounded p-2 whitespace-pre-wrap break-all overflow-hidden ${
                              !expanded && showToggle ? "max-h-[5rem]" : ""
                            }`}
                          >
                            {record.error}
                          </pre>
                          {showToggle && (
                            <button
                              type="button"
                              className="text-xs text-primary hover:underline mt-1"
                              onClick={() => toggleHistoryError(recordKey)}
                            >
                              {expanded
                                ? t("cronJobs.historyCollapse")
                                : t("cronJobs.historyExpand")}
                            </button>
                          )}
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Confirm Dialog */}
      <AlertDialog
        open={confirmState.open}
        onOpenChange={(o) =>
          !o && setConfirmState((s) => ({ ...s, open: false }))
        }
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{confirmState.title}</AlertDialogTitle>
            <AlertDialogDescription>
              {confirmState.description}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("cronJobs.cancelText")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={async () => {
                await confirmState.onConfirm();
                setConfirmState((s) => ({ ...s, open: false }));
              }}
            >
              {t("cronJobs.deleteText")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}

export default CronJobsPage;
