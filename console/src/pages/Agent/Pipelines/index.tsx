import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Card, Empty, Modal, Select, Spin, Tag, Typography, message } from "antd";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { agentsApi } from "../../../api/modules/agents";
import { chatApi } from "../../../api/modules/chat";
import AnywhereChat from "../../../components/AnywhereChat";
import sessionApi from "../../Chat/sessionApi";
import {
  buildPipelineDesignBindingKey,
  buildPipelineDesignEditContextPrompt,
  buildPipelineDesignBootstrapPrompt,
  buildPipelineDesignChatPath,
} from "../../../utils/pipelineDesign";
import { trackNavigation } from "../../../utils/navigationTelemetry";
import type {
  AgentProjectSummary,
  AgentSummary,
  PipelineValidationError,
  ProjectPipelineTemplateStep,
  ProjectPipelineRunSummary,
  ProjectPipelineTemplateInfo,
} from "../../../api/types/agents";
import type { ChatSpec } from "../../../api/types/chat";
import { useAgentStore } from "../../../stores/agentStore";
import styles from "./index.module.less";

const { Title, Text } = Typography;

type TemplateItem = ProjectPipelineTemplateInfo & {
  projectId: string;
  projectName: string;
};

type RunItem = ProjectPipelineRunSummary & {
  projectId: string;
  projectName: string;
};

type PipelineManagementData = {
  templates: TemplateItem[];
  runs: RunItem[];
};

type PersistedPipelineDraftState = {
  version: 1;
  templates: TemplateItem[];
  draftPipelineKeys: string[];
  selectedPipelineKey: string;
  selectedCurrentVersion: string;
  selectedCompareVersion: string;
  sourceFilter: "all" | "independent" | "project";
  draftNewVersionSteps: ProjectPipelineTemplateStep[];
  draftParseStatus: "idle" | "ready" | "error";
  draftParseError: string;
};

type PipelineGroup = {
  key: string;
  id: string;
  name: string;
  description: string;
  versions: ProjectPipelineTemplateInfo[];
  projects: { id: string; name: string }[];
  source: "independent" | "project";
};

type StepDiffItem = {
  id: string;
  kind: "added" | "removed" | "changed" | "unchanged";
  current?: { name: string; kind: string; description: string };
  compare?: { name: string; kind: string; description: string };
  changedFields: string[];
};

type EditChatTarget = {
  pipelineId: string;
  pipelineName: string;
  version: string;
  isEmptyNodes: boolean;
  description?: string;
  steps?: ProjectPipelineTemplateStep[];
  source?: "independent" | "project";
};

type DraftParseResult = {
  steps: ProjectPipelineTemplateStep[];
  error?: string;
};

type PipelineSaveConflictInfo = {
  expectedRevision: number;
  currentRevision: number;
  currentContentHash: string;
};

type PipelineChatBindingMeta = {
  binding_type: "pipeline_edit";
  pipeline_binding_key: string;
  pipeline_id: string;
  pipeline_name: string;
  pipeline_version: string;
  pipeline_scope: "independent" | "project";
  agent_id: string;
  flow_memory_path?: string;
};

const INDEPENDENT_PIPELINE_SCOPE_ID = "__independent__";
const PIPELINE_DRAFT_STORAGE_PREFIX = "copaw:pipelines:drafts:";

function buildPrefilledPipelineTemplateSteps(): ProjectPipelineTemplateStep[] {
  return [
    {
      id: "step-1-purpose",
      name: "明确流程用途",
      kind: "analysis",
      description: "[用途] 描述本流程解决的问题和适用范围。",
    },
    {
      id: "step-2-input",
      name: "整理输入来源",
      kind: "ingest",
      description: "[输入] 列出输入数据类型、来源路径和前置要求。",
    },
    {
      id: "step-3-workflow",
      name: "执行核心处理",
      kind: "transform",
      description: "[步骤线索] 按阶段拆解核心处理步骤，可继续细分子步骤。",
    },
    {
      id: "step-4-quality-check",
      name: "质量校验",
      kind: "validation",
      description: "定义质量门槛、失败判定和重试策略。",
    },
    {
      id: "step-5-output",
      name: "生成目标产物",
      kind: "publish",
      description: "[产物] 输出结果格式、保存位置和交付方式。",
    },
  ];
}

function getPipelineDraftStorageKey(agentId: string): string {
  return `${PIPELINE_DRAFT_STORAGE_PREFIX}${agentId}`;
}

function readPipelineDraftState(agentId: string): PersistedPipelineDraftState | null {
  if (typeof window === "undefined") return null;

  try {
    const raw = window.localStorage.getItem(getPipelineDraftStorageKey(agentId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedPipelineDraftState;

    if (!parsed || parsed.version !== 1 || !Array.isArray(parsed.templates)) {
      return null;
    }

    return parsed;
  } catch {
    return null;
  }
}

function writePipelineDraftState(agentId: string, state: PersistedPipelineDraftState): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(getPipelineDraftStorageKey(agentId), JSON.stringify(state));
  } catch {
    // Ignore localStorage quota or serialization failures.
  }
}

function clearPipelineDraftState(agentId: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(getPipelineDraftStorageKey(agentId));
  } catch {
    // Ignore storage cleanup failures.
  }
}

function getTemplateSourceKind(item: TemplateItem): "independent" | "project" {
  return item.projectId === INDEPENDENT_PIPELINE_SCOPE_ID ? "independent" : "project";
}

function buildPipelineGroupKey(
  templateId: string,
  source: "independent" | "project",
): string {
  return `${templateId}::${source}`;
}

async function loadPipelineManagementData(
  agentId: string,
  projectList: AgentProjectSummary[],
  independentScopeLabel: string,
): Promise<PipelineManagementData> {
  const [perProject, agentTemplates] = await Promise.all([
    Promise.all(
      projectList.map(async (project) => {
        const [templatesResult, runsResult] = await Promise.allSettled([
          agentsApi.listProjectPipelineTemplates(agentId, project.id),
          agentsApi.listProjectPipelineRuns(agentId, project.id),
        ]);

        return {
          project,
          templates:
            templatesResult.status === "fulfilled"
              ? templatesResult.value
              : [],
          runs: runsResult.status === "fulfilled" ? runsResult.value : [],
        };
      }),
    ),
    agentsApi.listAgentPipelineTemplates(agentId).catch(() => []),
  ]);

  const templates: TemplateItem[] = [
    ...agentTemplates.map((tpl) => ({
      ...tpl,
      projectId: INDEPENDENT_PIPELINE_SCOPE_ID,
      projectName: independentScopeLabel,
    })),
    ...perProject.flatMap((item) =>
      item.templates.map((tpl) => ({
        ...tpl,
        projectId: item.project.id,
        projectName: item.project.name,
      })),
    ),
  ];

  const runs: RunItem[] = perProject
    .flatMap((item) =>
      item.runs.map((run) => ({
        ...run,
        projectId: item.project.id,
        projectName: item.project.name,
      })),
    )
    .sort((a, b) =>
      (b.updated_at || b.created_at).localeCompare(a.updated_at || a.created_at),
    );

  return { templates, runs };
}

function statusTagColor(status: string): string {
  switch (status) {
    case "running":
      return "processing";
    case "succeeded":
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "pending":
      return "default";
    default:
      return "blue";
  }
}

function getCurrentAgent(
  agents: AgentSummary[],
  selectedAgent: string,
): AgentSummary | undefined {
  return agents.find((agent) => agent.id === selectedAgent);
}

function buildPipelineEntrySessionId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `pipeline-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function normalizeVersion(version: string): string {
  return version.trim() || "0";
}

function parseJsonFromText(text: string): unknown | null {
  const raw = text.trim();
  if (!raw) return null;

  const candidates: string[] = [raw];
  const fencedBlocks = raw.match(/```json\s*([\s\S]*?)```/gi) || [];
  fencedBlocks.forEach((block) => {
    const unwrapped = block
      .replace(/^```json\s*/i, "")
      .replace(/```$/i, "")
      .trim();
    if (unwrapped) candidates.push(unwrapped);
  });

  const braceStart = raw.indexOf("{");
  const braceEnd = raw.lastIndexOf("}");
  if (braceStart >= 0 && braceEnd > braceStart) {
    candidates.push(raw.slice(braceStart, braceEnd + 1));
  }

  for (const candidate of candidates) {
    try {
      return JSON.parse(candidate);
    } catch {
      continue;
    }
  }

  return null;
}

function getMetaString(meta: Record<string, unknown> | undefined, key: string): string {
  const value = meta?.[key];
  return typeof value === "string" ? value : "";
}

function buildPipelineChatBindingMeta(params: {
  pipelineId: string;
  pipelineName: string;
  version: string;
  scope: "independent" | "project";
  agentId?: string;
  flowMemoryPath?: string;
}): PipelineChatBindingMeta {
  const normalizedVersion = normalizeVersion(params.version);
  return {
    binding_type: "pipeline_edit",
    pipeline_binding_key: buildPipelineDesignBindingKey({
      pipelineId: params.pipelineId,
      version: normalizedVersion,
    }),
    pipeline_id: params.pipelineId,
    pipeline_name: params.pipelineName,
    pipeline_version: normalizedVersion,
    pipeline_scope: params.scope,
    agent_id: params.agentId || "unknown",
    flow_memory_path: params.flowMemoryPath,
  };
}

function buildPipelineFlowMemoryRelativePath(pipelineId: string): string {
  return `pipelines/workspaces/${pipelineId}/flow-memory.md`;
}

function normalizeDraftSteps(raw: unknown): DraftParseResult {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) {
    return {
      steps: [],
      error: "JSON root must be an object.",
    };
  }

  const doc = raw as Record<string, unknown>;
  if (doc.schema_version !== 1) {
    return {
      steps: [],
      error: "schema_version must be 1.",
    };
  }

  if (!Array.isArray(doc.steps)) {
    return {
      steps: [],
      error: "steps must be an array.",
    };
  }

  if (doc.steps.length === 0) {
    return {
      steps: [],
      error: "steps cannot be empty.",
    };
  }

  const arrayLike = doc.steps as unknown[];

  const steps: ProjectPipelineTemplateStep[] = [];
  const issues: string[] = [];
  const idSet = new Set<string>();

  const toText = (value: unknown): string => {
    if (typeof value === "string") return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
    return "";
  };

  const normalizeStepId = (item: Record<string, unknown>): string => {
    const direct = toText(item.id);
    if (direct) return direct;

    const alias = toText(item.step_id) || toText(item.stepId);
    if (!alias) return "";

    // Convert numeric-like ids into canonical step-* form.
    return /^\d+$/.test(alias) ? `step-${alias}` : alias;
  };

  arrayLike.forEach((node, index) => {
    if (!node || typeof node !== "object" || Array.isArray(node)) {
      issues.push(`steps[${index}] must be an object.`);
      return;
    }
    const item = node as Record<string, unknown>;

    const rawId = normalizeStepId(item);
    const rawName = toText(item.name) || toText(item.title);
    const rawKind = toText(item.kind) || toText(item.action) || toText(item.type);
    const rawDescription = toText(item.description) || toText(item.desc);

    const missing: string[] = [];
    if (!rawName) missing.push("name");
    if (missing.length > 0) {
      issues.push(`steps[${index}] missing required fields: ${missing.join(", ")}.`);
      return;
    }

    const safeId = rawId || `step-${index + 1}`;
    const safeKind = rawKind || "transform";

    if (idSet.has(safeId)) {
      issues.push(`steps[${index}] duplicate id: ${safeId}.`);
      return;
    }
    idSet.add(safeId);

    steps.push({
      id: safeId,
      name: rawName,
      kind: safeKind,
      description: rawDescription,
    });
  });

  if (issues.length > 0) {
    return {
      steps: [],
      error: issues.join(" "),
    };
  }

  return { steps };
}

function extractPipelineConflictInfo(detail: unknown): PipelineSaveConflictInfo | null {
  if (!detail || typeof detail !== "object") return null;
  const obj = detail as Record<string, unknown>;
  if (obj.code !== "pipeline_revision_conflict") return null;
  const expectedRevision = Number(obj.expected_revision || 0);
  const currentRevision = Number(obj.current_revision || 0);
  const currentContentHash = typeof obj.current_content_hash === "string"
    ? obj.current_content_hash
    : "";
  return {
    expectedRevision,
    currentRevision,
    currentContentHash,
  };
}

function extractPipelineDetailFromError(error: unknown): Record<string, unknown> | null {
  const text = error instanceof Error ? error.message : String(error);
  const marker = " - ";
  const idx = text.indexOf(marker);
  if (idx < 0) return null;
  const maybeJson = text.slice(idx + marker.length).trim();
  try {
    const parsed = JSON.parse(maybeJson) as Record<string, unknown>;
    const detail = parsed.detail;
    if (detail && typeof detail === "object") {
      return detail as Record<string, unknown>;
    }
  } catch {
    return null;
  }
  return null;
}

function stepsFingerprint(steps: ProjectPipelineTemplateStep[]): string {
  return JSON.stringify(
    steps.map((step) => ({
      id: step.id,
      name: step.name,
      kind: step.kind,
      description: step.description || "",
    })),
  );
}

function mergeDraftStepsByStepId(
  remoteSteps: ProjectPipelineTemplateStep[],
  localSteps: ProjectPipelineTemplateStep[],
): ProjectPipelineTemplateStep[] {
  const localMap = new Map(localSteps.map((step) => [step.id, step] as const));

  const merged: ProjectPipelineTemplateStep[] = [];

  // Keep remote order as baseline, then overlay local edits for matching ids.
  remoteSteps.forEach((remoteStep) => {
    const localStep = localMap.get(remoteStep.id);
    if (localStep) {
      merged.push({
        ...remoteStep,
        name: localStep.name || remoteStep.name,
        kind: localStep.kind || remoteStep.kind,
        description: localStep.description || remoteStep.description,
      });
      localMap.delete(remoteStep.id);
      return;
    }
    merged.push(remoteStep);
  });

  // Append local-only steps that do not exist remotely.
  localMap.forEach((localOnly) => {
    merged.push(localOnly);
  });

  return merged;
}

function compareSemverDesc(a: string, b: string): number {
  const parsePart = (value: string): number => {
    const num = Number(value);
    return Number.isFinite(num) ? num : 0;
  };

  const partsA = normalizeVersion(a)
    .split(".")
    .map((part) => parsePart(part.replace(/[^0-9]/g, "")));
  const partsB = normalizeVersion(b)
    .split(".")
    .map((part) => parsePart(part.replace(/[^0-9]/g, "")));

  const length = Math.max(partsA.length, partsB.length);
  for (let i = 0; i < length; i += 1) {
    const diff = (partsB[i] || 0) - (partsA[i] || 0);
    if (diff !== 0) return diff;
  }
  return normalizeVersion(b).localeCompare(normalizeVersion(a), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

function stepComparable(step: { name: string; kind: string; description: string }): string {
  return `${step.name}|${step.kind}|${step.description}`;
}

type DiffFieldKey = "name" | "kind" | "description";

type InlineDiffToken = {
  text: string;
  changed: boolean;
};

function getStepFieldValue(
  step: StepDiffItem["current"] | StepDiffItem["compare"],
  field: DiffFieldKey,
): string {
  if (!step) return "-";
  const value = step[field];
  return value && value.trim() ? value : "-";
}

function tokenizeInlineDiff(value: string): string[] {
  if (!value) return [];
  return value.split(/(\s+)/).filter((part) => part.length > 0);
}

function buildInlineDiffTokens(
  oldValue: string,
  newValue: string,
): { oldTokens: InlineDiffToken[]; newTokens: InlineDiffToken[] } {
  if (oldValue === newValue) {
    return {
      oldTokens: [{ text: oldValue || "-", changed: false }],
      newTokens: [{ text: newValue || "-", changed: false }],
    };
  }

  const oldWords = tokenizeInlineDiff(oldValue);
  const newWords = tokenizeInlineDiff(newValue);

  if (oldWords.length === 0 || newWords.length === 0) {
    return {
      oldTokens: [{ text: oldValue || "-", changed: true }],
      newTokens: [{ text: newValue || "-", changed: true }],
    };
  }

  const m = oldWords.length;
  const n = newWords.length;
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));

  for (let i = m - 1; i >= 0; i -= 1) {
    for (let j = n - 1; j >= 0; j -= 1) {
      if (oldWords[i] === newWords[j]) {
        dp[i][j] = dp[i + 1][j + 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
  }

  const oldMatched = new Array(m).fill(false);
  const newMatched = new Array(n).fill(false);

  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (oldWords[i] === newWords[j]) {
      oldMatched[i] = true;
      newMatched[j] = true;
      i += 1;
      j += 1;
      continue;
    }
    if (dp[i + 1][j] >= dp[i][j + 1]) {
      i += 1;
    } else {
      j += 1;
    }
  }

  return {
    oldTokens: oldWords.map((text, idx) => ({ text, changed: !oldMatched[idx] })),
    newTokens: newWords.map((text, idx) => ({ text, changed: !newMatched[idx] })),
  };
}

function buildChangedOnlyText(tokens: InlineDiffToken[]): string {
  const changedWords = tokens
    .filter((token) => token.changed)
    .map((token) => token.text.trim())
    .filter((token) => token.length > 0);

  return changedWords.length > 0 ? changedWords.join(" ") : "-";
}

function buildStepDiff(
  currentSteps: ProjectPipelineTemplateInfo["steps"],
  compareSteps: ProjectPipelineTemplateInfo["steps"],
): StepDiffItem[] {
  const currentMap = new Map(currentSteps.map((item) => [item.id, item]));
  const compareMap = new Map(compareSteps.map((item) => [item.id, item]));

  const result: StepDiffItem[] = [];

  currentSteps.forEach((step) => {
    const compareStep = compareMap.get(step.id);
    if (!compareStep) {
      result.push({
        id: step.id,
        kind: "added",
        current: {
          name: step.name,
          kind: step.kind,
          description: step.description,
        },
        changedFields: [],
      });
      return;
    }

    const changedFields: string[] = [];
    if (step.name !== compareStep.name) changedFields.push("name");
    if (step.kind !== compareStep.kind) changedFields.push("kind");
    if (step.description !== compareStep.description) changedFields.push("description");

    result.push({
      id: step.id,
      kind:
        stepComparable({
          name: step.name,
          kind: step.kind,
          description: step.description,
        }) ===
        stepComparable({
          name: compareStep.name,
          kind: compareStep.kind,
          description: compareStep.description,
        })
          ? "unchanged"
          : "changed",
      current: {
        name: step.name,
        kind: step.kind,
        description: step.description,
      },
      compare: {
        name: compareStep.name,
        kind: compareStep.kind,
        description: compareStep.description,
      },
      changedFields,
    });
  });

  compareSteps.forEach((step) => {
    if (currentMap.has(step.id)) return;
    result.push({
      id: step.id,
      kind: "removed",
      compare: {
        name: step.name,
        kind: step.kind,
        description: step.description,
      },
      changedFields: [],
    });
  });

  return result;
}

export default function PipelinesPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { selectedAgent, agents, setAgents } = useAgentStore();

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [templates, setTemplates] = useState<TemplateItem[]>([]);
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [selectedPipelineKey, setSelectedPipelineKey] = useState("");
  const [sourceFilter, setSourceFilter] = useState<"all" | "independent" | "project">("all");
  const [selectedCurrentVersion, setSelectedCurrentVersion] = useState("");
  const [selectedCompareVersion, setSelectedCompareVersion] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [designChatStarting, setDesignChatStarting] = useState(false);
  const [draftSaving, setDraftSaving] = useState(false);
  const [designChatSessionId, setDesignChatSessionId] = useState("");
  const [editTargetKey, setEditTargetKey] = useState("");
  const [editGuidePlaceholder, setEditGuidePlaceholder] = useState("");
  const [editWelcomeMode, setEditWelcomeMode] = useState<"default" | "init">("default");
  const [draftPipelineKeys, setDraftPipelineKeys] = useState<string[]>([]);
  const [draftNewVersionSteps, setDraftNewVersionSteps] = useState<ProjectPipelineTemplateStep[]>([]);
  const [draftParseStatus, setDraftParseStatus] = useState<"idle" | "ready" | "error">("idle");
  const [draftParseError, setDraftParseError] = useState("");
  const [expandedDraftDiffKeys, setExpandedDraftDiffKeys] = useState<string[]>([]);
  const [draftDiffViewMode, setDraftDiffViewMode] = useState<"changedOnly" | "full">("changedOnly");
  const [lastDraftMdMtime, setLastDraftMdMtime] = useState(0);
  const [saveStreamEvents, setSaveStreamEvents] = useState<Array<{ event: string; ts: number; detail: string }>>([]);
  const [saveStreamError, setSaveStreamError] = useState("");
  const [saveValidationErrors, setSaveValidationErrors] = useState<PipelineValidationError[]>([]);
  const [saveConflictInfo, setSaveConflictInfo] = useState<PipelineSaveConflictInfo | null>(null);
  const [conflictLocalDraftBackup, setConflictLocalDraftBackup] = useState<ProjectPipelineTemplateStep[]>([]);
  const [conflictRemoteDraftBackup, setConflictRemoteDraftBackup] = useState<ProjectPipelineTemplateStep[]>([]);
  const [conflictRestoreAvailable, setConflictRestoreAvailable] = useState(false);
  const [conflictMergeAvailable, setConflictMergeAvailable] = useState(false);

  const currentAgent = useMemo(
    () => getCurrentAgent(agents, selectedAgent),
    [agents, selectedAgent],
  );

  const projects = useMemo<AgentProjectSummary[]>(
    () => currentAgent?.projects ?? [],
    [currentAgent?.projects],
  );

  const independentScopeLabel = t("pipelines.independentScope", "独立流程");

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      if (!selectedAgent) return;

      setLoading(true);
      setError("");

      try {
        let availableAgents = agents;
        if (availableAgents.length === 0) {
          const listResp = await agentsApi.listAgents();
          availableAgents = listResp.agents;
          if (mounted) setAgents(listResp.agents);
        }

        const agent = getCurrentAgent(availableAgents, selectedAgent);
        const projectList = agent?.projects ?? [];
        const data = await loadPipelineManagementData(
          selectedAgent,
          projectList,
          independentScopeLabel,
        );

        if (!mounted) return;

        const persisted = readPipelineDraftState(selectedAgent);
        const persistedTemplates = (persisted?.templates || []).filter(
          (item) => item.projectId === INDEPENDENT_PIPELINE_SCOPE_ID,
        );
        const mergedTemplates = [...persistedTemplates, ...data.templates.filter((item) => {
          const key = buildPipelineGroupKey(item.id, getTemplateSourceKind(item));
          return !persistedTemplates.some(
            (draftItem) => buildPipelineGroupKey(draftItem.id, getTemplateSourceKind(draftItem)) === key,
          );
        })];

        const restoredDraftKeys = (persisted?.draftPipelineKeys || []).filter((key) =>
          mergedTemplates.some(
            (item) => buildPipelineGroupKey(item.id, getTemplateSourceKind(item)) === key,
          ),
        );

        setTemplates(mergedTemplates);
        setRuns(data.runs);
        setDraftPipelineKeys(restoredDraftKeys);

        if (persisted && restoredDraftKeys.length > 0) {
          setSourceFilter(persisted.sourceFilter || "independent");
          if (persisted.selectedPipelineKey) {
            setSelectedPipelineKey(persisted.selectedPipelineKey);
          }
          if (persisted.selectedCurrentVersion) {
            setSelectedCurrentVersion(persisted.selectedCurrentVersion);
          }
          if (persisted.selectedCompareVersion) {
            setSelectedCompareVersion(persisted.selectedCompareVersion);
          }
          setDraftNewVersionSteps(persisted.draftNewVersionSteps || []);
          setDraftParseStatus(persisted.draftParseStatus || "idle");
          setDraftParseError(persisted.draftParseError || "");
            message.info(
              t(
                "pipelines.localDraftRestored",
                "已恢复本地未保存草稿。",
              ),
            );
        }
      } catch (err) {
        console.error("failed to load pipeline management data", err);
        if (mounted) {
          setError(
            t(
              "pipelines.loadFailed",
              "Failed to load pipeline management data.",
            ),
          );
        }
      } finally {
        if (mounted) setLoading(false);
      }
    };

    load();

    return () => {
      mounted = false;
    };
  }, [agents, independentScopeLabel, selectedAgent, setAgents, t]);

  const pipelineGroups = useMemo<PipelineGroup[]>(() => {
    const filteredTemplates = templates.filter((item) => {
      const isIndependent = item.projectId === INDEPENDENT_PIPELINE_SCOPE_ID;
      if (sourceFilter === "independent") return isIndependent;
      if (sourceFilter === "project") return !isIndependent;
      return true;
    });

    const map = new Map<string, TemplateItem[]>();
    filteredTemplates.forEach((item) => {
      const groupKey = buildPipelineGroupKey(item.id, getTemplateSourceKind(item));
      if (!map.has(groupKey)) {
        map.set(groupKey, []);
      }
      map.get(groupKey)?.push(item);
    });

    return Array.from(map.entries())
      .map(([groupKey, items]) => {
        const versionsByKey = new Map<string, ProjectPipelineTemplateInfo>();
        const projectMap = new Map<string, { id: string; name: string }>();

        items.forEach((item) => {
          const versionKey = normalizeVersion(item.version);
          if (!versionsByKey.has(versionKey)) {
            versionsByKey.set(versionKey, {
              id: item.id,
              name: item.name,
              version: item.version,
              description: item.description,
              steps: item.steps,
            });
          }
          if (!projectMap.has(item.projectId)) {
            projectMap.set(item.projectId, {
              id: item.projectId,
              name: item.projectName,
            });
          }
        });

        const versions = Array.from(versionsByKey.values()).sort((a, b) =>
          compareSemverDesc(a.version, b.version),
        );

        const source: PipelineGroup["source"] = getTemplateSourceKind(items[0]);

        return {
          key: groupKey,
          id: items[0].id,
          name: items[0].name,
          description: items[0].description,
          versions,
          projects: Array.from(projectMap.values()),
          source,
        };
      })
      .sort((a, b) => {
        const nameCmp = a.name.localeCompare(b.name, undefined, { sensitivity: "base" });
        if (nameCmp !== 0) return nameCmp;
        return a.source.localeCompare(b.source);
      });
  }, [sourceFilter, templates]);

  const selectedPipeline = useMemo(
    () => pipelineGroups.find((item) => item.key === selectedPipelineKey),
    [pipelineGroups, selectedPipelineKey],
  );

  const currentTemplate = useMemo(() => {
    if (!selectedPipeline) return null;
    return (
      selectedPipeline.versions.find(
        (item) => normalizeVersion(item.version) === selectedCurrentVersion,
      ) || selectedPipeline.versions[0] || null
    );
  }, [selectedCurrentVersion, selectedPipeline]);

  const compareTemplate = useMemo(() => {
    if (!selectedPipeline || !selectedCompareVersion) return null;
    return (
      selectedPipeline.versions.find(
        (item) => normalizeVersion(item.version) === selectedCompareVersion,
      ) || null
    );
  }, [selectedCompareVersion, selectedPipeline]);

  const selectedTemplateItem = useMemo(() => {
    if (!selectedPipeline || !selectedCurrentVersion) return null;
    return (
      templates.find(
        (item) =>
          item.id === selectedPipeline.id &&
          getTemplateSourceKind(item) === selectedPipeline.source &&
          normalizeVersion(item.version) === selectedCurrentVersion,
      ) || null
    );
  }, [selectedCurrentVersion, selectedPipeline, templates]);

  const selectedIsDraft = useMemo(() => {
    if (!selectedPipeline) return false;
    return draftPipelineKeys.includes(selectedPipeline.key);
  }, [draftPipelineKeys, selectedPipeline]);

  const hasUnsavedDrafts = draftPipelineKeys.length > 0;

  useEffect(() => {
    if (!hasUnsavedDrafts) return;

    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = t(
        "pipelines.unsavedLeaveWarning",
        "当前有未保存的流程草稿，离开后将丢失。",
      );
    };

    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload);
    };
  }, [hasUnsavedDrafts, t]);

  const closeEditMode = () => {
    setEditMode(false);
    setEditGuidePlaceholder("");
    setEditWelcomeMode("default");
    setDraftNewVersionSteps([]);
    setDraftParseStatus("idle");
    setDraftParseError("");
    setExpandedDraftDiffKeys([]);
    setLastDraftMdMtime(0);
    setSaveStreamEvents([]);
    setSaveStreamError("");
    setSaveValidationErrors([]);
    setSaveConflictInfo(null);
    setConflictLocalDraftBackup([]);
    setConflictRemoteDraftBackup([]);
    setConflictRestoreAvailable(false);
    setConflictMergeAvailable(false);
  };

  const handleRefreshAfterConflict = useCallback(async () => {
    if (!selectedAgent || !selectedTemplateItem) {
      return;
    }
    try {
      const data = await loadPipelineManagementData(
        selectedAgent,
        projects,
        independentScopeLabel,
      );
      setTemplates(data.templates);
      setRuns(data.runs);
      const remoteDraft = await agentsApi.getPipelineDraft(selectedAgent, selectedTemplateItem.id);
      if (remoteDraft.steps && remoteDraft.steps.length > 0) {
        setDraftNewVersionSteps(remoteDraft.steps);
        setDraftParseStatus("ready");
        setDraftParseError("");
        setExpandedDraftDiffKeys([]);
        setLastDraftMdMtime(remoteDraft.md_mtime || 0);
        setConflictRemoteDraftBackup(remoteDraft.steps);
      }

      const hasLocalBackup = conflictLocalDraftBackup.length > 0;
      const hasRemoteBackup = (remoteDraft.steps || []).length > 0;
      const localFingerprint = hasLocalBackup
        ? stepsFingerprint(conflictLocalDraftBackup)
        : "";
      const remoteFingerprint = stepsFingerprint(remoteDraft.steps || []);
      setConflictRestoreAvailable(
        hasLocalBackup && localFingerprint !== remoteFingerprint,
      );
      setConflictMergeAvailable(
        hasLocalBackup && hasRemoteBackup && localFingerprint !== remoteFingerprint,
      );

      message.success(t("pipelines.conflictRefreshed", "已刷新到最新流程版本，请检查后重试保存。"));
    } catch (error) {
      console.error("failed to refresh pipelines after conflict", error);
      message.error(t("pipelines.conflictRefreshFailed", "刷新流程失败，请稍后重试。"));
    }
  }, [
    conflictLocalDraftBackup,
    independentScopeLabel,
    projects,
    selectedAgent,
    selectedTemplateItem,
    t,
  ]);

  const handleRestoreLocalDraftAfterConflict = useCallback(() => {
    if (conflictLocalDraftBackup.length === 0) {
      return;
    }
    setDraftNewVersionSteps(conflictLocalDraftBackup);
    setDraftParseStatus("ready");
    setDraftParseError("");
    setExpandedDraftDiffKeys([]);
    setConflictRestoreAvailable(false);
    message.success(t("pipelines.conflictLocalRestored", "已恢复本地草稿，请确认后重新保存。"));
  }, [conflictLocalDraftBackup, t]);

  const handleUseRemoteDraftAfterConflict = useCallback(() => {
    if (conflictRemoteDraftBackup.length === 0) {
      return;
    }
    setDraftNewVersionSteps(conflictRemoteDraftBackup);
    setDraftParseStatus("ready");
    setDraftParseError("");
    setExpandedDraftDiffKeys([]);
    setConflictRestoreAvailable(true);
    setConflictMergeAvailable(false);
    message.success(t("pipelines.conflictRemoteApplied", "已采用远端草稿。"));
  }, [conflictRemoteDraftBackup, t]);

  const handleMergeDraftAfterConflict = useCallback(() => {
    if (conflictRemoteDraftBackup.length === 0 || conflictLocalDraftBackup.length === 0) {
      return;
    }
    const merged = mergeDraftStepsByStepId(
      conflictRemoteDraftBackup,
      conflictLocalDraftBackup,
    );
    setDraftNewVersionSteps(merged);
    setDraftParseStatus("ready");
    setDraftParseError("");
    setExpandedDraftDiffKeys([]);
    setConflictRestoreAvailable(true);
    setConflictMergeAvailable(false);
    message.success(t("pipelines.conflictMerged", "已按 step_id 合并本地与远端草稿。"));
  }, [conflictLocalDraftBackup, conflictRemoteDraftBackup, t]);

  const requestCloseEditMode = () => {
    if (!selectedIsDraft) {
      closeEditMode();
      return;
    }

    Modal.confirm({
      title: t("pipelines.unsavedDraftTitle", "存在未保存草稿"),
      content: t(
        "pipelines.unsavedExitConfirm",
        "当前流程草稿尚未保存，退出编辑后改动可能丢失。是否继续？",
      ),
      okText: t("common.confirm", "确认"),
      cancelText: t("common.cancel", "取消"),
      onOk: () => {
        closeEditMode();
      },
    });
  };

  const requestSelectPipeline = (nextPipelineKey: string) => {
    if (!(editMode && selectedIsDraft && selectedPipelineKey !== nextPipelineKey)) {
      setSelectedPipelineKey(nextPipelineKey);
      setSelectedCompareVersion("");
      return;
    }

    Modal.confirm({
      title: t("pipelines.unsavedDraftTitle", "存在未保存草稿"),
      content: t(
        "pipelines.unsavedSwitchConfirm",
        "当前流程草稿尚未保存，切换流程后改动可能丢失。是否继续切换？",
      ),
      okText: t("common.confirm", "确认"),
      cancelText: t("common.cancel", "取消"),
      onOk: () => {
        closeEditMode();
        setSelectedPipelineKey(nextPipelineKey);
        setSelectedCompareVersion("");
      },
    });
  };

  const newVersionDiffItems = useMemo(
    () =>
      compareTemplate && currentTemplate
        ? buildStepDiff(compareTemplate.steps, currentTemplate.steps)
        : [],
    [compareTemplate, currentTemplate],
  );

  const realtimeDraftDiffItems = useMemo(
    () =>
      currentTemplate && draftNewVersionSteps.length > 0
        ? buildStepDiff(draftNewVersionSteps, currentTemplate.steps)
        : [],
    [currentTemplate, draftNewVersionSteps],
  );

  const draftDiffDetailKeys = useMemo(
    () => realtimeDraftDiffItems.map((item) => `${item.kind}:${item.id}`),
    [realtimeDraftDiffItems],
  );

  const allDraftDiffExpanded = useMemo(
    () =>
      draftDiffDetailKeys.length > 0 &&
      draftDiffDetailKeys.every((key) => expandedDraftDiffKeys.includes(key)),
    [draftDiffDetailKeys, expandedDraftDiffKeys],
  );

  const runningCount = useMemo(
    () => runs.filter((run) => run.status === "running").length,
    [runs],
  );

  const visibleRuns = useMemo(() => {
    const base = selectedPipeline
      ? selectedPipeline.source === "project"
        ? runs.filter((run) => run.template_id === selectedPipeline.id)
        : []
      : runs;
    return base.slice(0, 30);
  }, [runs, selectedPipeline]);

  useEffect(() => {
    if (!selectedAgent) return;

    const draftTemplates = templates.filter((item) =>
      draftPipelineKeys.includes(buildPipelineGroupKey(item.id, getTemplateSourceKind(item))),
    );

    if (draftTemplates.length === 0) {
      clearPipelineDraftState(selectedAgent);
      return;
    }

    writePipelineDraftState(selectedAgent, {
      version: 1,
      templates: draftTemplates,
      draftPipelineKeys,
      selectedPipelineKey,
      selectedCurrentVersion,
      selectedCompareVersion,
      sourceFilter,
      draftNewVersionSteps,
      draftParseStatus,
      draftParseError,
    });
  }, [
    draftNewVersionSteps,
    draftParseError,
    draftParseStatus,
    draftPipelineKeys,
    selectedAgent,
    selectedCompareVersion,
    selectedCurrentVersion,
    selectedPipelineKey,
    sourceFilter,
    templates,
  ]);

  useEffect(() => {
    if (pipelineGroups.length === 0) {
      setSelectedPipelineKey("");
      setSelectedCurrentVersion("");
      setSelectedCompareVersion("");
      return;
    }

    if (!pipelineGroups.some((item) => item.key === selectedPipelineKey)) {
      setSelectedPipelineKey(pipelineGroups[0].key);
    }
  }, [pipelineGroups, selectedPipelineKey]);

  useEffect(() => {
    if (!selectedPipeline) {
      setSelectedCurrentVersion("");
      setSelectedCompareVersion("");
      return;
    }

    const versions = selectedPipeline.versions;
    if (versions.length === 0) {
      setSelectedCurrentVersion("");
      setSelectedCompareVersion("");
      return;
    }

    if (!versions.some((item) => normalizeVersion(item.version) === selectedCurrentVersion)) {
      setSelectedCurrentVersion(normalizeVersion(versions[0].version));
    }

    if (
      selectedCompareVersion &&
      !versions.some((item) => normalizeVersion(item.version) === selectedCompareVersion)
    ) {
      setSelectedCompareVersion("");
    }
  }, [selectedCompareVersion, selectedCurrentVersion, selectedPipeline]);

  useEffect(() => {
    if (selectedCompareVersion && selectedCompareVersion === selectedCurrentVersion) {
      setSelectedCompareVersion("");
    }
  }, [selectedCompareVersion, selectedCurrentVersion]);

  const resolveBoundChat = useCallback(
    async (bindingKey: string): Promise<ChatSpec | null> => {
      const chats = await chatApi.listChats({ user_id: "default", channel: "console" });
      const matched = chats.filter((chat) => {
        const meta =
          chat.meta && typeof chat.meta === "object"
            ? (chat.meta as Record<string, unknown>)
            : undefined;
        const metaType = getMetaString(meta, "binding_type");
        const metaKey = getMetaString(meta, "pipeline_binding_key");
        const metaAgentId = getMetaString(meta, "agent_id");

        if (metaType !== "pipeline_edit" || metaKey !== bindingKey) {
          return false;
        }
        if (selectedAgent && metaAgentId && metaAgentId !== selectedAgent) {
          return false;
        }
        return true;
      });

      if (matched.length === 0) return null;

      const toMillis = (value?: string | null): number => {
        if (!value) return 0;
        const ts = Date.parse(value);
        return Number.isFinite(ts) ? ts : 0;
      };

      matched.sort((a, b) => {
        const tsA = toMillis(a.updated_at) || toMillis(a.created_at);
        const tsB = toMillis(b.updated_at) || toMillis(b.created_at);
        return tsB - tsA;
      });

      return matched[0] || null;
    },
    [selectedAgent],
  );

  const injectPipelineContext = useCallback(
    async (
      chat: Pick<ChatSpec, "id" | "session_id" | "user_id" | "channel">,
      target: EditChatTarget,
      mdRelativePath?: string,
      flowMemoryRelativePath?: string,
    ) => {
      const prompt = buildPipelineDesignEditContextPrompt({
        agentId: selectedAgent,
        source: "pipelines_page",
        scope: target.source || "independent",
        pipelineId: target.pipelineId,
        pipelineName: target.pipelineName,
        version: normalizeVersion(target.version),
        description: target.description || "",
        steps: target.steps || [],
        mdRelativePath,
        flowMemoryRelativePath,
      });

      sessionApi.setLastUserMessage(chat.id, prompt);
      if (chat.session_id) {
        sessionApi.setLastUserMessage(chat.session_id, prompt);
      }

      await chatApi.startConsoleChat({
        sessionId: chat.session_id || chat.id,
        prompt,
        userId: chat.user_id || "default",
        channel: chat.channel || "console",
      });
    },
    [selectedAgent],
  );

  const handleOpenDesignChat = async (withEditMode = false, target?: EditChatTarget) => {
    setDesignChatStarting(true);
    try {
      const source = "pipelines_page" as const;
      const targetPipelineName = target?.pipelineName || selectedPipeline?.name || selectedPipeline?.id || "unknown";
      const targetVersion = normalizeVersion(target?.version || currentTemplate?.version || "latest");
      const targetScope = target?.source || selectedPipeline?.source || "independent";
      const targetDescription = target?.description || currentTemplate?.description || "";
      const fallbackSteps = buildPrefilledPipelineTemplateSteps();
      const targetSteps = (target?.steps && target.steps.length > 0)
        ? target.steps
        : (currentTemplate?.steps && currentTemplate.steps.length > 0)
          ? currentTemplate.steps
          : fallbackSteps;
      const isEmptyNodes = target?.isEmptyNodes ?? (targetSteps.length === 0);
      const normalizedTarget: EditChatTarget = {
        pipelineId: target?.pipelineId || selectedPipeline?.id || "unknown",
        pipelineName: targetPipelineName,
        version: targetVersion,
        isEmptyNodes,
        description: targetDescription,
        steps: targetSteps,
        source: targetScope,
      };
      let mdRelativePath = "";
      let flowMemoryRelativePath = "";
      if (withEditMode && selectedAgent && normalizedTarget.pipelineId !== "unknown") {
        try {
          const draftInfo = await agentsApi.getPipelineDraft(selectedAgent, normalizedTarget.pipelineId);
          mdRelativePath = draftInfo.md_relative_path || "";
          flowMemoryRelativePath = draftInfo.flow_memory_relative_path || "";
          setLastDraftMdMtime(draftInfo.md_mtime || 0);
        } catch {
          setLastDraftMdMtime(0);
        }
      }
      const targetKey = buildPipelineDesignBindingKey({
        pipelineId: normalizedTarget.pipelineId,
        version: normalizedTarget.version,
      });

      const seedTask = withEditMode
        ? `编辑已有流程: ${targetPipelineName} (${targetVersion})\n请先分析当前节点并给出可执行的改造建议。`
        : undefined;
      const editGuide = t(
        isEmptyNodes
          ? "pipelines.editInputPlaceholderInit"
          : "pipelines.editInputPlaceholder",
        isEmptyNodes
          ? "这是一个新流程，请先定义目标、关键步骤和完成标准，我会帮你生成首版节点草案。"
          : "围绕当前流程 {{name}} ({{version}}) 描述你的改造目标，例如：新增校验节点、调整重试策略、优化输出结构。",
        {
          name: targetPipelineName,
          version: targetVersion,
        },
      );

      if (withEditMode) {
        const reusedInMemory =
          designChatSessionId && editTargetKey === targetKey
            ? ({
                id: designChatSessionId,
                session_id: designChatSessionId,
                user_id: "default",
                channel: "console",
              } as ChatSpec)
            : null;

        const restored = reusedInMemory || (await resolveBoundChat(targetKey));
        if (restored) {
          setDesignChatSessionId(restored.id);
          const prefilledDraft = isEmptyNodes ? buildPrefilledPipelineTemplateSteps() : [];
          setDraftNewVersionSteps(prefilledDraft);
          setDraftParseStatus(prefilledDraft.length > 0 ? "ready" : "idle");
          setDraftParseError("");
          setExpandedDraftDiffKeys([]);
          setEditMode(true);
          setEditTargetKey(targetKey);
          setEditWelcomeMode(isEmptyNodes ? "init" : "default");
          setEditGuidePlaceholder(editGuide);

          try {
            await injectPipelineContext(
              restored,
              normalizedTarget,
              mdRelativePath,
              flowMemoryRelativePath,
            );
            message.success(
              t("pipelines.boundSessionRestored", "已恢复流程绑定会话，并同步当前流程上下文。"),
            );
          } catch (error) {
            console.error("failed to inject pipeline context on restored session", error);
            message.warning(
              t("pipelines.boundSessionContextFailed", "已恢复绑定会话，但同步当前流程上下文失败。"),
            );
          }
          return;
        }
      }

      const bindingMeta = buildPipelineChatBindingMeta({
        pipelineId: normalizedTarget.pipelineId,
        pipelineName: normalizedTarget.pipelineName,
        version: normalizedTarget.version,
        scope: normalizedTarget.source || "independent",
        agentId: selectedAgent,
        flowMemoryPath:
          flowMemoryRelativePath ||
          (normalizedTarget.pipelineId && normalizedTarget.pipelineId !== "unknown"
            ? buildPipelineFlowMemoryRelativePath(normalizedTarget.pipelineId)
            : undefined),
      });

      const created = await chatApi.createChat({
        name: t("pipelines.designSessionName", "Pipeline Design"),
        session_id: buildPipelineEntrySessionId(),
        user_id: "default",
        channel: "console",
        meta: withEditMode ? bindingMeta : {},
      });

      setDesignChatSessionId(created.id);
      if (withEditMode) {
        const prefilledDraft = isEmptyNodes ? buildPrefilledPipelineTemplateSteps() : [];
        setDraftNewVersionSteps(prefilledDraft);
        setDraftParseStatus(prefilledDraft.length > 0 ? "ready" : "idle");
        setDraftParseError("");
        setExpandedDraftDiffKeys([]);
        setEditMode(true);
        setEditTargetKey(targetKey);
        setEditWelcomeMode(isEmptyNodes ? "init" : "default");
        setEditGuidePlaceholder(editGuide);

        try {
          await injectPipelineContext(
            created,
            normalizedTarget,
            mdRelativePath,
            flowMemoryRelativePath,
          );
          message.success(
            t("pipelines.boundSessionCreated", "已创建流程绑定会话，并同步当前流程上下文。"),
          );
        } catch (error) {
          console.error("failed to inject pipeline context on new session", error);
          message.warning(
            t("pipelines.boundSessionContextFailed", "已恢复绑定会话，但同步当前流程上下文失败。"),
          );
        }
        return;
      }

      const bootstrapPrompt = buildPipelineDesignBootstrapPrompt({
        source,
        agentId: selectedAgent,
        seedTask,
      });

      // Cache the bootstrap prompt so Chat page can show a local user bubble
      // before backend persistence catches up.
      sessionApi.setLastUserMessage(created.id, bootstrapPrompt);
      if (created.session_id) {
        sessionApi.setLastUserMessage(created.session_id, bootstrapPrompt);
      }

      await chatApi.startConsoleChat({
        sessionId: created.session_id || created.id,
        prompt: bootstrapPrompt,
        userId: created.user_id || "default",
        channel: created.channel || "console",
      });

      const to = buildPipelineDesignChatPath(created.id);
      trackNavigation({
        source: "pipelines.handleOpenDesignChat",
        from: "/pipelines",
        to,
        reason: "start-pipeline-design-chat-inline",
      });
    } catch (error) {
      console.error("failed to start pipeline design chat", error);
      message.error(
        t(
          "pipelines.startChatFailed",
          "Failed to start pipeline design chat. Please try again.",
        ),
      );
    } finally {
      setDesignChatStarting(false);
    }
  };

  const handleCreatePipelineAndEnterEdit = async () => {
    if (!selectedAgent) {
      message.warning(t("pipelines.noAgent", "No active agent selected."));
      return;
    }

    const now = Date.now();
    const draftId = `pipeline-${now}`;
    const draftVersion = "0.1.0";
    const draftTemplate: TemplateItem = {
      id: draftId,
      name: t("pipelines.newPipelineName", "新流程"),
      version: draftVersion,
      description: t("pipelines.newPipelineDescription", "待补充流程说明"),
      steps: [],
      projectId: INDEPENDENT_PIPELINE_SCOPE_ID,
      projectName: t("pipelines.independentScope", "独立流程"),
    };

    const draftGroupKey = buildPipelineGroupKey(draftTemplate.id, "independent");
    setTemplates((prev) => [draftTemplate, ...prev]);
    setDraftPipelineKeys((prev) => Array.from(new Set([draftGroupKey, ...prev])));
    setSourceFilter("independent");
    setSelectedPipelineKey(draftGroupKey);
    setSelectedCurrentVersion(normalizeVersion(draftTemplate.version));
    setSelectedCompareVersion("");

    await handleOpenDesignChat(true, {
      pipelineId: draftTemplate.id,
      pipelineName: draftTemplate.name,
      version: draftTemplate.version,
      isEmptyNodes: true,
      description: draftTemplate.description,
      steps: draftTemplate.steps,
      source: "independent",
    });
  };

  const handleSaveDraftPipeline = async () => {
    if (!selectedAgent || !selectedTemplateItem) {
      return;
    }

    const templateId = (selectedTemplateItem.id || "").trim();
    const safeTemplateId = templateId
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "-")
      .replace(/^-+|-+$/g, "") || `pipeline-${Date.now()}`;

    const effectiveSteps =
      draftParseStatus === "ready" && draftNewVersionSteps.length > 0
        ? draftNewVersionSteps
        : (selectedTemplateItem.steps || []);

    const templateDoc = {
      id: safeTemplateId,
      name: selectedTemplateItem.name || safeTemplateId,
      version: selectedTemplateItem.version || "0.1.0",
      description: selectedTemplateItem.description || "",
      steps: effectiveSteps,
    };

    setDraftSaving(true);
    const saveToastKey = "pipelines-save-stream";
    try {
      const savedDraftId = selectedTemplateItem.id;
      const savedDraftKey = buildPipelineGroupKey(savedDraftId, "independent");
      const preservedDraftTemplates = templates.filter(
        (item) => {
          const key = buildPipelineGroupKey(item.id, getTemplateSourceKind(item));
          return draftPipelineKeys.includes(key) && key !== savedDraftKey;
        },
      );
      const preservedDraftKeys = draftPipelineKeys.filter((key) => key !== savedDraftKey);

      let hasStreamFailure = false;
      let streamFailureStatusCode = 0;
      let streamFailureDetail = "";
      let streamFailureDetailRaw: unknown = null;
      let streamReachedDone = false;
      setSaveStreamEvents([]);
      setSaveStreamError("");
      setSaveValidationErrors([]);
      setSaveConflictInfo(null);
      setConflictLocalDraftBackup([]);
      setConflictRemoteDraftBackup([]);
      setConflictRestoreAvailable(false);
      setConflictMergeAvailable(false);

      message.loading({
        key: saveToastKey,
        content: t("pipelines.saveDraftPending", "正在校验并保存流程..."),
        duration: 0,
      });

      try {
        await agentsApi.saveAgentPipelineTemplateStream(
          selectedAgent,
          safeTemplateId,
          {
            id: safeTemplateId,
            name: templateDoc.name,
            version: templateDoc.version,
            description: templateDoc.description,
            steps: templateDoc.steps,
          },
          (event) => {
            const detailText =
              typeof event.payload?.detail === "string"
                ? event.payload.detail
                : event.payload?.detail
                  ? JSON.stringify(event.payload.detail)
                  : "";
            setSaveStreamEvents((prev) => [
              ...prev.slice(-7),
              { event: event.event, ts: Date.now(), detail: detailText },
            ]);

            if (event.event === "saved") {
              message.loading({
                key: saveToastKey,
                content: t("pipelines.saveDraftSaved", "保存成功，正在刷新数据..."),
                duration: 0,
              });
            } else if (event.event === "validation_failed" || event.event === "save_failed") {
              const payload = event.payload || {};
              hasStreamFailure = true;
              streamFailureStatusCode = Number(payload.status_code || 0) || 500;
              streamFailureDetail =
                typeof payload.detail === "string"
                  ? payload.detail
                  : payload.detail
                    ? JSON.stringify(payload.detail)
                    : "";
              streamFailureDetailRaw = payload.detail;
              setSaveStreamError(streamFailureDetail || `${streamFailureStatusCode}`);

              const detailObj = payload.detail;
              if (detailObj && typeof detailObj === "object") {
                const maybeErrors = (detailObj as { errors?: unknown }).errors;
                if (Array.isArray(maybeErrors)) {
                  const normalized = maybeErrors.filter(
                    (item): item is PipelineValidationError =>
                      Boolean(item) && typeof item === "object" &&
                      typeof (item as { error_code?: unknown }).error_code === "string",
                  );
                  setSaveValidationErrors(normalized);
                }
              }
            } else if (event.event === "done") {
              streamReachedDone = true;
            }
          },
          {
            expectedRevision: selectedTemplateItem.revision,
          },
        );
      } catch (streamError) {
        // Fallback to non-stream save path if SSE is interrupted.
        console.warn("pipeline save stream failed, fallback to direct save", streamError);
        await agentsApi.saveAgentPipelineTemplate(
          selectedAgent,
          safeTemplateId,
          {
            id: safeTemplateId,
            name: templateDoc.name,
            version: templateDoc.version,
            description: templateDoc.description,
            steps: templateDoc.steps,
          },
          {
            expectedRevision: selectedTemplateItem.revision,
          },
        );
        streamReachedDone = true;
      }

      if (hasStreamFailure) {
        const conflictInfo = extractPipelineConflictInfo(streamFailureDetailRaw);
        if (conflictInfo) {
          setSaveConflictInfo(conflictInfo);
          setConflictLocalDraftBackup(draftNewVersionSteps);
          setConflictRemoteDraftBackup([]);
          setConflictMergeAvailable(false);
        }
        throw new Error(`${streamFailureStatusCode || 500} ${streamFailureDetail}`.trim());
      }

      if (!streamReachedDone) {
        throw new Error("Save stream ended unexpectedly");
      }

      const data = await loadPipelineManagementData(
        selectedAgent,
        projects,
        independentScopeLabel,
      );

      setTemplates([...preservedDraftTemplates, ...data.templates]);
      setRuns(data.runs);
      setDraftPipelineKeys(preservedDraftKeys);
      setSourceFilter("independent");
      setSelectedPipelineKey(buildPipelineGroupKey(safeTemplateId, "independent"));
      setSelectedCurrentVersion(normalizeVersion(templateDoc.version));
      setSelectedCompareVersion("");
      setDraftNewVersionSteps([]);
      setDraftParseStatus("idle");
      setDraftParseError("");
      setExpandedDraftDiffKeys([]);
      setLastDraftMdMtime(0);
      setSaveStreamError("");
      setSaveValidationErrors([]);
      setSaveConflictInfo(null);
      setConflictLocalDraftBackup([]);
      setConflictRemoteDraftBackup([]);
      setConflictRestoreAvailable(false);
      setConflictMergeAvailable(false);

      message.destroy(saveToastKey);
      message.success(t("pipelines.saveDraftSuccess", "流程已保存"));
    } catch (error) {
      console.error("failed to save draft pipeline", error);
      message.destroy(saveToastKey);
      const detailObj = extractPipelineDetailFromError(error);
      const parsedConflictInfo = extractPipelineConflictInfo(detailObj);
      if (parsedConflictInfo) {
        setSaveConflictInfo(parsedConflictInfo);
        setConflictLocalDraftBackup(draftNewVersionSteps);
        setConflictRemoteDraftBackup([]);
        setConflictMergeAvailable(false);
      }
      if (!saveStreamError) {
        setSaveStreamError(String(error));
      }
      message.error(t("pipelines.saveDraftFailed", "保存流程失败，请重试。"));
    } finally {
      setDraftSaving(false);
    }
  };

  const handleEnterEditMode = async () => {
    if (!selectedPipeline || !currentTemplate) {
      message.warning(t("pipelines.selectPipelineFirst", "Please select a pipeline first."));
      return;
    }

    const isEmptyNodes = (currentTemplate.steps?.length || 0) === 0;
    setEditWelcomeMode(isEmptyNodes ? "init" : "default");
    setEditGuidePlaceholder(
      t(
        isEmptyNodes
          ? "pipelines.editInputPlaceholderInit"
          : "pipelines.editInputPlaceholder",
        isEmptyNodes
          ? "这是一个新流程，请先定义目标、关键步骤和完成标准，我会帮你生成首版节点草案。"
          : "围绕当前流程 {{name}} ({{version}}) 描述你的改造目标，例如：新增校验节点、调整重试策略、优化输出结构。",
        {
          name: selectedPipeline.name || selectedPipeline.id || "unknown",
          version: currentTemplate.version || "latest",
        },
      ),
    );

    await handleOpenDesignChat(true, {
      pipelineId: selectedPipeline.id,
      pipelineName: selectedPipeline.name || selectedPipeline.id,
      version: currentTemplate.version || "latest",
      isEmptyNodes,
      description: currentTemplate.description || "",
      steps: currentTemplate.steps || [],
      source: selectedPipeline.source,
    });
  };

  const handleAssistantTurnCompleted = useCallback(
    (payload: { text: string; response: Record<string, unknown> | null }) => {
      if (!editMode) return;

      const parsedFromResponse = payload.response
        ? normalizeDraftSteps(payload.response)
        : null;
      const parsedTextJson = parseJsonFromText(payload.text);
      const parsedFromText = parsedTextJson
        ? normalizeDraftSteps(parsedTextJson)
        : null;

      const candidates = [parsedFromText, parsedFromResponse].filter(
        (item): item is DraftParseResult => Boolean(item),
      );

      const parsed =
        candidates.find((item) => item.steps.length > 0 && !item.error) ||
        candidates[0] ||
        null;

      if (!parsedTextJson && !parsedFromResponse) {
        // No JSON found in this turn — keep existing draft nodes unchanged.
        message.warning(
          t(
            "pipelines.draftParseNoJson",
            "未识别到可用 JSON，请让助手严格输出 schema_version=1 与 steps 数组。",
          ),
        );
      } else if (!parsed || parsed.error || parsed.steps.length === 0) {
        // JSON found but structurally invalid — keep existing draft nodes unchanged.
        message.warning(
          t(
            "pipelines.draftParseInvalid",
            "JSON 解析失败：{{detail}}",
            {
              detail:
                (parsed && parsed.error) ||
                "invalid step schema: each step requires id/name/kind.",
            },
          ),
        );
      } else {
        setDraftNewVersionSteps(parsed.steps);
        setDraftParseStatus("ready");
        setDraftParseError("");
        setExpandedDraftDiffKeys([]);
      }

      const activePipelineId = selectedPipeline?.id || selectedTemplateItem?.id || "";
      if (!selectedAgent || !activePipelineId) {
        return;
      }

      void agentsApi
        .getPipelineDraft(selectedAgent, activePipelineId)
        .then((draftInfo) => {
          if (draftInfo.validation_errors && draftInfo.validation_errors.length > 0) {
            const firstError = draftInfo.validation_errors[0];
            setSaveValidationErrors(draftInfo.validation_errors);
            message.warning(
              t(
                "pipelines.draftValidationFailed",
                "流程 Markdown 校验失败：{{detail}}",
                { detail: firstError.message || firstError.error_code || "unknown error" },
              ),
            );
            return;
          }

          const mdMtime = draftInfo.md_mtime || 0;
          if (mdMtime <= lastDraftMdMtime) {
            return;
          }

          setLastDraftMdMtime(mdMtime);
          if (!draftInfo.steps || draftInfo.steps.length === 0) {
            return;
          }

          setDraftNewVersionSteps(draftInfo.steps);
          setDraftParseStatus("ready");
          setDraftParseError("");
          setExpandedDraftDiffKeys([]);
        })
        .catch(() => {
          // Ignore when draft markdown does not exist yet.
        });
    },
    [editMode, lastDraftMdMtime, selectedAgent, selectedPipeline?.id, selectedTemplateItem?.id, t],
  );

  const toggleDraftDiffDetails = useCallback((key: string) => {
    setExpandedDraftDiffKeys((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key],
    );
  }, []);

  const toggleAllDraftDiffDetails = useCallback(() => {
    setExpandedDraftDiffKeys(allDraftDiffExpanded ? [] : draftDiffDetailKeys);
  }, [allDraftDiffExpanded, draftDiffDetailKeys]);

  const renderDiffTokenText = useCallback(
    (
      tokens: InlineDiffToken[],
      changedClassName: string,
      neutralClassName: string,
    ) => {
      if (draftDiffViewMode === "changedOnly") {
        return (
          <span className={changedClassName}>{buildChangedOnlyText(tokens)}</span>
        );
      }

      return tokens.map((token, tokenIndex) => (
        <span
          key={`${token.text}-${tokenIndex}`}
          className={token.changed ? changedClassName : neutralClassName}
        >
          {token.text}
        </span>
      ));
    },
    [draftDiffViewMode],
  );

  const renderDiffPair = useCallback(
    (detailKey: string, field: DiffFieldKey, oldValue: string, newValue: string) => {
      const tokenDiff = buildInlineDiffTokens(oldValue, newValue);

      return (
        <div key={`${detailKey}-${field}`} className={styles.diffDetailRow}>
          <Text strong>{field}</Text>
          <div className={styles.diffPairGrid}>
            <div className={`${styles.diffPairColumn} ${styles.diffPairOld}`}>
              <Text type="secondary" className={styles.diffPairLabel}>
                {t("pipelines.diffOldValue", "旧值")}
              </Text>
              <Text className={styles.diffOldText}>
                {renderDiffTokenText(
                  tokenDiff.oldTokens,
                  styles.diffTokenRemoved,
                  styles.diffTokenNeutral,
                )}
              </Text>
            </div>
            <div className={`${styles.diffPairColumn} ${styles.diffPairNew}`}>
              <Text type="secondary" className={styles.diffPairLabel}>
                {t("pipelines.diffNewValue", "新值")}
              </Text>
              <Text className={styles.diffNewText}>
                {renderDiffTokenText(
                  tokenDiff.newTokens,
                  styles.diffTokenAdded,
                  styles.diffTokenNeutral,
                )}
              </Text>
            </div>
          </div>
        </div>
      );
    },
    [renderDiffTokenText, t],
  );

  useEffect(() => {
    setExpandedDraftDiffKeys((prev) =>
      prev.filter((key) => draftDiffDetailKeys.includes(key)),
    );
  }, [draftDiffDetailKeys]);

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <div>
          <Title level={3} className={styles.title}>
            {t("pipelines.title", "Pipelines")}
          </Title>
          <Text className={styles.subtitle}>
            {t(
              "pipelines.description",
              "Manage reusable pipeline definitions across projects, then validate and tune in Projects.",
            )}
          </Text>
        </div>
        <div className={styles.actions}>
          <Select
            size="small"
            value={sourceFilter}
            style={{ width: 180 }}
            onChange={(value) => setSourceFilter(value)}
            options={[
              { value: "all", label: t("pipelines.sourceFilterAll", "全部来源") },
              { value: "independent", label: t("pipelines.sourceFilterIndependent", "仅独立模板") },
              { value: "project", label: t("pipelines.sourceFilterProject", "仅项目模板") },
            ]}
          />
          <Button
            data-testid="pipeline-open-design-chat"
            loading={designChatStarting}
            disabled={designChatStarting}
            onClick={() => void handleCreatePipelineAndEnterEdit()}
          >
            {t("pipelines.create", "新建")}
          </Button>
          <Button type="primary" onClick={() => navigate("/projects")}>
            {t("pipelines.openProjects", "Open Projects to Run")}
          </Button>
        </div>
      </div>

      {projects.length === 0 ? (
        <Card size="small" style={{ marginBottom: 16 }}>
          <Text type="secondary">
            {t(
              "pipelines.noProjectsIndependentHint",
              "当前没有项目，但你仍可新建与编辑独立流程草稿。需要落盘时请先创建项目。",
            )}
          </Text>
        </Card>
      ) : null}

      <div className={styles.metrics}>
        <Card size="small" className={styles.metricCard}>
          <Text className={styles.metricLabel}>
            {t("pipelines.totalTemplates", "Template Variants")}
          </Text>
          <div className={styles.metricValue}>{templates.length}</div>
        </Card>
        <Card size="small" className={styles.metricCard}>
          <Text className={styles.metricLabel}>
            {t("pipelines.totalRuns", "Total Runs")}
          </Text>
          <div className={styles.metricValue}>{runs.length}</div>
        </Card>
        <Card size="small" className={styles.metricCard}>
          <Text className={styles.metricLabel}>
            {t("pipelines.runningRuns", "Running")}
          </Text>
          <div className={styles.metricValue}>{runningCount}</div>
        </Card>
      </div>

      <div className={styles.content}>
        {loading ? (
          <div className={styles.loadingWrap}>
            <Spin size="large" />
          </div>
        ) : error ? (
          <Card>
            <Text type="danger">{error}</Text>
          </Card>
        ) : !currentAgent ? (
          <Card>
            <Empty
              description={t("pipelines.noAgent", "No active agent selected.")}
            />
          </Card>
        ) : projects.length === 0 && templates.length === 0 ? (
          <Card>
            <Empty
              description={t(
                "pipelines.noProjects",
                "No projects found for the current agent.",
              )}
            />
          </Card>
        ) : (
          <div className={styles.columns}>
            <Card
              title={t("pipelines.library", "Pipeline Library")}
              className={styles.columnCard}
            >
              {pipelineGroups.length === 0 ? (
                <Empty
                  description={t(
                    "pipelines.emptyTemplates",
                    "No pipeline templates found yet.",
                  )}
                />
              ) : (
                <div className={styles.list}>
                  {pipelineGroups.map((item) => {
                    const selected = item.key === selectedPipelineKey;
                    return (
                      <button
                        key={item.key}
                        type="button"
                        className={`${styles.listItem} ${selected ? styles.selected : ""}`}
                        onClick={() => requestSelectPipeline(item.key)}
                      >
                        <div className={styles.listItemHeader}>
                          <Text strong>{item.name}</Text>
                          <Tag>{item.versions.length}</Tag>
                          <Tag color={item.source === "independent" ? "cyan" : "gold"}>
                            {item.source === "independent"
                              ? t("pipelines.sourceIndependent", "独立")
                              : t("pipelines.sourceProject", "项目")}
                          </Tag>
                          {draftPipelineKeys.includes(item.key) ? (
                            <Tag color="warning">
                              {t("pipelines.draftBadge", "未保存")}
                            </Tag>
                          ) : null}
                        </div>
                        <Text type="secondary">{item.description || item.id}</Text>
                        <Text type="secondary" className={styles.helperText}>
                          {t("pipelines.versionCount", "Versions: {{count}}", {
                            count: item.versions.length,
                          })}
                        </Text>
                        <Text type="secondary" className={styles.helperText}>
                          {t("pipelines.usedIn", "Used in {{count}} projects", {
                            count: item.projects.length,
                          })}
                        </Text>
                      </button>
                    );
                  })}
                </div>
              )}
            </Card>

            <Card
              title={t("pipelines.nodes", "Current Nodes")}
              className={styles.columnCard}
              extra={
                <div className={styles.nodesActions}>
                  <Select
                    size="small"
                    className={styles.versionSelect}
                    value={selectedCurrentVersion || undefined}
                    placeholder={t("pipelines.currentVersion", "Current version")}
                    options={(selectedPipeline?.versions || []).map((item) => ({
                      label: item.version || "0",
                      value: normalizeVersion(item.version),
                    }))}
                    onChange={(value) => {
                      setSelectedCurrentVersion(value);
                      if (value === selectedCompareVersion) {
                        setSelectedCompareVersion("");
                      }
                    }}
                  />
                  {editMode ? (
                    <>
                      {selectedIsDraft ? (
                        <Button
                          size="small"
                          type="primary"
                          loading={draftSaving}
                          disabled={draftSaving}
                          onClick={() => void handleSaveDraftPipeline()}
                        >
                          {t("pipelines.saveDraft", "保存")}
                        </Button>
                      ) : null}
                      <Button
                        size="small"
                        onClick={requestCloseEditMode}
                      >
                        {t("pipelines.exitEdit", "Exit Edit")}
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="small"
                      type="primary"
                      loading={designChatStarting}
                      disabled={!currentTemplate || designChatStarting}
                      onClick={() => void handleEnterEditMode()}
                    >
                      {t("pipelines.enterEdit", "Edit Pipeline")}
                    </Button>
                  )}
                </div>
              }
            >
              {!currentTemplate ? (
                <Empty
                  description={t(
                    "pipelines.selectPipeline",
                    "Select a pipeline to view nodes.",
                  )}
                />
              ) : currentTemplate.steps.length === 0 ? (
                <Empty
                  description={t(
                    "pipelines.emptyNodes",
                    "No nodes in this pipeline version.",
                  )}
                />
              ) : (
                <div className={styles.list}>
                  {currentTemplate.steps.map((step) => (
                    <div key={step.id} className={styles.listItemStatic}>
                      <div className={styles.listItemHeader}>
                        <Text strong>{step.name}</Text>
                        <Tag color="blue">{step.kind}</Tag>
                      </div>
                      <Text type="secondary">{step.id}</Text>
                      <Text type="secondary" className={styles.helperText}>
                        {step.description || "-"}
                      </Text>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card
              title={t("pipelines.newVersionNodes", "New Version Nodes")}
              className={styles.columnCard}
              extra={
                <div className={styles.newVersionActions}>
                  {editMode && draftParseStatus === "ready" && realtimeDraftDiffItems.length > 0 ? (
                    <Button
                      size="small"
                      onClick={() =>
                        setDraftDiffViewMode((prev) =>
                          prev === "changedOnly" ? "full" : "changedOnly",
                        )
                      }
                    >
                      {draftDiffViewMode === "changedOnly"
                        ? t("pipelines.diffViewFull", "显示全文")
                        : t("pipelines.diffViewChangedOnly", "只看变化")}
                    </Button>
                  ) : null}
                  {editMode && draftParseStatus === "ready" && realtimeDraftDiffItems.length > 0 ? (
                    <Button size="small" onClick={toggleAllDraftDiffDetails}>
                      {allDraftDiffExpanded
                        ? t("pipelines.diffCollapseAll", "收起全部")
                        : t("pipelines.diffExpandAll", "展开全部")}
                    </Button>
                  ) : null}
                  <Select
                    size="small"
                    className={styles.versionSelect}
                    value={selectedCompareVersion || undefined}
                    allowClear
                    placeholder={t("pipelines.compareVersion", "Select history version")}
                    options={(selectedPipeline?.versions || [])
                      .filter((item) => normalizeVersion(item.version) !== selectedCurrentVersion)
                      .map((item) => ({
                        label: item.version || "0",
                        value: normalizeVersion(item.version),
                      }))}
                    onChange={(value) => setSelectedCompareVersion(value || "")}
                  />
                </div>
              }
            >
              {editMode && (saveStreamEvents.length > 0 || saveStreamError) ? (
                <div className={styles.saveStreamPanel}>
                  <Text type="secondary" className={styles.saveStreamTitle}>
                    {t("pipelines.saveStreamTimeline", "保存事件")}
                  </Text>
                  {saveStreamEvents.map((item, index) => (
                    <Text key={`${item.event}-${item.ts}-${index}`} type="secondary" className={styles.saveStreamItem}>
                      {new Date(item.ts).toLocaleTimeString()} · {item.event}
                      {item.detail ? ` · ${item.detail}` : ""}
                    </Text>
                  ))}
                  {saveStreamError ? (
                    <Text type="danger" className={styles.saveStreamError}>
                      {t("pipelines.saveStreamError", "保存失败：{{detail}}", {
                        detail: saveStreamError,
                      })}
                    </Text>
                  ) : null}
                  {saveValidationErrors.length > 0 ? (
                    <div className={styles.validationErrorList}>
                      {saveValidationErrors.map((item, index) => (
                        <div key={`${item.error_code}-${item.field_path}-${index}`} className={styles.validationErrorItem}>
                          <Text type="danger" className={styles.validationErrorTitle}>
                            {item.error_code} · {item.field_path || "unknown_field"}
                          </Text>
                          <Text type="secondary" className={styles.validationErrorText}>
                            {item.message}
                          </Text>
                          {item.step_id ? (
                            <Text type="secondary" className={styles.validationErrorText}>
                              step_id: {item.step_id}
                            </Text>
                          ) : null}
                          {item.suggestion ? (
                            <Text type="secondary" className={styles.validationErrorText}>
                              suggestion: {item.suggestion}
                            </Text>
                          ) : null}
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {saveConflictInfo ? (
                    <div className={styles.conflictPanel}>
                      <Text type="warning" className={styles.conflictTitle}>
                        {t("pipelines.conflictTitle", "检测到并发冲突")}
                      </Text>
                      <Text type="secondary" className={styles.validationErrorText}>
                        {t(
                          "pipelines.conflictDetail",
                          "本地预期 revision={{expected}}，远端当前 revision={{current}}。",
                          {
                            expected: saveConflictInfo.expectedRevision,
                            current: saveConflictInfo.currentRevision,
                          },
                        )}
                      </Text>
                      {saveConflictInfo.currentContentHash ? (
                        <Text type="secondary" className={styles.validationErrorText}>
                          hash: {saveConflictInfo.currentContentHash}
                        </Text>
                      ) : null}
                      <Button size="small" onClick={() => void handleRefreshAfterConflict()}>
                        {t("pipelines.conflictRefresh", "刷新后重试")}
                      </Button>
                      {conflictRemoteDraftBackup.length > 0 ? (
                        <Button size="small" onClick={() => void handleUseRemoteDraftAfterConflict()}>
                          {t("pipelines.conflictUseRemote", "采用远端草稿")}
                        </Button>
                      ) : null}
                      {conflictMergeAvailable ? (
                        <Button size="small" onClick={() => void handleMergeDraftAfterConflict()}>
                          {t("pipelines.conflictMerge", "按 step_id 合并")}
                        </Button>
                      ) : null}
                      {conflictRestoreAvailable ? (
                        <Button size="small" onClick={() => void handleRestoreLocalDraftAfterConflict()}>
                          {t("pipelines.conflictRestoreLocal", "恢复本地草稿")}
                        </Button>
                      ) : null}
                    </div>
                  ) : null}
                </div>
              ) : null}

              {editMode && draftParseStatus === "ready" && draftNewVersionSteps.length > 0 ? (
                <>
                  <Text type="secondary" className={styles.draftStatusText}>
                    {t("pipelines.draftRealtimeReady", "已根据最新对话更新节点草稿")}
                  </Text>
                  <div className={styles.list}>
                    {realtimeDraftDiffItems.map((item) => (
                      <div key={`draft-${item.kind}-${item.id}`} className={styles.listItemStatic}>
                        <div className={styles.listItemHeader}>
                          <Text strong>{item.current?.name || item.compare?.name || item.id}</Text>
                          <Tag
                            color={
                              item.kind === "added"
                                ? "success"
                                : item.kind === "removed"
                                  ? "error"
                                  : item.kind === "changed"
                                    ? "warning"
                                    : "default"
                            }
                          >
                            {item.kind === "added"
                              ? t("pipelines.diffAdded", "Added")
                              : item.kind === "removed"
                                ? t("pipelines.diffRemoved", "Removed")
                                : item.kind === "changed"
                                  ? t("pipelines.diffChanged", "Changed")
                                  : t("pipelines.diffUnchanged", "Unchanged")}
                          </Tag>
                          {item.current?.kind ? <Tag color="processing">{item.current.kind}</Tag> : null}
                        </div>
                        <Text type="secondary">{item.id}</Text>
                        <Text type="secondary" className={styles.helperText}>
                          {item.current?.description || item.compare?.description || "-"}
                        </Text>
                        {(() => {
                          const detailKey = `${item.kind}:${item.id}`;
                          const expanded = expandedDraftDiffKeys.includes(detailKey);
                          return (
                            <>
                              <Button
                                type="link"
                                size="small"
                                className={styles.diffDetailToggle}
                                onClick={() => toggleDraftDiffDetails(detailKey)}
                              >
                                {expanded
                                  ? t("pipelines.diffDetailHide", "收起详情")
                                  : t("pipelines.diffDetailShow", "查看详情")}
                              </Button>
                              {expanded ? (
                                <div className={styles.diffDetailPanel}>
                                  {item.kind === "changed" ? (
                                    item.changedFields.map((field) => {
                                      const typedField = field as DiffFieldKey;
                                      return renderDiffPair(
                                        detailKey,
                                        typedField,
                                        getStepFieldValue(item.compare, typedField),
                                        getStepFieldValue(item.current, typedField),
                                      );
                                    })
                                  ) : item.kind === "added" ? (
                                    (["name", "kind", "description"] as DiffFieldKey[]).map((field) => {
                                      return renderDiffPair(
                                        detailKey,
                                        field,
                                        "-",
                                        getStepFieldValue(item.current, field),
                                      );
                                    })
                                  ) : (
                                    (["name", "kind", "description"] as DiffFieldKey[]).map((field) => {
                                      return renderDiffPair(
                                        detailKey,
                                        field,
                                        getStepFieldValue(item.compare, field),
                                        "-",
                                      );
                                    })
                                  )}
                                </div>
                              ) : null}
                            </>
                          );
                        })()}
                        {item.kind === "changed" && item.changedFields.length > 0 ? (
                          <Text type="secondary" className={styles.helperText}>
                            {t("pipelines.diffFields", "Changed: {{fields}}", {
                              fields: item.changedFields.join(", "),
                            })}
                          </Text>
                        ) : null}
                      </div>
                    ))}
                  </div>
                </>
              ) : editMode && draftParseStatus === "error" ? (
                <Empty description={draftParseError || t("pipelines.draftParseError", "节点草稿解析失败")} />
              ) : editMode ? (
                <Empty
                  description={t(
                    "pipelines.draftRealtimeHint",
                    "在右侧编辑对话中输出节点 JSON 草案后，这里会实时更新。",
                  )}
                />
              ) : !compareTemplate ? (
                <Empty
                  description={t(
                    "pipelines.selectNewVersion",
                    "Select a version as the new draft to compare with current nodes.",
                  )}
                />
              ) : newVersionDiffItems.length === 0 ? (
                <Empty
                  description={t(
                    "pipelines.noDiff",
                    "No diff available for this version pair.",
                  )}
                />
              ) : (
                <div className={styles.list}>
                  {newVersionDiffItems.map((item) => (
                    <div key={`${item.kind}-${item.id}`} className={styles.listItemStatic}>
                      <div className={styles.listItemHeader}>
                        <Text strong>{item.current?.name || item.compare?.name || item.id}</Text>
                        <Tag
                          color={
                            item.kind === "added"
                              ? "success"
                              : item.kind === "removed"
                                ? "error"
                                : item.kind === "changed"
                                  ? "warning"
                                  : "default"
                          }
                        >
                          {item.kind === "added"
                            ? t("pipelines.diffAdded", "Added")
                            : item.kind === "removed"
                              ? t("pipelines.diffRemoved", "Removed")
                              : item.kind === "changed"
                                ? t("pipelines.diffChanged", "Changed")
                                : t("pipelines.diffUnchanged", "Unchanged")}
                        </Tag>
                      </div>
                      <Text type="secondary">{item.id}</Text>
                      <Text type="secondary" className={styles.helperText}>
                        {item.current?.description || item.compare?.description || "-"}
                      </Text>
                      {item.kind === "changed" && item.changedFields.length > 0 && (
                        <Text type="secondary" className={styles.helperText}>
                          {t("pipelines.diffFields", "Changed: {{fields}}", {
                            fields: item.changedFields.join(", "),
                          })}
                        </Text>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>

            <Card
              title={editMode ? t("pipelines.editChat", "Pipeline Edit Chat") : t("pipelines.recentRuns", "Recent Runs")}
              className={`${styles.columnCard} ${editMode ? styles.chatColumn : ""}`}
              extra={
                editMode && designChatSessionId ? (
                  <Button size="small" onClick={() => navigate(`/chat/${designChatSessionId}`)}>
                    {t("pipelines.openInFullChat", "Open Full Chat")}
                  </Button>
                ) : undefined
              }
              styles={editMode ? { body: { padding: 0, height: "calc(100% - 56px)", overflow: "hidden" } } : undefined}
            >
              {editMode ? (
                designChatStarting ? (
                  <div className={styles.chatLoadingWrap}>
                    <Spin size="large" />
                  </div>
                ) : designChatSessionId ? (
                  <AnywhereChat
                    sessionId={designChatSessionId}
                    onAssistantTurnCompleted={handleAssistantTurnCompleted}
                    inputPlaceholder={editGuidePlaceholder || undefined}
                    welcomeGreeting={t(
                      editWelcomeMode === "init"
                        ? "pipelines.editWelcomeGreetingInit"
                        : "pipelines.editWelcomeGreeting",
                      editWelcomeMode === "init"
                        ? "新流程已创建，我们先把首版流程搭起来。"
                        : "流程编辑助手已就绪，你想先改哪一步？",
                    )}
                    welcomeDescription={t(
                      editWelcomeMode === "init"
                        ? "pipelines.editWelcomeDescriptionInit"
                        : "pipelines.editWelcomeDescription",
                      editWelcomeMode === "init"
                        ? "已预填首版模板，你可以直接在对话里按用途/输入/产物/步骤线索进行修改。"
                        : "我会基于当前流程结构给出节点级修改建议，并帮助你整理可执行的改造方案。",
                    )}
                    welcomePrompts={[
                      t(
                        editWelcomeMode === "init"
                          ? "pipelines.editWelcomePromptInit1"
                          : "pipelines.editWelcomePrompt1",
                        editWelcomeMode === "init"
                          ? "基于用途/输入/产物/步骤线索，修改右侧预填模板并返回完整 pipeline JSON。"
                          : "分析当前流程瓶颈，并给出 3 条可执行优化建议（含节点改动）。",
                      ),
                      t(
                        editWelcomeMode === "init"
                          ? "pipelines.editWelcomePromptInit2"
                          : "pipelines.editWelcomePrompt2",
                        editWelcomeMode === "init"
                          ? "若信息不足，先保留占位描述并最小修改，不要从零重建。"
                          : "我要改这个流程：新增校验节点、调整重试策略，并输出变更后的步骤清单。",
                      ),
                    ]}
                  />
                ) : (
                  <Empty
                    description={t(
                      "pipelines.chatPanelHint",
                      "Start a design chat to iterate without leaving this page.",
                    )}
                  />
                )
              ) : visibleRuns.length === 0 ? (
                <Empty
                  description={t(
                    "pipelines.emptyRuns",
                    "No pipeline runs yet.",
                  )}
                />
              ) : (
                <div className={styles.list}>
                  {visibleRuns.map((run) => (
                    <div key={run.id} className={styles.listItemStatic}>
                      <div className={styles.listItemHeader}>
                        <Text strong>{run.template_id}</Text>
                        <Tag color={statusTagColor(run.status)}>{run.status}</Tag>
                      </div>
                      <Text type="secondary">
                        {t("pipelines.projectLabel", "Project: {{name}}", {
                          name: run.projectName,
                        })}
                      </Text>
                      <Text type="secondary" className={styles.helperText}>
                        {run.updated_at || run.created_at}
                      </Text>
                      <div className={styles.runActions}>
                        <Button
                          size="small"
                          type="link"
                          className={styles.runLink}
                          onClick={() => {
                            setSourceFilter("project");
                            setSelectedPipelineKey(
                              buildPipelineGroupKey(run.template_id, "project"),
                            );
                            setSelectedCompareVersion("");
                          }}
                        >
                          {t("pipelines.focusPipeline", "Focus Pipeline")}
                        </Button>
                        <Button
                          size="small"
                          type="link"
                          className={styles.runLink}
                          onClick={() => navigate("/projects")}
                        >
                          {t("pipelines.goToProjects", "Go to Projects")}
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        )}
      </div>
    </div>
  );
}