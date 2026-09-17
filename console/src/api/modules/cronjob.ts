import { request } from "../request";
import type {
  CronDispatchTargetsResponse,
  CronJobExecutionRecord,
  CronJobSpecInput,
  CronJobSpecOutput,
  CronJobView,
  AutomationAuthorizationPreview,
} from "../types";

export const cronJobApi = {
  listCronJobs: (scope: "mine" | "agent" = "mine") =>
    request<CronJobSpecOutput[]>(`/cron/jobs?scope=${scope}`),

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

  getCronJobHistory: (jobId: string) =>
    request<CronJobExecutionRecord[]>(
      `/cron/jobs/${encodeURIComponent(jobId)}/history`,
    ),

  getCronJobAuthorization: (jobId: string) =>
    request<AutomationAuthorizationPreview>(
      `/cron/jobs/${encodeURIComponent(jobId)}/authorization`,
    ),

  authorizeCronJob: (
    jobId: string,
    preview: Pick<
      AutomationAuthorizationPreview,
      "config_version" | "authorization_digest"
    >,
  ) =>
    request<CronJobSpecOutput>(
      `/cron/jobs/${encodeURIComponent(jobId)}/authorize`,
      {
        method: "POST",
        body: JSON.stringify(preview),
      },
    ),

  revokeCronJobAuthorization: (jobId: string) =>
    request<CronJobSpecOutput>(
      `/cron/jobs/${encodeURIComponent(jobId)}/revoke`,
      { method: "POST" },
    ),

  listCronDispatchTargets: (params?: {
    channel?: string;
    keyword?: string;
  }) => {
    const searchParams = new URLSearchParams();
    if (params?.channel) searchParams.append("channel", params.channel);
    if (params?.keyword) searchParams.append("keyword", params.keyword);
    const query = searchParams.toString();
    return request<CronDispatchTargetsResponse>(
      `/cron/dispatch-targets${query ? `?${query}` : ""}`,
    );
  },
};
