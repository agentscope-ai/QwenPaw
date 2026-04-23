import { useState, useEffect, useRef, useMemo } from "react";
import {
  Button,
  Card,
  Form,
  Modal,
  Popover,
  Select,
  Table,
} from "@agentscope-ai/design";
import {
  CalendarOutlined,
  LeftOutlined,
  RightOutlined,
  UnorderedListOutlined,
} from "@ant-design/icons";
import dayjs from "dayjs";
import timezone from "dayjs/plugin/timezone";
import utc from "dayjs/plugin/utc";
import type {
  CronJobExecutionRecord,
  CronJobSpecOutput,
} from "../../../api/types";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import {
  createColumns,
  JobDrawer,
  useCronJobs,
  DEFAULT_FORM_VALUES,
} from "./components";
import { parseCron, serializeCron } from "./components/parseCron";
import { PageHeader } from "@/components/PageHeader";
import styles from "./index.module.less";

type CronJob = CronJobSpecOutput;
type OneTimeCronJob = CronJob & {
  schedule: { type: "once"; run_at: string; timezone?: string };
};
type CronViewMode = "list" | "calendar";
type ScheduleTypeFilter = "all" | "cron" | "once";
type OneTimeJobEvent = {
  job: OneTimeCronJob;
  runAtInUserTimezone: dayjs.Dayjs;
};

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
  const [form] = Form.useForm<CronJob>();
  const userTimezoneRef = useRef("UTC");

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

  const handleCreate = () => {
    setEditingJob(null);
    form.resetFields();
    form.setFieldsValue({
      ...DEFAULT_FORM_VALUES,
      schedule: {
        ...DEFAULT_FORM_VALUES.schedule,
        timezone: userTimezoneRef.current,
      },
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
    } else {
      // Parse cron expression to form fields
      const cronParts = parseCron(job.schedule?.cron || "0 9 * * *");
      formValues.cronType = cronParts.type;

      // Set time picker value
      if (cronParts.type === "daily" || cronParts.type === "weekly") {
        const h = cronParts.hour ?? 9;
        const m = cronParts.minute ?? 0;
        formValues.cronTime = dayjs().hour(h).minute(m);
      }

      // Set days of week
      if (cronParts.type === "weekly" && cronParts.daysOfWeek) {
        formValues.cronDaysOfWeek = cronParts.daysOfWeek;
      }

      // Set custom cron
      if (cronParts.type === "custom" && cronParts.rawCron) {
        formValues.cronCustom = cronParts.rawCron;
      }
    }

    form.setFieldsValue(formValues);
    setDrawerOpen(true);
  };

  const handleDelete = (jobId: string) => {
    Modal.confirm({
      title: t("cronJobs.confirmDelete"),
      content: t("cronJobs.deleteConfirm"),
      okText: t("cronJobs.deleteText"),
      okType: "primary",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
        await deleteJob(jobId);
      },
    });
  };

  const handleToggleEnabled = async (job: CronJob) => {
    await toggleEnabled(job);
  };

  const handleExecuteNow = async (job: CronJob) => {
    Modal.confirm({
      title: t("cronJobs.executeNowTitle"),
      content: t("cronJobs.executeNowContent", { name: job.name }),
      okText: t("cronJobs.executeNowConfirm"),
      okType: "primary",
      cancelText: t("cronJobs.cancelText"),
      onOk: async () => {
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
      schedule = {
        type: "once",
        run_at: values.onceRunAt
          ? dayjs(values.onceRunAt).format("YYYY-MM-DDTHH:mm:00")
          : undefined,
        timezone: values.schedule?.timezone || userTimezoneRef.current,
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

    let processedValues = {
      ...values,
      schedule,
    };
    delete processedValues.scheduleType;
    delete processedValues.onceRunAt;
    delete processedValues.cronType;
    delete processedValues.cronTime;
    delete processedValues.cronDaysOfWeek;
    delete processedValues.cronCustom;

    if (processedValues.task_type === "text") {
      // Remove request object entirely for text tasks
      delete processedValues.request;
    } else if (processedValues.task_type === "agent") {
      //Ensure request object exists
      if (!processedValues.request) {
        processedValues.request = {};
      }

      // Parse request input JSON
      if (
        processedValues.request?.input &&
        typeof processedValues.request.input === "string"
      ) {
        try {
          processedValues.request.input = JSON.parse(
            processedValues.request.input,
          );
        } catch (error) {
          console.error("❌ Failed to parse request.input JSON:", error);
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

  const columns = createColumns({
    onToggleEnabled: handleToggleEnabled,
    onExecuteNow: handleExecuteNow,
    onViewHistory: handleViewHistory,
    onEdit: handleEdit,
    onDelete: handleDelete,
    t,
  });

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

  const getRunAtInUserTimezone = (job: OneTimeCronJob) => {
    const runAt = job.schedule.run_at;
    const hasOffset = /([zZ]|[+-]\d{2}:?\d{2})$/.test(runAt);
    if (hasOffset) {
      return dayjs(runAt).tz(userTimezone);
    }
    return dayjs.tz(runAt, job.schedule.timezone || "UTC").tz(userTimezone);
  };

  const oneTimeJobs = useMemo(
    () =>
      jobs
        .filter(isOneTimeJob)
        .slice()
        .sort(
          (a, b) =>
            dayjs(a.schedule.run_at).valueOf() -
            dayjs(b.schedule.run_at).valueOf(),
        ),
    [jobs],
  );

  const filteredListJobs = useMemo(() => {
    if (scheduleTypeFilter === "all") return jobs;
    return jobs.filter((job) => job.schedule?.type === scheduleTypeFilter);
  }, [jobs, scheduleTypeFilter]);

  const oneTimeJobEvents = useMemo<OneTimeJobEvent[]>(
    () =>
      oneTimeJobs
        .map((job) => ({
          job,
          runAtInUserTimezone: getRunAtInUserTimezone(job),
        }))
        .sort(
          (a, b) =>
            a.runAtInUserTimezone.valueOf() - b.runAtInUserTimezone.valueOf(),
        ),
    [oneTimeJobs, userTimezone],
  );

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

  const calendarDays = useMemo(() => {
    const monthStart = calendarMonth.startOf("month");
    const calendarStart = monthStart.startOf("week");
    return Array.from({ length: 42 }, (_, index) =>
      calendarStart.add(index, "day"),
    );
  }, [calendarMonth]);

  return (
    <div className={styles.cronJobsPage}>
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("cronJobs.title") }]}
        extra={
          <div className={styles.headerActions}>
            <div className={styles.viewToggle}>
              <button
                className={`${styles.viewToggleBtn} ${
                  viewMode === "list" ? styles.viewToggleBtnActive : ""
                }`}
                onClick={() => setViewMode("list")}
                title={t("cronJobs.listView")}
              >
                <UnorderedListOutlined />
              </button>
              <button
                className={`${styles.viewToggleBtn} ${
                  viewMode === "calendar" ? styles.viewToggleBtnActive : ""
                }`}
                onClick={() => setViewMode("calendar")}
                title={t("cronJobs.calendarView")}
              >
                <CalendarOutlined />
              </button>
            </div>
            {viewMode === "list" && (
              <Select<ScheduleTypeFilter>
                value={scheduleTypeFilter}
                onChange={setScheduleTypeFilter}
                style={{ width: 200 }}
                options={[
                  {
                    label: t("cronJobs.scheduleFilterAll"),
                    value: "all",
                  },
                  {
                    label: t("cronJobs.scheduleTypeRecurring"),
                    value: "cron",
                  },
                  {
                    label: t("cronJobs.scheduleTypeOnce"),
                    value: "once",
                  },
                ]}
              />
            )}
            <Button type="primary" onClick={handleCreate}>
              + {t("cronJobs.createJob")}
            </Button>
          </div>
        }
      />

      {viewMode === "list" ? (
        <Card className={styles.tableCard} bodyStyle={{ padding: 0 }}>
          <Table
            columns={columns}
            dataSource={filteredListJobs}
            loading={loading}
            rowKey="id"
            scroll={{ x: 2840 }}
            pagination={{
              pageSize: 10,
              showSizeChanger: false,
            }}
          />
        </Card>
      ) : (
        <Card className={styles.calendarCard} bodyStyle={{ padding: 0 }}>
          <div className={styles.calendarHeader}>
            <Button
              type="text"
              icon={<LeftOutlined />}
              onClick={() =>
                setCalendarMonth((prev) => prev.subtract(1, "month"))
              }
            />
            <div className={styles.calendarTitle}>
              {calendarMonth.tz(userTimezone).format("YYYY-MM")}
            </div>
            <Button
              type="text"
              icon={<RightOutlined />}
              onClick={() => setCalendarMonth((prev) => prev.add(1, "month"))}
            />
          </div>

          {oneTimeJobs.length === 0 && (
            <div className={styles.calendarEmptyHint}>
              {t("cronJobs.calendarEmptyHint")}
            </div>
          )}

          <div className={styles.calendarWeekHeader}>
            {[0, 1, 2, 3, 4, 5, 6].map((day) => (
              <div key={day} className={styles.calendarWeekCell}>
                {dayjs().day(day).format("dd")}
              </div>
            ))}
          </div>
          <div className={styles.calendarGrid}>
            {calendarDays.map((day) => {
              const dateKey = day.format("YYYY-MM-DD");
              const dayEvents = oneTimeJobsByDate[dateKey] || [];
              const isCurrentMonth = day.month() === calendarMonth.month();
              const isToday = day.isSame(dayjs().tz(userTimezone), "day");
              const visibleEvents = dayEvents.slice(0, 3);
              const hiddenCount = Math.max(dayEvents.length - 3, 0);
              const popoverContent = (
                <div className={styles.dayJobPopover}>
                  <div className={styles.dayJobPopoverHeader}>
                    <span className={styles.dayJobPopoverDay}>
                      {day.format("D")}
                    </span>
                    <span className={styles.dayJobPopoverWeek}>
                      {day.format("ddd")}
                    </span>
                  </div>
                  <div className={styles.dayJobList}>
                    {dayEvents.map(({ job, runAtInUserTimezone }) => (
                      <div
                        key={job.id}
                        className={`${styles.dayJobItem} ${
                          job.enabled ? "" : styles.dayJobItemDisabled
                        }`}
                        onClick={() => {
                          setActivePopoverDate(null);
                          handleEdit(job);
                        }}
                      >
                        <span className={styles.dayJobItemTime}>
                          {runAtInUserTimezone.format("HH:mm")}
                        </span>
                        <span className={styles.dayJobItemName}>
                          {job.name}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              );
              return (
                <div
                  key={dateKey}
                  className={`${styles.calendarCell} ${
                    !isCurrentMonth ? styles.calendarCellMuted : ""
                  } ${isToday ? styles.calendarCellToday : ""}`}
                >
                  <div className={styles.calendarCellDate}>{day.date()}</div>
                  <div className={styles.calendarEvents}>
                    {visibleEvents.map(({ job, runAtInUserTimezone }) => (
                      <div
                        key={job.id}
                        className={`${styles.calendarEvent} ${
                          job.enabled ? "" : styles.calendarEventDisabled
                        }`}
                        title={`${runAtInUserTimezone.format("HH:mm")} ${
                          job.name
                        }`}
                        onClick={() => handleEdit(job)}
                      >
                        <span className={styles.calendarEventDot} />
                        <span className={styles.calendarEventText}>
                          {runAtInUserTimezone.format("HH:mm")} {job.name}
                        </span>
                      </div>
                    ))}
                    {hiddenCount > 0 && (
                      <Popover
                        trigger="click"
                        placement="rightTop"
                        open={activePopoverDate === dateKey}
                        onOpenChange={(open) =>
                          setActivePopoverDate(open ? dateKey : null)
                        }
                        overlayClassName={styles.dayJobPopoverOverlay}
                        content={popoverContent}
                      >
                        <button className={styles.calendarMoreBtn}>
                          {t("cronJobs.calendarMoreItems", {
                            count: hiddenCount,
                          })}
                        </button>
                      </Popover>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <JobDrawer
        open={drawerOpen}
        editingJob={editingJob}
        form={form}
        saving={saving}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />

      <Modal
        visible={historyModalOpen}
        title={t("cronJobs.historyTitle", { name: historyJobName })}
        footer={null}
        onCancel={() => setHistoryModalOpen(false)}
      >
        <div className={styles.historyList}>
          {historyLoading ? (
            <div className={styles.historyEmpty}>{t("common.loading")}</div>
          ) : historyRecords.length === 0 ? (
            <div className={styles.historyEmpty}>
              {t("cronJobs.historyEmpty")}
            </div>
          ) : (
            historyRecords.map((record, index) => (
              <div
                key={`${record.run_at}-${index}`}
                className={styles.historyItem}
              >
                <div className={styles.historyItemMain}>
                  <span className={styles.historyItemTime}>
                    {dayjs(record.run_at)
                      .tz(userTimezone)
                      .format("YYYY-MM-DD HH:mm:ss")}
                  </span>
                  <span
                    className={`${styles.historyItemStatus} ${
                      record.status === "success"
                        ? styles.historyItemStatusSuccess
                        : styles.historyItemStatusError
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
                <div className={styles.historyItemMeta}>
                  {record.trigger === "manual"
                    ? t("cronJobs.historyTriggerManual")
                    : t("cronJobs.historyTriggerScheduled")}
                </div>
                {record.error &&
                  (() => {
                    const recordKey = `${record.run_at}-${index}`;
                    const expanded = expandedHistoryErrors.has(recordKey);
                    const showToggle = shouldShowErrorToggle(record.error);
                    return (
                      <div>
                        <div
                          className={`${styles.historyItemError} ${
                            !expanded && showToggle
                              ? styles.historyItemErrorCollapsed
                              : ""
                          }`}
                        >
                          {record.error}
                        </div>
                        {showToggle && (
                          <button
                            type="button"
                            className={styles.historyItemErrorToggle}
                            onClick={() => toggleHistoryError(recordKey)}
                          >
                            {expanded
                              ? t("cronJobs.historyCollapse")
                              : t("cronJobs.historyExpand")}
                          </button>
                        )}
                      </div>
                    );
                  })()}
              </div>
            ))
          )}
        </div>
      </Modal>
    </div>
  );
}

export default CronJobsPage;
