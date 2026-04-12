import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { CronJobSpecInput, CronJobSpecOutput } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";

type CronJob = CronJobSpecOutput;
type CronJobDraft = CronJobSpecInput;

export function useCronJobs() {
  const { t } = useTranslation();
  const { selectedAgent } = useAgentStore();
  const [jobs, setJobs] = useState<CronJob[]>([]);
  const [loading, setLoading] = useState(false);
  const { message } = useAppMessage();

  const fetchJobs = async () => {
    setLoading(true);
    try {
      const data = await api.listCronJobs();
      if (data) {
        setJobs(data as CronJob[]);
      }
    } catch (error) {
      console.error("Failed to load cron jobs", error);
      message.error(t("cronJobs.loadFailed"));
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

  const createJob = async (values: CronJobDraft) => {
    try {
      const created = await api.createCronJob(values);
      setJobs((prev) => [created as CronJob, ...prev]);
      message.success(t("cronJobs.createSuccess"));
      return true;
    } catch (error) {
      console.error("Failed to create cron job", error);
      message.error(t("cronJobs.saveFailed"));
      return false;
    }
  };

  const updateJob = async (jobId: string, values: CronJobDraft) => {
    const original = jobs.find((j) => j.id === jobId);
    const optimisticUpdate = original
      ? ({ ...original, ...values, id: jobId } as CronJob)
      : null;
    if (optimisticUpdate) {
      setJobs((prev) => prev.map((j) => (j.id === jobId ? optimisticUpdate : j)));
    }

    try {
      const payload = { ...values, id: jobId };
      const updated = await api.replaceCronJob(jobId, payload);
      setJobs((prev) =>
        prev.map((j) => (j.id === jobId ? (updated as CronJob) : j)),
      );
      message.success(t("cronJobs.updateSuccess"));
      return true;
    } catch (error) {
      console.error("Failed to update cron job", error);
      if (original) {
        setJobs((prev) => prev.map((j) => (j.id === jobId ? original : j)));
      }
      message.error(t("cronJobs.saveFailed"));
      return false;
    }
  };

  const deleteJob = async (jobId: string) => {
    const original = jobs.find((j) => j.id === jobId);
    setJobs((prev) => prev.filter((j) => j.id !== jobId));

    try {
      await api.deleteCronJob(jobId);
      message.success(t("cronJobs.deleteSuccess"));
      return true;
    } catch (error) {
      console.error("Failed to delete cron job", error);
      if (original) {
        setJobs((prev) => [...prev, original]);
      }
      message.error(t("cronJobs.deleteFailed"));
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
      message.success(
        updated.enabled ? t("agent.enableSuccess") : t("agent.disableSuccess"),
      );
      return true;
    } catch (error) {
      console.error("Failed to toggle cron job", error);
      setJobs((prev) => prev.map((j) => (j.id === job.id ? job : j)));
      message.error(t("cronJobs.operationFailed"));
      return false;
    }
  };

  const executeNow = async (jobId: string) => {
    try {
      await api.triggerCronJob(jobId);
      message.success(t("cronJobs.executeNowSuccess"));
      return true;
    } catch (error) {
      console.error("Failed to execute cron job", error);
      message.error(t("cronJobs.executeNowFailed"));
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
