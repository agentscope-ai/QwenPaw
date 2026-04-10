import { useState, useEffect } from "react";
import { useAppMessage } from "../../../hooks/useAppMessage";
import api from "../../../api";
import type { CronJobSpecInput, CronJobSpecOutput } from "../../../api/types";
import { useAgentStore } from "../../../stores/agentStore";

type CronJob = CronJobSpecOutput;
type CronJobDraft = CronJobSpecInput;

export function useCronJobs() {
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

  const createJob = async (values: CronJobDraft) => {
    try {
      const created = await api.createCronJob(values);
      setJobs((prev) => [created as CronJob, ...prev]);
      message.success("Created successfully");
      return true;
    } catch (error) {
      console.error("Failed to create cron job", error);
      message.error("Failed to save");
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
      message.error("Failed to save");
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
