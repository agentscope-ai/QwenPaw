import { request } from "../request";
import type {
  CronJobSpecInput,
  CronJobSpecOutput,
  CronJobView,
} from "../types";

export const cronJobApi = {
  listCronJobs: () => request<CronJobSpecOutput[]>("/cron/jobs"),

  createCronJob: (spec: CronJobSpecInput) =>
    request<CronJobSpecOutput>("/cron/jobs", {
      method: "POST",
      body: JSON.stringify(spec),
    }),

  getCronJob: (jobId: string) =>
    request<CronJobView>(`/cron/jobs/${encodeURIComponent(jobId)}`),

  replaceCronJob: (jobId: string, spec: CronJobSpecInput) =>
    request<CronJobSpecOutput>(`/cron/jobs/${encodeURIComponent(jobId)}`, {
      method: "PUT",
      body: JSON.stringify(spec),
    }),

  deleteCronJob: (jobId: string) =>
    request<void>(`/cron/jobs/${encodeURIComponent(jobId)}`, {
      method: "DELETE",
    }),

  pauseCronJob: (jobId: string) =>
    request<void>(`/cron/jobs/${encodeURIComponent(jobId)}/pause`, {
      method: "POST",
    }),

  resumeCronJob: (jobId: string) =>
    request<void>(`/cron/jobs/${encodeURIComponent(jobId)}/resume`, {
      method: "POST",
    }),

  runCronJob: (jobId: string) =>
    request<void>(`/cron/jobs/${encodeURIComponent(jobId)}/run`, {
      method: "POST",
    }),

  triggerCronJob: (jobId: string) =>
    request<void>(`/cron/jobs/${encodeURIComponent(jobId)}/run`, {
      method: "POST",
    }),

  getCronJobState: (jobId: string) =>
    request<unknown>(`/cron/jobs/${encodeURIComponent(jobId)}/state`),
};
