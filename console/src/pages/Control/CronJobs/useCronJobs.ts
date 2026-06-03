import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { CronJobSpecOutput } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";
import { parseErrorDetail } from "../../../utils/error";

type CronJob = CronJobSpecOutput;

export function useCronJobs() {
  const { selectedAgent } = useAgentStore();
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(false);
  const { message } = useAppMessage();
  const { t } = useTranslation();

  const getDisplayErrorMessage = (error: unknown, fallback: string): string => {
    const normalizeMessage = (raw: string): string => {
      const cleaned = raw.replace(/^Value error,\s*/i, "").trim();
      if (cleaned.includes("schedule.type is cron but cron is empty")) {
        return t("cronJobs.validation.cronRequired");
      }
      if (cleaned.includes("schedule.type is once but run_at is missing")) {
        return t("cronJobs.validation.runAtRequired");
      }
      if (
        cleaned.includes("repeat_end_type is until but repeat_until is missing")
      ) {
        return t("cronJobs.validation.repeatUntilRequired");
      }
      if (
        cleaned.includes("repeat_end_type is count but repeat_count is missing")
      ) {
        return t("cronJobs.validation.repeatCountRequired");
      }
      if (cleaned.includes("repeat_until must be later than run_at")) {
        return t("cronJobs.validation.repeatUntilAfterRunAt");
      }
      if (cleaned.includes("task_type is text but text is empty")) {
        return t("cronJobs.validation.textRequired");
      }
      if (cleaned.includes("task_type is agent but request is missing")) {
        return t("cronJobs.validation.requestRequired");
      }
      if (cleaned.includes("cron must have 5 fields")) {
        return t("cronJobs.validation.invalidCronExpression");
      }
      return cleaned;
    };

    const detail = parseErrorDetail(error) as unknown;
    if (typeof detail === "string" && detail.trim()) {
      return normalizeMessage(detail);
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (typeof first === "string" && first.trim()) {
        return normalizeMessage(first);
      }
      if (first && typeof first === "object") {
        const firstObj = first as { msg?: unknown; message?: unknown };
        if (typeof firstObj.msg === "string" && firstObj.msg.trim()) {
          return normalizeMessage(firstObj.msg);
        }
        if (typeof firstObj.message === "string" && firstObj.message.trim()) {
          return normalizeMessage(firstObj.message);
        }
      }
    }
    if (detail && typeof detail === "object") {
      const detailObj = detail as {
        message?: unknown;
        detail?: unknown;
        msg?: unknown;
      };
      if (typeof detailObj.message === "string" && detailObj.message.trim()) {
        return normalizeMessage(detailObj.message);
      }
      if (typeof detailObj.msg === "string" && detailObj.msg.trim()) {
        return normalizeMessage(detailObj.msg);
      }
      if (typeof detailObj.detail === "string" && detailObj.detail.trim()) {
        return normalizeMessage(detailObj.detail);
      }
    }
    if (error instanceof Error && error.message) {
      const separatorIndex = error.message.indexOf(" - ");
      const messageText =
        separatorIndex >= 0
          ? error.message.slice(0, separatorIndex)
          : error.message;
      return normalizeMessage(messageText);
    }
    return fallback;
  };

  const fetchJobs = async () => {
    setLoading(true);
    try {
      const data = await api.listCronJobs();
      if (data) {
        setJobs(data as CronJob[]);
      }
    } catch (error) {
      console.error("Failed to load cron jobs", error);
      message.error("Failed to load Cron Jobs");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    let mounted = true;

    const loadJobs = async () => {
      await fetchJobs();
    };

    if (mounted) {
      loadJobs();
    }

    return () => {
      mounted = false;
    };
  }, [selectedAgent]);

  const createJob = async (values: CronJob) => {
    try {
      const created = await api.createCronJob(values);
      setJobs((prev) => [created as CronJob, ...prev]);
      message.success("Created successfully");
      return true;
    } catch (error) {
      console.error("Failed to create cron job", error);
      message.error(getDisplayErrorMessage(error, "Failed to save"));
      return false;
    }
  };

  const updateJob = async (jobId: string, values: CronJob) => {
    const original = jobs.find((j) => j.id === jobId);
    const optimisticUpdate = { ...original, ...values };
    setJobs((prev) => prev.map((j) => (j.id === jobId ? optimisticUpdate : j)));

    try {
      const updated = await api.replaceCronJob(jobId, values);
      setJobs((prev) =>
        prev.map((j) => (j.id === jobId ? (updated as CronJob) : j)),
      );
      message.success("Updated successfully");
      return true;
    } catch (error) {
      console.error("Failed to update cron job", error);
      if (original) {
        setJobs((prev) => prev.map((j) => (j.id === jobId ? original : j)));
      }
      message.error(getDisplayErrorMessage(error, "Failed to save"));
      return false;
    }
  };

  const deleteJob = async (jobId: string) => {
    const original = jobs.find((j) => j.id === jobId);
    setJobs((prev) => prev.filter((j) => j.id !== jobId));

    try {
      await api.deleteCronJob(jobId);
      message.success("Deleted successfully");
      return true;
    } catch (error) {
      console.error("Failed to delete cron job", error);
      if (original) {
        setJobs((prev) => [...prev, original]);
      }
      message.error("Failed to delete");
      return false;
    }
  };

  const toggleEnabled = async (job: CronJob) => {
    const updated = { ...job, enabled: !job.enabled };
    setJobs((prev) => prev.map((j) => (j.id === job.id ? updated : j)));

    try {
      const returned = await api.replaceCronJob(job.id, updated);
      setJobs((prev) =>
        prev.map((j) => (j.id === job.id ? (returned as CronJob) : j)),
      );
      message.success(`${updated.enabled ? "Enabled" : "Disabled"}`);
      return true;
    } catch (error) {
      console.error("Failed to toggle cron job", error);
      setJobs((prev) => prev.map((j) => (j.id === job.id ? job : j)));
      message.error("Operation failed");
      return false;
    }
  };

  const executeNow = async (jobId: string) => {
    try {
      await api.triggerCronJob(jobId);
      message.success("Task triggered successfully");
      return true;
    } catch (error) {
      console.error("Failed to execute cron job", error);
      message.error("Failed to execute");
      return false;
    }
  };

  return {
    jobs,
    loading,
    createJob,
    updateJob,
    deleteJob,
    toggleEnabled,
    executeNow,
  };
}
