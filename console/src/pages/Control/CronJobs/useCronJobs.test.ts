import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { CronJobSpecOutput } from "../../../api/types";

// ---- Hoisted mocks ----

const mockApi = vi.hoisted(() => ({
  listCronJobs: vi.fn(),
  createCronJob: vi.fn(),
  replaceCronJob: vi.fn(),
  deleteCronJob: vi.fn(),
  triggerCronJob: vi.fn(),
}));

const mockMessage = vi.hoisted(() => ({
  success: vi.fn(),
  error: vi.fn(),
  warning: vi.fn(),
  info: vi.fn(),
}));

vi.mock("../../../stores/agentStore", () => ({
  useAgentStore: () => ({ selectedAgent: "agent-1" }),
}));

vi.mock("../../../hooks/useAppMessage", () => ({
  useAppMessage: () => ({ message: mockMessage }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

vi.mock("../../../api", () => ({
  default: mockApi,
}));

import { useCronJobs } from "./useCronJobs";

const mockCronJobs: CronJobSpecOutput[] = [
  {
    id: "job-1",
    name: "Daily Report",
    enabled: true,
    schedule: { type: "cron", cron: "0 9 * * *" },
    task_type: "text",
    text: "Generate daily report",
    dispatch: {
      type: "channel",
      target: { user_id: "u1", session_id: "s1" },
    },
  },
  {
    id: "job-2",
    name: "Weekly Cleanup",
    enabled: false,
    schedule: { type: "cron", cron: "0 0 * * 0" },
    task_type: "text",
    text: "Clean up old data",
    dispatch: {
      type: "channel",
      target: { user_id: "u1", session_id: "s1" },
    },
  },
];

describe("useCronJobs (#2250 + A#80724854 编辑/批量操作)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockApi.listCronJobs.mockResolvedValue([...mockCronJobs]);
  });

  describe("编辑功能 (#2250)", () => {
    it("updateJob 成功后用 API 返回值更新列表", async () => {
      const updatedJob = { ...mockCronJobs[0], name: "Updated Report" };
      mockApi.replaceCronJob.mockResolvedValue(updatedJob);

      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });

      let success = false;
      await act(async () => {
        success = await result.current.updateJob("job-1", {
          ...mockCronJobs[0],
          name: "Updated Report",
        } as CronJobSpecOutput);
      });

      expect(success).toBe(true);
      expect(mockApi.replaceCronJob).toHaveBeenCalledWith(
        "job-1",
        expect.objectContaining({ name: "Updated Report" }),
      );
      expect(result.current.jobs.find((j) => j.id === "job-1")!.name).toBe(
        "Updated Report",
      );
      expect(mockMessage.success).toHaveBeenCalledWith("Updated successfully");
    });

    it("updateJob 失败后回滚到原始数据（乐观更新回滚）", async () => {
      mockApi.replaceCronJob.mockRejectedValue(
        new Error('Network error - {"detail":"save failed"}'),
      );

      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });

      const originalName = result.current.jobs.find(
        (j) => j.id === "job-1",
      )!.name;

      let success = false;
      await act(async () => {
        success = await result.current.updateJob("job-1", {
          ...mockCronJobs[0],
          name: "Will Fail",
        } as CronJobSpecOutput);
      });

      expect(success).toBe(false);
      expect(result.current.jobs.find((j) => j.id === "job-1")!.name).toBe(
        originalName,
      );
      expect(mockMessage.error).toHaveBeenCalled();
    });

    it("toggleEnabled 乐观更新 enabled 状态", async () => {
      const toggledJob = { ...mockCronJobs[0], enabled: false };
      mockApi.replaceCronJob.mockResolvedValue(toggledJob);

      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });

      expect(result.current.jobs.find((j) => j.id === "job-1")!.enabled).toBe(
        true,
      );

      await act(async () => {
        await result.current.toggleEnabled(mockCronJobs[0]);
      });

      expect(result.current.jobs.find((j) => j.id === "job-1")!.enabled).toBe(
        false,
      );
    });

    it("toggleEnabled 失败后回滚 enabled 状态", async () => {
      mockApi.replaceCronJob.mockRejectedValue(new Error("Server error"));

      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });

      await act(async () => {
        await result.current.toggleEnabled(mockCronJobs[0]);
      });

      expect(result.current.jobs.find((j) => j.id === "job-1")!.enabled).toBe(
        true,
      );
      expect(mockMessage.error).toHaveBeenCalledWith("Operation failed");
    });
  });

  describe("批量操作后状态更新 (A#80724854)", () => {
    it("deleteJob 成功后从列表中移除", async () => {
      mockApi.deleteCronJob.mockResolvedValue(undefined);

      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });

      let success = false;
      await act(async () => {
        success = await result.current.deleteJob("job-1");
      });

      expect(success).toBe(true);
      expect(result.current.jobs).toHaveLength(1);
      expect(result.current.jobs[0].id).toBe("job-2");
      expect(mockMessage.success).toHaveBeenCalledWith("Deleted successfully");
    });

    it("deleteJob 失败后恢复已删除的 job", async () => {
      mockApi.deleteCronJob.mockRejectedValue(new Error("Delete failed"));

      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });

      let success = false;
      await act(async () => {
        success = await result.current.deleteJob("job-1");
      });

      expect(success).toBe(false);
      expect(result.current.jobs).toHaveLength(2);
      expect(mockMessage.error).toHaveBeenCalledWith("Failed to delete");
    });

    it("createJob 成功后新 job 插入列表头部", async () => {
      const newJob: CronJobSpecOutput = {
        id: "job-3",
        name: "New Job",
        enabled: true,
        schedule: { type: "cron", cron: "0 12 * * *" },
        task_type: "text",
        text: "New task",
        dispatch: {
          type: "channel",
          target: { user_id: "u1", session_id: "s1" },
        },
      };
      mockApi.createCronJob.mockResolvedValue(newJob);

      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });

      let success = false;
      await act(async () => {
        success = await result.current.createJob(newJob);
      });

      expect(success).toBe(true);
      expect(result.current.jobs).toHaveLength(3);
      expect(result.current.jobs[0].id).toBe("job-3");
      expect(mockMessage.success).toHaveBeenCalledWith("Created successfully");
    });

    it("executeNow 触发成功后不改变 job 列表", async () => {
      mockApi.triggerCronJob.mockResolvedValue(undefined);

      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });

      let success = false;
      await act(async () => {
        success = await result.current.executeNow("job-1");
      });

      expect(success).toBe(true);
      expect(result.current.jobs).toHaveLength(2);
      expect(mockMessage.success).toHaveBeenCalledWith(
        "Task triggered successfully",
      );
    });
  });
});
