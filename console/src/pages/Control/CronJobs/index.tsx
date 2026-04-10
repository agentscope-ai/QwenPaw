import { useState, useEffect, useRef } from "react";
import { Button, Card, Form, Modal, Table } from "@agentscope-ai/design";
import dayjs from "dayjs";
import type { CronJobSpecInput, CronJobSpecOutput } from "../../../api/types";
import { useTranslation } from "react-i18next";
import api from "../../../api";
import { useAppMessage } from "../../../hooks/useAppMessage";
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
type CronJobFormValues = CronJobSpecInput & {
  cronType?: string;
  cronTime?: dayjs.Dayjs;
  cronDaysOfWeek?: string[];
  cronCustom?: string;
  sessionStrategy?: "dispatch" | "new_per_run";
};

function CronJobsPage() {
  const { t } = useTranslation();
  const { message } = useAppMessage();
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
  const [form] = Form.useForm<CronJob>();
  const userTimezoneRef = useRef("UTC");

  useEffect(() => {
    api
      .getUserTimezone()
      .then((res) => {
        if (res.timezone) userTimezoneRef.current = res.timezone;
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

    // Parse cron expression to form fields
    const cronParts = parseCron(job.schedule?.cron || "0 9 * * *");

    const formValues: any = {
      ...job,
      request: {
        ...job.request,
        input: job.request?.input
          ? JSON.stringify(job.request.input, null, 2)
          : "",
      },
      cronType: cronParts.type,
      sessionStrategy: job.execution?.session?.mode || "dispatch",
    };

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

  const handleSubmit = async (values: CronJobFormValues) => {
    // Serialize cron from form fields
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

    const cronExpression = serializeCron(cronParts);

    let processedValues: CronJobSpecInput = {
      ...values,
      schedule: {
        ...values.schedule,
        cron: cronExpression,
      },
      execution: {
        session: {
          mode: values.sessionStrategy || "dispatch",
        },
      },
    };

    delete (processedValues as any).sessionStrategy;
    if (processedValues.request) {
      delete (processedValues.request as any).session_id;
      delete (processedValues.request as any).user_id;
    }

    if (processedValues.task_type === "text") {
      delete (processedValues as any).request;
    }

    if (processedValues.task_type === "agent") {
      delete (processedValues as any).text;

      // Parse request input JSON
      if (values.request?.input && typeof values.request.input === "string") {
        try {
          processedValues = {
            ...processedValues,
            request: {
              ...(processedValues.request || {}),
              input: JSON.parse(values.request.input as any),
            },
          };
        } catch (error) {
          console.error("❌ Failed to parse request.input JSON:", error);
          message.error(t("cronJobs.invalidJsonFormat"));
          return;
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
    onEdit: handleEdit,
    onDelete: handleDelete,
    t,
  });

  return (
    <div className={styles.cronJobsPage}>
      <PageHeader
        items={[{ title: t("nav.control") }, { title: t("cronJobs.title") }]}
        extra={
          <Button type="primary" onClick={handleCreate}>
            + {t("cronJobs.createJob")}
          </Button>
        }
      />

      <Card className={styles.tableCard} bodyStyle={{ padding: 0 }}>
        <Table
          columns={columns}
          dataSource={jobs}
          loading={loading}
          rowKey="id"
          scroll={{ x: 2840 }}
          pagination={{
            pageSize: 10,
          }}
        />
      </Card>

      <JobDrawer
        open={drawerOpen}
        editingJob={editingJob}
        form={form}
        saving={saving}
        onClose={handleDrawerClose}
        onSubmit={handleSubmit}
      />
    </div>
  );
}

export default CronJobsPage;
