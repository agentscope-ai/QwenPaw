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
  promoteCronJob: vi.fn(),
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
      // The rollback must put the row back where it was: the list has no
      // column sorters, so array order is the order the table renders.
      expect(result.current.jobs.map((j) => j.id)).toEqual(["job-1", "job-2"]);
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

  describe("导入待审门禁 (import review gate)", () => {
    // A quarantined imported job: meta.portability.requires_review drives the
    // gate, and dispatch.meta / meta must survive an edit untouched.
    const reviewJob = {
      id: "job-review",
      name: "Imported Job",
      enabled: false,
      schedule: { type: "cron", cron: "0 9 * * *" },
      task_type: "text",
      text: "imported task",
      dispatch: {
        type: "channel",
        target: { user_id: "u1", session_id: "s1" },
        meta: { dispatch_original: true },
      },
      meta: { portability: { requires_review: true, source: "import" } },
      request: {
        input: "original input",
        request_context: {
          project_dir: "  /original/dir  ",
          imported_flag: "keep-me",
        },
      },
    } as unknown as CronJobSpecOutput;

    beforeEach(() => {
      mockApi.listCronJobs.mockResolvedValue([reviewJob]);
    });

    it("toggleEnabled 被门禁拦截：不发请求且列表不变", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      let ok = true;
      await act(async () => {
        ok = await result.current.toggleEnabled(reviewJob);
      });

      expect(ok).toBe(false);
      expect(mockApi.replaceCronJob).not.toHaveBeenCalled();
      expect(mockMessage.error).toHaveBeenCalledWith(
        "cronJobs.importReviewBlocked",
      );
      expect(result.current.jobs[0].enabled).toBe(false);
    });

    it("executeNow 被门禁拦截：不触发任务", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      let ok = true;
      await act(async () => {
        ok = await result.current.executeNow("job-review");
      });

      expect(ok).toBe(false);
      expect(mockApi.triggerCronJob).not.toHaveBeenCalled();
      expect(mockMessage.error).toHaveBeenCalledWith(
        "cronJobs.importReviewBlocked",
      );
    });

    it("executeNow 找不到 job 时不发请求也不报错", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));
      mockApi.triggerCronJob.mockResolvedValue(undefined);

      let ok = false;
      await act(async () => {
        ok = await result.current.executeNow("does-not-exist");
      });

      // The gate only fires for a job that exists and needs review; an unknown
      // id falls through to the api call.
      expect(ok).toBe(true);
      expect(mockApi.triggerCronJob).toHaveBeenCalledWith("does-not-exist");
      expect(mockMessage.error).not.toHaveBeenCalled();
    });
  });

  describe("受保护合并 mergeReviewPendingJob", () => {
    const reviewJob = {
      id: "job-review",
      name: "Imported Job",
      enabled: true,
      schedule: { type: "cron", cron: "0 9 * * *" },
      task_type: "text",
      text: "imported task",
      dispatch: {
        type: "channel",
        target: { user_id: "u1", session_id: "s1" },
        meta: { dispatch_original: true },
      },
      meta: { portability: { requires_review: true, source: "import" } },
      request: {
        input: "original input",
        request_context: {
          project_dir: "  /original/dir  ",
          imported_flag: "keep-me",
        },
      },
    } as unknown as CronJobSpecOutput;

    beforeEach(() => {
      mockApi.listCronJobs.mockResolvedValue([reviewJob]);
      mockApi.replaceCronJob.mockResolvedValue(reviewJob);
    });

    const payloadOf = () =>
      mockApi.replaceCronJob.mock.calls[0][1] as Record<string, any>;

    it("Ant Form 只提交已注册字段时，保留 id／meta／dispatch.meta 并强制 enabled=false", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      await act(async () => {
        await result.current.updateJob("job-review", {
          // What a form actually submits: no id, no meta, no dispatch.meta.
          name: "Renamed",
          enabled: true,
          schedule: { type: "cron", cron: "0 10 * * *" },
          task_type: "text",
          text: "edited",
          dispatch: {
            type: "channel",
            target: { user_id: "u1", session_id: "s1" },
          },
        } as unknown as CronJobSpecOutput);
      });

      const payload = payloadOf();
      // A plain shallow replace would have erased these.
      expect(payload.id).toBe("job-review");
      expect(payload.meta).toEqual(reviewJob.meta);
      expect(payload.dispatch.meta).toEqual({ dispatch_original: true });
      expect(payload.enabled).toBe(false);
      expect(payload.name).toBe("Renamed");
    });

    it("project_dir 是唯一可被表单覆盖的请求上下文字段，且会被 trim", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      await act(async () => {
        await result.current.updateJob("job-review", {
          name: "Renamed",
          schedule: { type: "cron", cron: "0 9 * * *" },
          dispatch: {
            type: "channel",
            target: { user_id: "u1", session_id: "s1" },
          },
          request: {
            input: "new input",
            request_context: { project_dir: "  /new/dir  " },
          },
        } as unknown as CronJobSpecOutput);
      });

      const ctx = payloadOf().request.request_context;
      expect(ctx.project_dir).toBe("/new/dir");
      // Migration metadata is immutable: a field the form never submitted must
      // survive from the original.
      expect(ctx.imported_flag).toBe("keep-me");
      expect(payloadOf().request.input).toBe("new input");
    });

    it("表单未提交 project_dir 时沿用原值", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      await act(async () => {
        await result.current.updateJob("job-review", {
          name: "Renamed",
          schedule: { type: "cron", cron: "0 9 * * *" },
          dispatch: {
            type: "channel",
            target: { user_id: "u1", session_id: "s1" },
          },
          request: { input: "x", request_context: {} },
        } as unknown as CronJobSpecOutput);
      });

      expect(payloadOf().request.request_context.project_dir).toBe(
        "  /original/dir  ",
      );
    });

    it("非字符串 project_dir 原样保留", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      await act(async () => {
        await result.current.updateJob("job-review", {
          name: "Renamed",
          schedule: { type: "cron", cron: "0 9 * * *" },
          dispatch: {
            type: "channel",
            target: { user_id: "u1", session_id: "s1" },
          },
          request: { input: "x", request_context: { project_dir: 42 } },
        } as unknown as CronJobSpecOutput);
      });

      expect(payloadOf().request.request_context.project_dir).toBe(42);
    });

    it("原值与表单都没有 request 时合并结果为 undefined", async () => {
      const noRequest = {
        ...reviewJob,
        request: undefined,
      } as unknown as CronJobSpecOutput;
      mockApi.listCronJobs.mockResolvedValue([noRequest]);

      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      await act(async () => {
        await result.current.updateJob("job-review", {
          name: "Renamed",
          schedule: { type: "cron", cron: "0 9 * * *" },
          dispatch: {
            type: "channel",
            target: { user_id: "u1", session_id: "s1" },
          },
        } as unknown as CronJobSpecOutput);
      });

      expect(payloadOf().request).toBeUndefined();
    });

    it("input 缺失时回退到原 request.input", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      await act(async () => {
        await result.current.updateJob("job-review", {
          name: "Renamed",
          schedule: { type: "cron", cron: "0 9 * * *" },
          dispatch: {
            type: "channel",
            target: { user_id: "u1", session_id: "s1" },
          },
          request: { request_context: { project_dir: "/p" } },
        } as unknown as CronJobSpecOutput);
      });

      expect(payloadOf().request.input).toBe("original input");
    });

    it("非待审任务不走受保护合并，直接提交表单值", async () => {
      mockApi.listCronJobs.mockResolvedValue([{ ...mockCronJobs[0] }]);
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      const values = {
        ...mockCronJobs[0],
        name: "Plain edit",
      } as CronJobSpecOutput;
      await act(async () => {
        await result.current.updateJob("job-1", values);
      });

      // Without the review gate the payload is exactly what the form gave.
      expect(mockApi.replaceCronJob).toHaveBeenCalledWith("job-1", values);
    });

    it("updateJob 找不到原 job 时仍能提交表单值", async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      const values = { id: "ghost", name: "x" } as unknown as CronJobSpecOutput;
      let ok = false;
      await act(async () => {
        ok = await result.current.updateJob("ghost", values);
      });

      expect(ok).toBe(true);
      expect(mockApi.replaceCronJob).toHaveBeenCalledWith("ghost", values);
    });
  });

  describe("promoteImportedJob (导入任务晋级)", () => {
    const reviewJob = (over: Record<string, unknown> = {}) =>
      ({
        id: "job-review",
        name: "Imported Job",
        enabled: false,
        schedule: { type: "cron", cron: "0 9 * * *" },
        task_type: "text",
        text: "imported",
        dispatch: {
          type: "channel",
          target: { user_id: "u1", session_id: "s1" },
        },
        meta: { portability: { requires_review: true } },
        request: {
          input: "in",
          request_context: { project_dir: "/mapped/dir" },
        },
        ...over,
      }) as unknown as CronJobSpecOutput;

    it("非待审任务直接返回 false 且不调用晋级接口", async () => {
      mockApi.listCronJobs.mockResolvedValue([...mockCronJobs]);
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(2));

      let ok = true;
      await act(async () => {
        ok = await result.current.promoteImportedJob("job-1");
      });

      expect(ok).toBe(false);
      expect(mockApi.promoteCronJob).not.toHaveBeenCalled();
    });

    it("找不到 job 时返回 false", async () => {
      mockApi.listCronJobs.mockResolvedValue([reviewJob()]);
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      let ok = true;
      await act(async () => {
        ok = await result.current.promoteImportedJob("ghost");
      });

      expect(ok).toBe(false);
      expect(mockApi.promoteCronJob).not.toHaveBeenCalled();
    });

    it("需要本地项目映射但缺 project_dir 时拒绝晋级", async () => {
      const job = reviewJob({
        meta: {
          portability: {
            requires_review: true,
            source_cwd_remote_or_unverified: true,
          },
        },
        request: { input: "in", request_context: {} },
      });
      mockApi.listCronJobs.mockResolvedValue([job]);
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      let ok = true;
      await act(async () => {
        ok = await result.current.promoteImportedJob("job-review");
      });

      expect(ok).toBe(false);
      expect(mockApi.promoteCronJob).not.toHaveBeenCalled();
      expect(mockMessage.error).toHaveBeenCalledWith(
        "cronJobs.importReviewProjectDirRequired",
      );
    });

    it("project_dir 只有空白字符时同样视为缺失", async () => {
      const job = reviewJob({
        meta: {
          portability: {
            requires_review: true,
            source_cwd_binding: "omitted_remote_or_unverified",
          },
        },
        request: { input: "in", request_context: { project_dir: "   " } },
      });
      mockApi.listCronJobs.mockResolvedValue([job]);
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      let ok = true;
      await act(async () => {
        ok = await result.current.promoteImportedJob("job-review");
      });

      expect(ok).toBe(false);
      expect(mockApi.promoteCronJob).not.toHaveBeenCalled();
      expect(mockMessage.error).toHaveBeenCalledWith(
        "cronJobs.importReviewProjectDirRequired",
      );
    });

    it("晋级期间登记 promotingJobIds，成功后清除并写回返回值", async () => {
      let release!: (v: unknown) => void;
      mockApi.promoteCronJob.mockReturnValue(
        new Promise((resolve) => {
          release = resolve;
        }),
      );
      const promoted = reviewJob({
        name: "Promoted",
        meta: { portability: { requires_review: false } },
      });
      mockApi.listCronJobs.mockResolvedValue([reviewJob()]);

      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));
      expect(result.current.promotingJobIds.size).toBe(0);

      let pending!: Promise<boolean>;
      act(() => {
        pending = result.current.promoteImportedJob("job-review");
      });

      await vi.waitFor(() =>
        expect(result.current.promotingJobIds.has("job-review")).toBe(true),
      );

      await act(async () => {
        release(promoted);
        await pending;
      });

      expect(await pending).toBe(true);
      expect(mockApi.promoteCronJob).toHaveBeenCalledWith("job-review");
      expect(result.current.jobs[0].name).toBe("Promoted");
      expect(mockMessage.success).toHaveBeenCalledWith(
        "cronJobs.importReviewSuccess",
      );
      // The finally block must clear the in-flight marker.
      expect(result.current.promotingJobIds.has("job-review")).toBe(false);
    });

    it("晋级失败时报错并仍清除 promotingJobIds", async () => {
      mockApi.promoteCronJob.mockRejectedValue(
        new Error(
          'Bad Request - {"detail":"Value error, cron must have 5 fields"}',
        ),
      );
      mockApi.listCronJobs.mockResolvedValue([reviewJob()]);

      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      let ok = true;
      await act(async () => {
        ok = await result.current.promoteImportedJob("job-review");
      });

      expect(ok).toBe(false);
      expect(mockMessage.error).toHaveBeenCalledWith(
        "cronJobs.validation.invalidCronExpression",
      );
      expect(result.current.promotingJobIds.size).toBe(0);
    });

    it("晋级失败且错误无法解析时使用导入失败兜底文案", async () => {
      mockApi.promoteCronJob.mockRejectedValue("opaque");
      mockApi.listCronJobs.mockResolvedValue([reviewJob()]);

      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      await act(async () => {
        await result.current.promoteImportedJob("job-review");
      });

      expect(mockMessage.error).toHaveBeenCalledWith(
        "cronJobs.importReviewFailed",
      );
    });

    it("safety 标记同样触发待审门禁", async () => {
      const job = reviewJob({
        meta: {
          portability: { safety: "disabled_until_explicit_promotion" },
        },
      });
      mockApi.listCronJobs.mockResolvedValue([job]);
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(1));

      let ok = true;
      await act(async () => {
        ok = await result.current.toggleEnabled(job);
      });

      expect(ok).toBe(false);
      expect(mockMessage.error).toHaveBeenCalledWith(
        "cronJobs.importReviewBlocked",
      );
    });
  });

  describe("getDisplayErrorMessage 后端校验文案归一化", () => {
    const failCreateWith = (error: unknown) => {
      mockApi.createCronJob.mockRejectedValue(error);
    };

    const createAndReadError = async () => {
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(2));
      let ok = true;
      await act(async () => {
        ok = await result.current.createJob(
          mockCronJobs[0] as CronJobSpecOutput,
        );
      });
      expect(ok).toBe(false);
      return mockMessage.error.mock.calls[0][0] as string;
    };

    it.each([
      [
        "Value error, schedule.type is cron but cron is empty",
        "cronJobs.validation.cronRequired",
      ],
      [
        "Value error, schedule.type is once but run_at is missing",
        "cronJobs.validation.runAtRequired",
      ],
      [
        "Value error, repeat_end_type is until but repeat_until is missing",
        "cronJobs.validation.repeatUntilRequired",
      ],
      [
        "Value error, repeat_end_type is count but repeat_count is missing",
        "cronJobs.validation.repeatCountRequired",
      ],
      [
        "Value error, repeat_until must be later than run_at",
        "cronJobs.validation.repeatUntilAfterRunAt",
      ],
      [
        "Value error, task_type is text but text is empty",
        "cronJobs.validation.textRequired",
      ],
      [
        "Value error, task_type is agent but request is missing",
        "cronJobs.validation.requestRequired",
      ],
      ["cron must have 5 fields", "cronJobs.validation.invalidCronExpression"],
    ])("字符串 detail「%s」映射为 %s", async (detail, expected) => {
      failCreateWith(
        new Error(`Bad Request - {"detail":${JSON.stringify(detail)}}`),
      );
      expect(await createAndReadError()).toBe(expected);
    });

    it("无法识别的 detail 原样透出（去掉 Value error 前缀）", async () => {
      failCreateWith(
        new Error(
          'Bad Request - {"detail":"Value error, something else broke"}',
        ),
      );
      expect(await createAndReadError()).toBe("something else broke");
    });

    it("detail 为字符串数组时取第一项", async () => {
      failCreateWith(
        new Error(
          'Bad Request - {"detail":["Value error, cron must have 5 fields"]}',
        ),
      );
      expect(await createAndReadError()).toBe(
        "cronJobs.validation.invalidCronExpression",
      );
    });

    it("detail 数组首项为对象时读 msg 字段", async () => {
      failCreateWith(
        new Error(
          'Bad Request - {"detail":[{"msg":"Value error, task_type is text but text is empty"}]}',
        ),
      );
      expect(await createAndReadError()).toBe(
        "cronJobs.validation.textRequired",
      );
    });

    it("detail 数组首项为对象时读 message 字段", async () => {
      failCreateWith(
        new Error(
          'Bad Request - {"detail":[{"message":"repeat_until must be later than run_at"}]}',
        ),
      );
      expect(await createAndReadError()).toBe(
        "cronJobs.validation.repeatUntilAfterRunAt",
      );
    });

    it("detail 为对象时依次尝试 message／msg／嵌套 detail", async () => {
      failCreateWith(new Error('Bad Request - {"message":"message field"}'));
      expect(await createAndReadError()).toBe("message field");
    });

    it("detail 为对象且只有 msg 时读 msg", async () => {
      failCreateWith(new Error('Bad Request - {"msg":"msg field"}'));
      expect(await createAndReadError()).toBe("msg field");
    });

    it("detail 为对象且只有嵌套 detail 字符串时读它", async () => {
      failCreateWith(
        new Error('Bad Request - {"detail":{"detail":"nested detail"}}'),
      );
      expect(await createAndReadError()).toBe("nested detail");
    });

    it("detail 为空字符串时回退到 Error.message", async () => {
      failCreateWith(new Error('Bad Request - {"detail":"   "}'));
      // The blank detail is skipped, so the raw message before the separator
      // is used instead.
      expect(await createAndReadError()).toBe("Bad Request");
    });

    it("Error.message 带分隔符但非 JSON 时取分隔符前半段", async () => {
      failCreateWith(new Error("Something broke - not json at all"));
      expect(await createAndReadError()).toBe("Something broke");
    });

    it("Error.message 无分隔符时整句透出", async () => {
      failCreateWith(new Error("plain failure"));
      expect(await createAndReadError()).toBe("plain failure");
    });

    it("非 Error 且无可解析内容时使用兜底文案", async () => {
      failCreateWith("opaque string");
      expect(await createAndReadError()).toBe("Failed to save");
    });

    it("updateJob 失败时同样归一化后端校验文案", async () => {
      mockApi.replaceCronJob.mockRejectedValue(
        new Error(
          'Bad Request - {"detail":"Value error, schedule.type is once but run_at is missing"}',
        ),
      );
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(2));

      let ok = true;
      await act(async () => {
        ok = await result.current.updateJob(
          "job-1",
          mockCronJobs[0] as CronJobSpecOutput,
        );
      });

      expect(ok).toBe(false);
      expect(mockMessage.error).toHaveBeenCalledWith(
        "cronJobs.validation.runAtRequired",
      );
    });
  });

  describe("加载与删除的边界分支", () => {
    it("listCronJobs 返回空值时不覆盖列表（保留初始空态）", async () => {
      // The `if (data)` guard: a falsy payload must not be written into state.
      // Use a persistent impl (re-established by beforeEach) so no once-queue
      // entry leaks into the next test.
      mockApi.listCronJobs.mockResolvedValue(null);
      const { result } = renderHook(() => useCronJobs());

      await vi.waitFor(() => expect(mockApi.listCronJobs).toHaveBeenCalled());
      await act(async () => {
        await Promise.resolve();
      });

      expect(result.current.jobs).toEqual([]);
      expect(result.current.loading).toBe(false);
    });

    it("deleteJob 找不到原 job 时失败不回填", async () => {
      mockApi.deleteCronJob.mockRejectedValue(new Error("gone"));
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(2));

      let ok = true;
      await act(async () => {
        ok = await result.current.deleteJob("ghost");
      });

      expect(ok).toBe(false);
      expect(mockMessage.error).toHaveBeenCalledWith("Failed to delete");
      // Nothing was removed optimistically, so both jobs remain.
      expect(result.current.jobs).toHaveLength(2);
    });

    it("toggleEnabled 成功后以接口返回值为准并提示 Enabled", async () => {
      const returned = { ...mockCronJobs[1], enabled: true };
      mockApi.replaceCronJob.mockResolvedValue(returned);
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(2));

      let ok = false;
      await act(async () => {
        ok = await result.current.toggleEnabled(mockCronJobs[1]);
      });

      expect(ok).toBe(true);
      expect(mockMessage.success).toHaveBeenCalledWith("Enabled");
      expect(result.current.jobs.find((j) => j.id === "job-2")!.enabled).toBe(
        true,
      );
    });

    it("关闭任务时提示 Disabled", async () => {
      mockApi.replaceCronJob.mockResolvedValue({
        ...mockCronJobs[0],
        enabled: false,
      });
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(2));

      await act(async () => {
        await result.current.toggleEnabled(mockCronJobs[0]);
      });

      expect(mockMessage.success).toHaveBeenCalledWith("Disabled");
    });

    it("createJob 失败时不改动列表", async () => {
      mockApi.createCronJob.mockRejectedValue(new Error("boom"));
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(2));

      let ok = true;
      await act(async () => {
        ok = await result.current.createJob(
          mockCronJobs[0] as CronJobSpecOutput,
        );
      });

      expect(ok).toBe(false);
      expect(result.current.jobs).toHaveLength(2);
    });

    it("executeNow 失败时提示 Failed to execute", async () => {
      mockApi.triggerCronJob.mockRejectedValue(new Error("no runner"));
      const { result } = renderHook(() => useCronJobs());
      await vi.waitFor(() => expect(result.current.jobs).toHaveLength(2));

      let ok = true;
      await act(async () => {
        ok = await result.current.executeNow("job-1");
      });

      expect(ok).toBe(false);
      expect(mockMessage.error).toHaveBeenCalledWith("Failed to execute");
    });
  });
});
