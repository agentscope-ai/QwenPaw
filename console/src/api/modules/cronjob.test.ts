import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

vi.mock("../request", () => ({
  request: vi.fn(),
}));

import { cronJobApi } from "./cronjob";
import { request } from "../request";

describe("cronJobApi", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("listCronJobs calls GET /cron/jobs", async () => {
    const jobs = [{ id: "job-1", name: "backup" }];
    vi.mocked(request).mockResolvedValue(jobs);
    const result = await cronJobApi.listCronJobs();
    expect(request).toHaveBeenCalledWith("/cron/jobs");
    expect(result).toEqual(jobs);
  });

  it("createCronJob sends POST to /cron/jobs with spec body", async () => {
    const spec = { name: "cleanup", cron_expression: "0 * * * *" } as any;
    const created = { ...spec, id: "job-2" };
    vi.mocked(request).mockResolvedValue(created);
    const result = await cronJobApi.createCronJob(spec);
    expect(request).toHaveBeenCalledWith("/cron/jobs", {
      method: "POST",
      body: JSON.stringify(spec),
    });
    expect(result).toEqual(created);
  });

  it("getCronJob calls GET with encoded jobId", async () => {
    const job = { id: "job/special", name: "test" };
    vi.mocked(request).mockResolvedValue(job);
    const result = await cronJobApi.getCronJob("job/special");
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job/special")}`,
    );
    expect(result).toEqual(job);
  });

  it("replaceCronJob sends PUT with encoded jobId and spec body", async () => {
    const spec = { name: "updated", cron_expression: "*/5 * * * *" } as any;
    await cronJobApi.replaceCronJob("job-1", spec);
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job-1")}`,
      {
        method: "PUT",
        body: JSON.stringify(spec),
      },
    );
  });

  it("deleteCronJob sends DELETE with encoded jobId", async () => {
    await cronJobApi.deleteCronJob("job-1");
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job-1")}`,
      {
        method: "DELETE",
      },
    );
  });

  it("pauseCronJob sends POST to /pause endpoint", async () => {
    await cronJobApi.pauseCronJob("job-1");
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job-1")}/pause`,
      { method: "POST" },
    );
  });

  it("resumeCronJob sends POST to /resume endpoint", async () => {
    await cronJobApi.resumeCronJob("job-1");
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job-1")}/resume`,
      { method: "POST" },
    );
  });

  it("runCronJob sends POST to /run endpoint", async () => {
    await cronJobApi.runCronJob("job-1");
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job-1")}/run`,
      { method: "POST" },
    );
  });
});

describe("cronJobApi branches", () => {
  beforeEach(() => {
    vi.mocked(request).mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("triggerCronJob posts to the run endpoint", async () => {
    await cronJobApi.triggerCronJob("job-9");
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job-9")}/run`,
      { method: "POST" },
    );
  });

  it("getCronJobState reads the state endpoint", async () => {
    await cronJobApi.getCronJobState("job-9");
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job-9")}/state`,
    );
  });

  it("getCronJobHistory reads the history endpoint", async () => {
    const records = [{ run_id: "r1" }];
    vi.mocked(request).mockResolvedValue(records);
    const result = await cronJobApi.getCronJobHistory("job-9");
    expect(request).toHaveBeenCalledWith(
      `/cron/jobs/${encodeURIComponent("job-9")}/history`,
    );
    expect(result).toEqual(records);
  });

  it("listCronDispatchTargets appends both query params", async () => {
    await cronJobApi.listCronDispatchTargets({
      channel: "web",
      keyword: "report",
    });
    expect(request).toHaveBeenCalledWith(
      "/cron/dispatch-targets?channel=web&keyword=report",
    );
  });

  it("listCronDispatchTargets omits empty filters", async () => {
    await cronJobApi.listCronDispatchTargets({});
    expect(request).toHaveBeenCalledWith("/cron/dispatch-targets");
    await cronJobApi.listCronDispatchTargets();
    expect(request).toHaveBeenCalledWith("/cron/dispatch-targets");
  });

  it("listCronDispatchTargets accepts a single filter", async () => {
    await cronJobApi.listCronDispatchTargets({ keyword: "nightly" });
    expect(request).toHaveBeenCalledWith(
      "/cron/dispatch-targets?keyword=nightly",
    );
  });
});
