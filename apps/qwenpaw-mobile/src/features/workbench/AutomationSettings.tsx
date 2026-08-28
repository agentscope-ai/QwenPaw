import { MobileAlert } from "@/components/MobileAlert";
import { Clock3, HeartPulse, Pencil, Play, Pause, Plus } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { DynamicConfigSheet } from "./DynamicConfigSheet";
import { ModuleEmpty, ModuleError, ModuleFooter, ModuleLoading } from "./ModuleState";

interface CronJob {
  id: string;
  name: string;
  enabled?: boolean;
  schedule?: Record<string, unknown>;
  task_type?: "text" | "agent";
  text?: string;
  request?: { input?: unknown; [key: string]: unknown };
  dispatch?: Record<string, unknown>;
  runtime?: Record<string, unknown>;
  save_result_to_inbox?: boolean;
}

interface HeartbeatConfig {
  enabled: boolean;
  every?: string;
  target?: string;
  timeoutSeconds?: number;
  activeHours?: { start: string; end: string } | null;
}

interface DispatchTarget {
  channel: string;
  user_id: string;
  session_id: string;
}

export function AutomationSettings({ connection }: { connection: Connection }) {
  const [jobs, setJobs] = useState<CronJob[] | null>(null);
  const [heartbeat, setHeartbeat] = useState<HeartbeatConfig | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [editingJob, setEditingJob] = useState<CronJob | "new" | null>(null);
  const [editingHeartbeat, setEditingHeartbeat] = useState(false);
  const [dispatchTargets, setDispatchTargets] = useState<DispatchTarget[]>([]);

  const load = useCallback(async () => {
    try {
      const client = new QwenPawClient(connection);
      const [jobResult, heartbeatResult, targetsResult] = await Promise.allSettled([
        client.inspectModule("/cron/jobs"),
        client.inspectModule("/config/heartbeat"),
        client.inspectModule("/cron/dispatch-targets"),
      ]);
      if (jobResult.status === "fulfilled") {
        setJobs(Array.isArray(jobResult.value) ? jobResult.value as CronJob[] : []);
      } else {
        setJobs([]);
      }
      if (heartbeatResult.status === "fulfilled" &&
          heartbeatResult.value && typeof heartbeatResult.value === "object") {
        setHeartbeat(heartbeatResult.value as HeartbeatConfig);
      } else {
        setHeartbeat(null);
      }
      if (targetsResult.status === "fulfilled") {
        const items = (targetsResult.value as { items?: unknown[] })?.items;
        setDispatchTargets(Array.isArray(items) ? items as DispatchTarget[] : []);
      }
      if (jobResult.status === "rejected" && heartbeatResult.status === "rejected") {
        throw jobResult.reason;
      }
      setError(null);
    } catch (reason) {
      setError(errorMessage(reason));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  const runHeartbeat = useCallback(async () => {
    if (saving) return;
    setSaving("heartbeat");
    try {
      await new QwenPawClient(connection)
        .mutateModule("/config/heartbeat/run", "POST");
      MobileAlert.alert("Heartbeat 已启动", "任务已交给当前 QwenPaw 执行。");
    } catch (reason) {
      MobileAlert.alert("启动失败", errorMessage(reason));
    } finally {
      setSaving(null);
    }
  }, [connection, saving]);

  const jobAction = useCallback((job: CronJob) => {
    if (saving) return;
    const execute = async (action: "run" | "pause" | "resume") => {
      setSaving(job.id);
      try {
        await new QwenPawClient(connection).mutateModule(
          `/cron/jobs/${encodeURIComponent(job.id)}/${action}`,
          "POST",
        );
        if (action !== "run") {
          setJobs((current) => current?.map((candidate) => (
            candidate.id === job.id
              ? { ...candidate, enabled: action === "resume" }
              : candidate
          )) ?? null);
        }
      } catch (reason) {
        MobileAlert.alert("任务操作失败", errorMessage(reason));
      } finally {
        setSaving(null);
      }
    };
    MobileAlert.alert(job.name, scheduleLabel(job.schedule), [
      { text: "立即运行", onPress: () => void execute("run") },
      job.enabled === false
        ? { text: "恢复任务", onPress: () => void execute("resume") }
        : { text: "暂停任务", onPress: () => void execute("pause") },
      {
        text: "历史记录",
        onPress: () => void new QwenPawClient(connection).inspectModule(
          `/cron/jobs/${encodeURIComponent(job.id)}/history`,
        ).then((value) => {
          const records = Array.isArray(value) ? value as {
            run_at?: string;
            status?: string;
            error?: string;
          }[] : [];
          MobileAlert.alert(
            `${job.name} · 最近运行`,
            records.length ? records.slice(0, 8).map((record) => (
              `${record.status ?? "unknown"} · ${record.run_at ?? ""}${record.error ? `\n${record.error}` : ""}`
            )).join("\n\n") : "暂无运行记录",
          );
        }).catch((reason) => MobileAlert.alert("读取失败", errorMessage(reason))),
      },
      { text: "编辑", onPress: () => setEditingJob(job) },
      {
        text: "删除",
        style: "destructive",
        onPress: () => MobileAlert.alert("删除定时任务？", job.name, [
          { text: "取消", style: "cancel" },
          {
            text: "删除",
            style: "destructive",
            onPress: () => void new QwenPawClient(connection).mutateModule(
              `/cron/jobs/${encodeURIComponent(job.id)}`,
              "DELETE",
            ).then(load).catch((reason) => MobileAlert.alert("删除失败", errorMessage(reason))),
          },
        ]),
      },
      { text: "取消", style: "cancel" },
    ]);
  }, [connection, load, saving]);

  if (error) return <ModuleError message={error} onRetry={() => void load()} />;
  if (!jobs) return <ModuleLoading />;

  return (
    <>
      <IosGroup title="Heartbeat">
        <IosRow
          icon={HeartPulse}
          label="主动唤醒"
          onPress={heartbeat ? () => void runHeartbeat() : undefined}
          subtitle={heartbeat
            ? `${heartbeat.every ?? "按配置"} · ${heartbeat.target ?? "当前 Agent"}`
            : "当前 QwenPaw 不支持 Heartbeat"}
          trailing={heartbeat?.enabled ? "已启用" : "未启用"}
        />
        {heartbeat ? (
          <IosRow
            icon={Pencil}
            iconTone="ink"
            label="配置 Heartbeat"
            onPress={() => setEditingHeartbeat(true)}
            subtitle="周期、目标、超时与活跃时段"
          />
        ) : null}
      </IosGroup>
      {jobs.length ? (
        <IosGroup title={`Cron Jobs · ${jobs.length}`}>
          <IosRow
            icon={Plus}
            label="创建 Cron Job"
            onPress={() => setEditingJob("new")}
            subtitle="周期任务或一次性任务"
          />
          {jobs.map((job) => (
            <IosRow
              icon={job.enabled === false ? Pause : Play}
              iconTone={job.enabled === false ? "ink" : "orange"}
              key={job.id}
              label={job.name}
              onPress={() => jobAction(job)}
              subtitle={scheduleLabel(job.schedule)}
              trailing={job.enabled === false ? "已暂停" : "运行中"}
            />
          ))}
        </IosGroup>
      ) : (
        <>
          <IosGroup title="Cron Jobs">
            <IosRow icon={Plus} label="创建 Cron Job" onPress={() => setEditingJob("new")} />
          </IosGroup>
          <ModuleEmpty icon={Clock3} title="暂无定时任务" subtitle="当前 Agent 还没有创建 Cron Job。" />
        </>
      )}
      <ModuleFooter>点按任务可立即运行、暂停或恢复；操作直接写入当前 QwenPaw。</ModuleFooter>
      {editingHeartbeat && heartbeat ? (
        <DynamicConfigSheet
          fields={[
            { name: "enabled", label: "启用 Heartbeat", type: "switch" },
            { name: "every", label: "执行周期", type: "text", required: true, placeholder: "6h 或 30m" },
            { name: "target", label: "目标", type: "select", options: ["main", "last", "inbox"] },
            { name: "timeoutSeconds", label: "超时秒数", type: "number", required: true },
            { name: "activeHoursStart", label: "活跃时段开始", type: "text", placeholder: "08:00，可留空" },
            { name: "activeHoursEnd", label: "活跃时段结束", type: "text", placeholder: "22:00，可留空" },
          ]}
          onClose={() => setEditingHeartbeat(false)}
          onSave={async (values) => {
            const start = String(values.activeHoursStart || "").trim();
            const end = String(values.activeHoursEnd || "").trim();
            await new QwenPawClient(connection).mutateModule(
              "/config/heartbeat",
              "PUT",
              {
                enabled: values.enabled === true,
                every: values.every,
                target: values.target,
                timeoutSeconds: values.timeoutSeconds,
                activeHours: start && end ? { start, end } : null,
              },
            );
            await load();
          }}
          title="Heartbeat 配置"
          values={{
            ...heartbeat,
            activeHoursStart: heartbeat.activeHours?.start ?? "",
            activeHoursEnd: heartbeat.activeHours?.end ?? "",
          }}
        />
      ) : null}
      {editingJob ? (
        <DynamicConfigSheet
          fields={[
            { name: "name", label: "任务名称", type: "text", required: true },
            { name: "enabled", label: "启用任务", type: "switch" },
            { name: "schedule_type", label: "执行计划", type: "select", options: ["cron", "once"] },
            { name: "cron", label: "Cron 表达式", type: "text", placeholder: "0 9 * * *" },
            { name: "run_at", label: "一次执行时间", type: "text", placeholder: "2026-08-26T09:00:00" },
            { name: "timezone", label: "时区", type: "text", required: true, placeholder: "Asia/Shanghai" },
            { name: "repeat_every_days", label: "每隔几天重复", type: "number", help: "一次性任务可选；0 表示不重复。" },
            { name: "task_type", label: "任务类型", type: "select", options: ["agent", "text"] },
            { name: "content", label: "任务内容", type: "textarea", required: true, help: "Agent 任务填写用户指令；文本任务填写直接投递的文本。" },
            ...(dispatchTargets.length ? [{
              name: "dispatch_target",
              label: "投递目标",
              type: "select" as const,
              options: dispatchTargets.map(targetValue),
            }] : []),
            { name: "save_result_to_inbox", label: "结果保存到 Inbox", type: "switch" },
            { name: "timeout_seconds", label: "超时秒数", type: "number" },
          ]}
          onClose={() => setEditingJob(null)}
          onSave={async (values) => {
            const current = editingJob === "new" ? null : editingJob;
            const id = current?.id ?? createJobId(String(values.name || ""));
            const taskType = values.task_type === "text" ? "text" : "agent";
            const content = String(values.content || "");
            const scheduleType = values.schedule_type === "once" ? "once" : "cron";
            const cron = String(values.cron || "").trim();
            const runAt = String(values.run_at || "").trim();
            if (scheduleType === "cron" && !cron) {
              throw new Error("周期任务必须填写 Cron 表达式。");
            }
            if (scheduleType === "once" && !runAt) {
              throw new Error("一次性任务必须填写执行时间。");
            }
            const selectedTarget = parseTarget(
              String(values.dispatch_target || ""),
              dispatchTargets,
            );
            const payload = {
              ...(current ?? {}),
              id,
              name: String(values.name || "").trim(),
              enabled: values.enabled === true,
              save_result_to_inbox: values.save_result_to_inbox === true,
              schedule: scheduleType === "cron" ? {
                type: "cron",
                cron,
                timezone: String(values.timezone || "UTC").trim(),
              } : {
                type: "once",
                run_at: runAt,
                timezone: String(values.timezone || "UTC").trim(),
                ...(Number(values.repeat_every_days || 0) > 0 ? {
                  repeat_every_days: Number(values.repeat_every_days),
                  repeat_end_type: "never",
                } : {}),
              },
              task_type: taskType,
              ...(taskType === "text" ? { text: content, request: undefined } : {
                text: "",
                request: {
                  ...(current?.request ?? {}),
                  input: [{ role: "user", content: [{ type: "text", text: content }] }],
                  user_id: "mobile",
                  session_id: `cron:${id}`,
                },
              }),
              dispatch: {
                ...(current?.dispatch ?? {}),
                type: "channel",
                channel: selectedTarget?.channel ??
                  String(current?.dispatch?.channel || "console"),
                target: selectedTarget ? {
                  user_id: selectedTarget.user_id,
                  session_id: selectedTarget.session_id,
                } : current?.dispatch?.target ?? {
                  user_id: "mobile",
                  session_id: `cron:${id}`,
                },
                mode: "final",
                silent: false,
              },
              runtime: {
                ...(current?.runtime ?? {}),
                max_concurrency: 1,
                timeout_seconds: Number(values.timeout_seconds || 120),
                misfire_grace_seconds: 600,
                tool_safety: false,
              },
            };
            await new QwenPawClient(connection).mutateModule(
              current ? `/cron/jobs/${encodeURIComponent(current.id)}` : "/cron/jobs",
              current ? "PUT" : "POST",
              payload,
            );
            await load();
          }}
          title={editingJob === "new" ? "创建 Cron Job" : "编辑 Cron Job"}
          values={jobFormValues(editingJob, dispatchTargets)}
        />
      ) : null}
    </>
  );
}

function jobFormValues(
  job: CronJob | "new",
  dispatchTargets: DispatchTarget[],
): Record<string, unknown> {
  if (job === "new") return {
    enabled: true,
    schedule_type: "cron",
    cron: "0 9 * * *",
    run_at: "",
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC",
    repeat_every_days: 0,
    task_type: "agent",
    dispatch_target: dispatchTargets[0] ? targetValue(dispatchTargets[0]) : "",
    save_result_to_inbox: true,
    timeout_seconds: 120,
  };
  const input = job.request?.input;
  let content = job.text ?? "";
  if (job.task_type !== "text" && Array.isArray(input)) {
    const first = input[0] as { content?: { text?: string }[] } | undefined;
    content = first?.content?.map((item) => item.text ?? "").join("\n") ?? "";
  }
  return {
    name: job.name,
    enabled: job.enabled !== false,
    schedule_type: job.schedule?.type === "once" ? "once" : "cron",
    cron: String(job.schedule?.cron ?? "0 9 * * *"),
    run_at: String(job.schedule?.run_at ?? ""),
    timezone: String(job.schedule?.timezone ?? "UTC"),
    repeat_every_days: Number(job.schedule?.repeat_every_days ?? 0),
    task_type: job.task_type ?? "agent",
    dispatch_target: dispatchValue(job.dispatch, dispatchTargets),
    content,
    save_result_to_inbox: job.save_result_to_inbox !== false,
    timeout_seconds: Number(job.runtime?.timeout_seconds ?? 120),
  };
}

function targetValue(target: DispatchTarget): string {
  return `${target.channel} · ${target.user_id} · ${target.session_id}`;
}

function parseTarget(
  value: string,
  targets: DispatchTarget[],
): DispatchTarget | undefined {
  return targets.find((target) => targetValue(target) === value);
}

function dispatchValue(
  dispatch: Record<string, unknown> | undefined,
  targets: DispatchTarget[],
): string {
  const target = dispatch?.target as { user_id?: string; session_id?: string } | undefined;
  const match = targets.find((item) => item.channel === dispatch?.channel &&
    item.user_id === target?.user_id && item.session_id === target?.session_id);
  return match ? targetValue(match) : targets[0] ? targetValue(targets[0]) : "";
}

function createJobId(name: string): string {
  const slug = name.trim().toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `${slug || "mobile-job"}-${Date.now().toString(36)}`;
}

function scheduleLabel(schedule?: Record<string, unknown>): string {
  if (!schedule) return "未设置计划";
  if (typeof schedule.cron === "string") return schedule.cron;
  if (typeof schedule.run_at === "string") return schedule.run_at;
  return "按服务端计划运行";
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "读取失败";
}
