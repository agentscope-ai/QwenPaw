import { Brain, Gauge, Languages, TerminalSquare } from "lucide-react-native";
import { useCallback, useEffect, useState } from "react";

import { QwenPawClient } from "../../api/client";
import type { Connection } from "../../api/types";
import { IosGroup, IosRow } from "../../components/IosList";
import { DynamicConfigSheet } from "./DynamicConfigSheet";

type Editor = "runtime" | "context" | "memory" | "locale";

export function AgentAdvancedSettings({ connection }: { connection: Connection }) {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [language, setLanguage] = useState("zh");
  const [timezone, setTimezone] = useState("Asia/Shanghai");
  const [editor, setEditor] = useState<Editor | null>(null);

  const load = useCallback(async () => {
    const client = new QwenPawClient(connection);
    const [configResult, languageResult, timezoneResult] = await Promise.allSettled([
      client.inspectModule("/workspace/running-config"),
      client.inspectModule("/workspace/language"),
      client.inspectModule("/config/user-timezone"),
    ]);
    if (configResult.status === "fulfilled" && isRecord(configResult.value)) {
      setConfig(configResult.value);
    }
    if (languageResult.status === "fulfilled") {
      setLanguage(String((languageResult.value as { language?: string }).language || "zh"));
    }
    if (timezoneResult.status === "fulfilled") {
      setTimezone(String((timezoneResult.value as { timezone?: string }).timezone || "Asia/Shanghai"));
    }
  }, [connection]);

  useEffect(() => {
    const task = setTimeout(() => void load(), 0);
    return () => clearTimeout(task);
  }, [load]);

  if (!config) return null;
  const loop = object(config.loop);
  const iteration = object(loop.iteration);
  const context = object(config.light_context_config);
  const compact = object(context.context_compact_config);
  const pruning = object(context.tool_result_pruning_config);
  const visual = object(context.visual_compact_config);
  const memory = object(config.reme_light_memory_config);
  const memorySearch = object(memory.auto_memory_search_config);

  return (
    <>
      <IosGroup title="运行与限流">
        <IosRow
          icon={Gauge}
          label="Agent Loop 与 LLM"
          onPress={() => setEditor("runtime")}
          subtitle={`最多 ${number(iteration.max_iterations, config.max_iters)} 轮 · ${number(config.llm_max_retries)} 次重试`}
        />
        <IosRow
          icon={TerminalSquare}
          iconTone="ink"
          label="Shell 与上下文"
          onPress={() => setEditor("context")}
          subtitle={`${number(config.shell_command_timeout)} 秒 · ${number(config.max_input_length)} tokens`}
        />
      </IosGroup>
      <IosGroup title="Memory 与呈现">
        <IosRow
          icon={Brain}
          label="记忆与压缩"
          onPress={() => setEditor("memory")}
          subtitle={`${String(config.memory_manager_backend || "remelight")} · 每 ${number(memory.auto_memory_interval)} 轮`}
        />
      </IosGroup>
      <IosGroup title="语言与地区">
        <IosRow
          icon={Languages}
          label={languageLabel(language)}
          onPress={() => setEditor("locale")}
          subtitle="Agent 默认语言"
          trailing={timezone}
        />
      </IosGroup>

      {editor ? (
        <DynamicConfigSheet
          fields={editor === "runtime" ? [
            { name: "iteration_enabled", label: "启用轮数限制", type: "boolean" },
            { name: "max_iterations", label: "最大迭代轮数", type: "number", required: true },
            { name: "llm_retry_enabled", label: "LLM 自动重试", type: "boolean" },
            { name: "llm_max_retries", label: "最大重试次数", type: "number", required: true },
            { name: "llm_backoff_base", label: "重试基础等待秒数", type: "number", required: true },
            { name: "llm_backoff_cap", label: "重试最大等待秒数", type: "number", required: true },
            { name: "llm_max_concurrent", label: "最大并发请求", type: "number", required: true },
            { name: "llm_max_qpm", label: "每分钟最大请求", type: "number", required: true },
            { name: "llm_acquire_timeout", label: "限流等待超时秒数", type: "number", required: true },
          ] : editor === "context" ? [
            { name: "shell_command_timeout", label: "Shell 命令超时秒数", type: "number", required: true },
            { name: "shell_command_executable", label: "Shell 可执行程序", type: "text" },
            { name: "max_input_length", label: "最大输入 Tokens", type: "number", required: true },
            { name: "history_max_length", label: "最大历史消息数", type: "number", required: true },
            { name: "context_compact_enabled", label: "自动压缩上下文", type: "boolean" },
            { name: "compact_threshold_ratio", label: "压缩触发比例", type: "number", required: true },
            { name: "tool_pruning_enabled", label: "裁剪旧工具结果", type: "boolean" },
            { name: "pruning_recent_n", label: "保留最近工具结果数", type: "number", required: true },
            { name: "visual_compact_enabled", label: "压缩视觉输入", type: "boolean" },
            { name: "visual_compact_effort", label: "视觉压缩强度", type: "select", options: ["low", "medium", "high"] },
          ] : editor === "memory" ? [
            { name: "memory_manager_backend", label: "Memory Backend", type: "select", options: ["remelight", "adbpg"] },
            { name: "auto_memory_interval", label: "自动记忆间隔轮数", type: "number", required: true },
            { name: "memory_search_enabled", label: "启用记忆搜索", type: "boolean" },
            { name: "auto_search_enabled", label: "对话前自动搜索", type: "boolean" },
            { name: "auto_search_max_results", label: "自动搜索结果数", type: "number", required: true },
            { name: "dream_cron_enabled", label: "启用 Dream Cron", type: "boolean" },
            { name: "dream_cron", label: "Dream Cron 表达式", type: "text" },
            { name: "daily_paper_cron_enabled", label: "启用 Daily Paper", type: "boolean" },
            { name: "daily_paper_cron", label: "Daily Paper Cron", type: "text" },
            { name: "daily_paper_topics", label: "Daily Paper 主题", type: "textarea" },
          ] : [
            { name: "language", label: "Agent 语言", type: "select", options: ["zh", "en", "id", "ru"] },
            { name: "timezone", label: "时区", type: "text", required: true, placeholder: "Asia/Shanghai" },
          ]}
          onClose={() => setEditor(null)}
          onSave={save}
          title={editorTitle(editor)}
          values={editor === "runtime" ? {
            iteration_enabled: iteration.enabled,
            max_iterations: number(iteration.max_iterations, config.max_iters),
            llm_retry_enabled: config.llm_retry_enabled,
            llm_max_retries: config.llm_max_retries,
            llm_backoff_base: config.llm_backoff_base,
            llm_backoff_cap: config.llm_backoff_cap,
            llm_max_concurrent: config.llm_max_concurrent,
            llm_max_qpm: config.llm_max_qpm,
            llm_acquire_timeout: config.llm_acquire_timeout,
          } : editor === "context" ? {
            shell_command_timeout: config.shell_command_timeout,
            shell_command_executable: config.shell_command_executable,
            max_input_length: config.max_input_length,
            history_max_length: config.history_max_length,
            context_compact_enabled: compact.enabled,
            compact_threshold_ratio: compact.compact_threshold_ratio,
            tool_pruning_enabled: pruning.enabled,
            pruning_recent_n: pruning.pruning_recent_n,
            visual_compact_enabled: visual.enabled,
            visual_compact_effort: visual.effort || "low",
          } : editor === "memory" ? {
            memory_manager_backend: config.memory_manager_backend,
            auto_memory_interval: memory.auto_memory_interval,
            memory_search_enabled: memory.memory_search_enabled,
            auto_search_enabled: memorySearch.enabled,
            auto_search_max_results: memorySearch.max_results,
            dream_cron_enabled: memory.dream_cron_enabled,
            dream_cron: memory.dream_cron,
            daily_paper_cron_enabled: memory.daily_paper_cron_enabled,
            daily_paper_cron: memory.daily_paper_cron,
            daily_paper_topics: memory.daily_paper_topics,
          } : { language, timezone }}
        />
      ) : null}
    </>
  );

  async function save(values: Record<string, unknown>) {
    const client = new QwenPawClient(connection);
    if (editor === "locale") {
      await Promise.all([
        client.mutateModule("/workspace/language", "PUT", {
          language: String(values.language),
        }),
        client.mutateModule("/config/user-timezone", "PUT", {
          timezone: String(values.timezone).trim(),
        }),
      ]);
      await load();
      return;
    }

    let next = { ...config };
    if (editor === "runtime") {
      next = {
        ...next,
        llm_retry_enabled: values.llm_retry_enabled,
        llm_max_retries: values.llm_max_retries,
        llm_backoff_base: values.llm_backoff_base,
        llm_backoff_cap: values.llm_backoff_cap,
        llm_max_concurrent: values.llm_max_concurrent,
        llm_max_qpm: values.llm_max_qpm,
        llm_acquire_timeout: values.llm_acquire_timeout,
        loop: {
          ...loop,
          iteration: {
            ...iteration,
            enabled: values.iteration_enabled,
            max_iterations: values.max_iterations,
          },
        },
      };
    } else if (editor === "context") {
      next = {
        ...next,
        shell_command_timeout: values.shell_command_timeout,
        shell_command_executable: values.shell_command_executable,
        max_input_length: values.max_input_length,
        history_max_length: values.history_max_length,
        light_context_config: {
          ...context,
          context_compact_config: {
            ...compact,
            enabled: values.context_compact_enabled,
            compact_threshold_ratio: values.compact_threshold_ratio,
          },
          tool_result_pruning_config: {
            ...pruning,
            enabled: values.tool_pruning_enabled,
            pruning_recent_n: values.pruning_recent_n,
          },
          visual_compact_config: {
            ...visual,
            enabled: values.visual_compact_enabled,
            effort: values.visual_compact_effort,
          },
        },
      };
    } else if (editor === "memory") {
      next = {
        ...next,
        memory_manager_backend: values.memory_manager_backend,
        reme_light_memory_config: {
          ...memory,
          auto_memory_interval: values.auto_memory_interval,
          memory_search_enabled: values.memory_search_enabled,
          dream_cron_enabled: values.dream_cron_enabled,
          dream_cron: values.dream_cron,
          daily_paper_cron_enabled: values.daily_paper_cron_enabled,
          daily_paper_cron: values.daily_paper_cron,
          daily_paper_topics: values.daily_paper_topics,
          auto_memory_search_config: {
            ...memorySearch,
            enabled: values.auto_search_enabled,
            max_results: values.auto_search_max_results,
          },
        },
      };
    }
    const saved = await client.mutateModule<Record<string, unknown>>(
      "/workspace/running-config",
      "PUT",
      next,
    );
    setConfig(saved);
  }
}

function object(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function number(value: unknown, fallback: unknown = 0): number {
  const parsed = Number(value ?? fallback);
  return Number.isFinite(parsed) ? parsed : 0;
}

function languageLabel(value: string): string {
  return ({ zh: "中文", en: "English", id: "Bahasa Indonesia", ru: "Русский" })[value] || value;
}

function editorTitle(editor: Editor): string {
  if (editor === "runtime") return "Agent Loop 与 LLM";
  if (editor === "context") return "Shell 与上下文";
  if (editor === "memory") return "Memory 与压缩";
  return "语言与地区";
}
