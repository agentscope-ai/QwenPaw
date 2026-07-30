import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties, PointerEvent as ReactPointerEvent } from "react";
import { Button, Tooltip, message } from "antd";
import { ArrowUpOutlined } from "@ant-design/icons";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  CircleCheck,
  Eraser,
  Info,
  Loader2,
  PanelRightClose,
  PanelRightOpen,
  Square,
  XCircle,
} from "lucide-react";
import {
  getArtifactVersionMediaUrl,
  getAssetVersionMediaUrl,
  getGeneratedMediaUrl,
} from "@/api/creator";
import type {
  CreatorContentPart,
  CreatorMessage,
  ProjectDocument,
  RefSearchItem,
} from "@/contracts/creator";
import { useParams } from "@/routing/navigation";
import logoGlyphOrange from "@/assets/design/logo-glyph-orange.png";
import logoGlyphWhite from "@/assets/design/logo-mark-plain.png";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import {
  useCreatorSessionStore,
  type SubagentActivity,
  type SubagentStreamMessage,
  type SubagentStreamTool,
} from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";
import {
  creatorEventLabel,
  creatorRoleLabel,
  creatorStatusLabel,
  creatorTargetLabel,
  creatorToolLabel,
  getEstimatedDuration,
  taskKindLabel,
} from "@/lib/creatorPresentation";
import {
  actionAwareConversationContent,
  actionEnvelopeFromStreamText,
  conversationContent,
  creatorActionEnvelope,
  shouldRenderConversationMessage,
  toolCallPresentations,
  type CreatorActionEnvelope,
  type ToolCallPresentation,
} from "@/lib/creatorMessagePresentation";
import { deriveAgentLiveStatus } from "@/lib/agentLiveStatus";
import AgentEventFeed from "./AgentEventFeed";
import DecisionTray from "./DecisionTray";
import MentionInput, { type MentionInputHandle } from "./MentionInput";
import { reviewPendingUnits } from "./FileProjectReviewPanel";
import OnboardingHint from "@/components/onboarding/OnboardingHint";

interface DockSize {
  width: number;
  height: number;
}

const DOCK_MIN_WIDTH = 440;
const DOCK_MIN_HEIGHT = 420;
const DOCK_DEFAULT_SIZE: DockSize = { width: 440, height: 620 };
const DOCK_SIZE_STORAGE_KEY = "agentDock.size.v1";

// "Stoppable" check consistent with the global hard-stop (the stop button
// migrated here from the former AgentStatusBar).
const ACTIVE_RUN_STATUSES = new Set([
  "QUEUED",
  "QUEUED_CAPACITY",
  "RUNNING_MODEL",
  "WAITING_RUNTIME",
  "WAITING_AUTHORIZATION",
]);

const STOPPABLE_SESSION_STATUSES = [
  "RUNNING",
  "RESUMING",
  "WAITING_RUNTIME",
  "WAITING_EXECUTION_AUTH",
  "WAITING_USER_INPUT",
  "PENDING_REVIEW",
  "INTERRUPT_REQUESTED",
];

function dockMaxSize(): DockSize {
  if (typeof window === "undefined") return { width: 960, height: 1200 };
  return {
    width: Math.max(DOCK_MIN_WIDTH, window.innerWidth - 40),
    height: Math.max(DOCK_MIN_HEIGHT, window.innerHeight - 40),
  };
}

function clampDockSize(size: DockSize): DockSize {
  const maximum = dockMaxSize();
  return {
    width: Math.min(Math.max(size.width, DOCK_MIN_WIDTH), maximum.width),
    height: Math.min(Math.max(size.height, DOCK_MIN_HEIGHT), maximum.height),
  };
}

function loadDockSize(): DockSize {
  if (typeof window === "undefined") return DOCK_DEFAULT_SIZE;
  try {
    const raw = window.localStorage.getItem(DOCK_SIZE_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<DockSize>;
      if (
        typeof parsed.width === "number" &&
        typeof parsed.height === "number"
      ) {
        return clampDockSize({ width: parsed.width, height: parsed.height });
      }
    }
  } catch {
    // Local storage is optional; the visible default remains deterministic.
  }
  return DOCK_DEFAULT_SIZE;
}

function mediaUrl(rawUrl: string, assetVersionRef?: string): string {
  return assetVersionRef?.startsWith("asset-version:")
    ? getAssetVersionMediaUrl(assetVersionRef.slice("asset-version:".length))
    : getGeneratedMediaUrl(rawUrl);
}

const ASSISTANT_MARKDOWN_COMPONENTS: Components = {
  p: ({ children }) => (
    <p className="mb-2 whitespace-pre-wrap break-words last:mb-0">{children}</p>
  ),
  h1: ({ children }) => (
    <h1 className="mb-2 mt-3 text-[15px] font-semibold leading-6 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-1.5 mt-3 text-sm font-semibold leading-6 first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-1 mt-2 text-[13px] font-semibold leading-6 first:mt-0">
      {children}
    </h3>
  ),
  ul: ({ children }) => (
    <ul className="mb-2 list-disc space-y-0.5 pl-5 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-2 list-decimal space-y-0.5 pl-5 last:mb-0">{children}</ol>
  ),
  li: ({ children }) => <li className="pl-0.5">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="my-2 border-l-2 border-[var(--color-border-strong)] pl-2 text-[var(--color-text-secondary)]">
      {children}
    </blockquote>
  ),
  a: ({ children, href }) => (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="text-[var(--color-accent)] underline decoration-[var(--color-accent)]/40 underline-offset-2 hover:decoration-[var(--color-accent)]"
    >
      {children}
    </a>
  ),
  pre: ({ children }) => (
    <pre className="my-2 max-w-full overflow-x-auto rounded-md bg-[var(--color-bg-secondary)] p-2 text-[11px] leading-5 text-[var(--color-text-secondary)]">
      {children}
    </pre>
  ),
  code: ({ children, className }) => (
    <code
      className={
        className
          ? `${className} font-mono`
          : "rounded bg-[var(--color-bg-secondary)] px-1 py-0.5 font-mono text-[11px] text-[var(--color-text-secondary)]"
      }
    >
      {children}
    </code>
  ),
  table: ({ children }) => (
    <table className="my-2 w-full border-collapse text-left text-[11px] leading-5">
      {children}
    </table>
  ),
  th: ({ children }) => (
    <th className="border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2 py-1 font-semibold">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-[var(--color-border)] px-2 py-1 align-top">
      {children}
    </td>
  ),
  hr: () => <hr className="my-3 border-[var(--color-border)]" />,
};

const SUBAGENT_MARKDOWN_COMPONENTS: Components = {
  ...ASSISTANT_MARKDOWN_COMPONENTS,
  p: ({ children }) => (
    <p className="mb-1.5 whitespace-pre-wrap break-words last:mb-0">
      {children}
    </p>
  ),
  h1: ({ children }) => (
    <h1 className="mb-1.5 mt-2 text-xs font-semibold leading-5 first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mb-1 mt-2 text-xs font-semibold leading-5 first:mt-0">
      {children}
    </h2>
  ),
  h3: ({ children }) => (
    <h3 className="mb-1 mt-1.5 text-[11px] font-semibold leading-5 first:mt-0">
      {children}
    </h3>
  ),
  ul: ({ children }) => (
    <ul className="mb-1.5 list-disc space-y-0.5 pl-4 last:mb-0">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-1.5 list-decimal space-y-0.5 pl-4 last:mb-0">
      {children}
    </ol>
  ),
  pre: ({ children }) => (
    <pre className="my-1.5 max-w-full overflow-x-auto rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] leading-4 text-[var(--color-text-secondary)]">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <table className="my-1.5 w-full border-collapse text-left text-[10px] leading-4">
      {children}
    </table>
  ),
};

function MarkdownContent({
  children,
  compact = false,
}: {
  children: string;
  compact?: boolean;
}) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={
        compact ? SUBAGENT_MARKDOWN_COMPONENTS : ASSISTANT_MARKDOWN_COMPONENTS
      }
    >
      {children}
    </ReactMarkdown>
  );
}

function MessageParts({
  parts,
  richText = false,
}: {
  parts: CreatorContentPart[];
  richText?: boolean;
}) {
  return (
    <>
      {parts.map((part, index) => {
        if (part.type === "text") {
          return richText ? (
            <MarkdownContent key={index}>{part.text}</MarkdownContent>
          ) : (
            <span key={index} className="whitespace-pre-wrap">
              {part.text}
            </span>
          );
        }
        if (part.type === "image_url") {
          return (
            <img
              key={index}
              src={mediaUrl(
                part.image_url.url,
                part.attachment?.assetVersionRef,
              )}
              alt="消息图片"
              className="mt-1 max-h-40 rounded object-contain"
            />
          );
        }
        if (part.type === "video_url") {
          return (
            <video
              key={index}
              src={mediaUrl(
                part.video_url.url,
                part.attachment?.assetVersionRef,
              )}
              controls
              preload="metadata"
              className="mt-1 max-h-40 rounded"
            />
          );
        }
        return (
          <span
            key={index}
            className="mt-1 block rounded bg-[var(--color-bg-secondary)] px-2 py-1 text-[10px] text-[var(--color-text-secondary)]"
          >
            {part.type === "audio"
              ? "音频附件"
              : part.type === "document"
              ? "文档附件"
              : part.type}{" "}
            ·{" "}
            {String(part.attachment.name || part.attachment.filename || "附件")}
          </span>
        );
      })}
    </>
  );
}

function useLiveDisclosure(active: boolean) {
  const allowExpand = useAgentDockUiStore((state) => state.allowExpandDetails);
  const [expanded, setExpanded] = useState(false);
  const wasActive = useRef(active);
  useEffect(() => {
    if (!allowExpand) return;
    if (active && !wasActive.current) setExpanded(true);
    if (!active && wasActive.current) setExpanded(false);
    wasActive.current = active;
  }, [active, allowExpand]);
  return { expanded, setExpanded };
}

function ThinkingDisclosure({
  children,
  active,
}: {
  children: string;
  active: boolean;
}) {
  const allowExpand = useAgentDockUiStore((state) => state.allowExpandDetails);
  const isReplaying = useCreatorSessionStore((state) => state.isReplaying);
  const { expanded, setExpanded } = useLiveDisclosure(active);
  if (!children) return null;
  return (
    <div
      data-agent-thinking
      data-expanded={expanded ? "true" : "false"}
      className="border-l-2 border-[var(--color-border-strong)] pl-2 text-[10px]"
    >
      <div className="flex items-center gap-2">
        <span
          className={`flex items-center gap-1.5 ${
            active
              ? "text-[var(--color-text-secondary)]"
              : "text-[var(--color-text-tertiary)]"
          }`}
        >
          {isReplaying ? (
            <CircleCheck className="h-3 w-3 opacity-50" />
          ) : active ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <CircleCheck className="h-3 w-3" />
          )}
          {isReplaying ? "思考完成" : active ? "思考中" : "思考完成"}
        </span>
        {allowExpand && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
          >
            {expanded ? "收起" : "详情"}
          </button>
        )}
      </div>
      {expanded && (
        <pre
          data-agent-thinking-output
          tabIndex={0}
          className="mt-1 max-h-56 touch-pan-y overflow-y-auto overscroll-contain whitespace-pre-wrap break-words font-sans text-[10px] leading-4 text-[var(--color-text-secondary)] [scrollbar-gutter:stable]"
        >
          {children}
        </pre>
      )}
    </div>
  );
}

function extractErrorMessage(error: string): string {
  if (!error) return "";
  try {
    const parsed = JSON.parse(error);
    const type = parsed.error?.type || "";
    const message = parsed.error?.message || parsed.message || error;
    const errorMap: Record<string, string> = {
      AgentProjectBaseRequired: "项目状态已过期，请重试",
    };
    if (errorMap[type]) return errorMap[type];
    return message;
  } catch {
    return error;
  }
}

const ERROR_MESSAGE_MAP: Record<string, string> = {
  AgentProjectBaseRequired: "项目状态已过期，请重试",
  "R2V ArtifactSlot 归属冲突": "视频生成失败，请重试",
  "exceeded 16 model turns": "Agent 执行超时，请重试",
  "retryable: false": "执行失败，无法自动重试",
};

function simplifyErrorMessage(text: string): string {
  if (!text) return "";
  for (const [key, value] of Object.entries(ERROR_MESSAGE_MAP)) {
    if (text.includes(key)) return value;
  }
  const firstLine = text.split("\n")[0].trim();
  const firstSentence = firstLine.split("。")[0].split(". ")[0];
  return firstSentence || "执行失败，请重试";
}

function actionReason(envelope: CreatorActionEnvelope): string {
  const arguments_ = envelope.payload?.arguments;
  if (
    !arguments_ ||
    typeof arguments_ !== "object" ||
    Array.isArray(arguments_)
  )
    return "";
  const reason = (arguments_ as Record<string, unknown>).reason;
  return typeof reason === "string" ? reason.trim() : "";
}

function waitingActionTitle(reason: string): string {
  const subject = reason || "执行结果";
  const prefixed = /^(?:正在)?等待/.test(subject) ? subject : `等待${subject}`;
  return prefixed.endsWith("中") ? prefixed : `${prefixed}中`;
}

function actionTitle(envelope: CreatorActionEnvelope, active: boolean): string {
  if (envelope.action === "tool_call") {
    const label = creatorToolLabel(envelope.tool || "");
    return active ? `${label}中` : `${label}完成`;
  }
  if (envelope.action === "yield_until_runtime_event") {
    return waitingActionTitle(actionReason(envelope));
  }
  if (envelope.action === "complete_current_change")
    return active ? "完成检查中" : "完成检查已提交";
  if (envelope.action === "plan") return active ? "制定计划中" : "计划已生成";
  if (envelope.action === "final") return active ? "整理回复中" : "回复已生成";
  return active ? "处理中…" : "处理完成";
}

function ActionDisclosure({
  envelope,
  active,
}: {
  envelope: CreatorActionEnvelope;
  active: boolean;
}) {
  const allowExpand = useAgentDockUiStore((state) => state.allowExpandDetails);
  const isReplaying = useCreatorSessionStore((state) => state.isReplaying);
  const { expanded, setExpanded } = useLiveDisclosure(active);
  const payload = envelope.payload
    ? JSON.stringify(envelope.payload, null, 2)
    : envelope.rawPayload;
  const waiting = envelope.action === "yield_until_runtime_event" && !active;
  return (
    <div
      data-agent-action={envelope.action}
      data-streaming-action={active ? "true" : undefined}
      data-expanded={expanded ? "true" : "false"}
      className="border-l-2 border-[var(--color-accent)]/25 pl-2 text-[10px]"
    >
      <div className="flex items-center gap-2">
        <span
          className={`flex items-center gap-1.5 ${
            active || waiting
              ? "text-[var(--color-text-secondary)]"
              : "text-[var(--color-success)]"
          }`}
        >
          {isReplaying ? (
            <CircleCheck className="h-3 w-3 opacity-50" />
          ) : active ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : waiting ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : (
            <CircleCheck className="h-3 w-3" />
          )}
          {actionTitle(envelope, active)}
        </span>
        {allowExpand && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
          >
            {expanded ? "收起" : "详情"}
          </button>
        )}
      </div>
      {expanded && (
        <pre
          data-agent-action-output
          tabIndex={0}
          className="mt-1 max-h-56 touch-pan-y overflow-auto overscroll-contain whitespace-pre-wrap break-words rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] leading-4 text-[var(--color-text-secondary)] [scrollbar-gutter:stable]"
        >
          {payload}
        </pre>
      )}
    </div>
  );
}

function ConversationMessage({ item }: { item: CreatorMessage }) {
  const envelope =
    item.role === "assistant" ? creatorActionEnvelope(item) : null;
  const content =
    item.role === "assistant"
      ? actionAwareConversationContent(item, envelope)
      : conversationContent(item);
  const thinking =
    typeof item.metadata?.providerThinking === "string"
      ? item.metadata.providerThinking
      : "";
  const streaming = item.metadata?.streaming === true;
  if (content.length === 0 && !thinking && !envelope) return null;
  if (item.role === "user") {
    return (
      <div data-agent-message className="space-y-2">
        <div className="ml-auto w-fit max-w-[85%] rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-[11px] leading-[1.5] text-white">
          <MessageParts parts={content} />
        </div>
      </div>
    );
  }
  if (item.role === "tool") {
    return (
      <div
        data-agent-message
        className="rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-secondary)] px-2.5 py-1.5 text-[10px] text-[var(--color-text-secondary)]"
      >
        <MessageParts parts={content} />
      </div>
    );
  }
  if (
    typeof window !== "undefined" &&
    window.location.hostname === "localhost"
  ) {
    console.log("[ConversationMessage]", {
      streaming,
      thinking: !!thinking,
      thinkingLen: thinking.length,
      contentLen: content.length,
      completed: item.metadata?.completed,
    });
  }
  return (
    <div
      data-agent-message
      className="space-y-1.5 text-[11px] leading-5 text-[var(--color-text-secondary)]"
    >
      {streaming && !thinking && (
        <div className="flex items-center gap-1.5 text-[11px] text-[var(--color-text-secondary)]">
          <Loader2 className="h-3 w-3 animate-spin" />
          <span>处理中</span>
        </div>
      )}
      {thinking && (
        <ThinkingDisclosure active={streaming}>{thinking}</ThinkingDisclosure>
      )}
      {content.length > 0 && !streaming && (
        <MessageParts parts={content} richText />
      )}
      {envelope &&
        !(envelope.syntax === "native" && envelope.action === "tool_call") &&
        (streaming ||
          envelope.action === "yield_until_runtime_event" ||
          envelope.action === "complete_current_change") && (
          <ActionDisclosure envelope={envelope} active={streaming} />
        )}
    </div>
  );
}

interface ConversationTurn {
  user: CreatorMessage;
  responses: CreatorMessage[];
}

type SpecialistOutcome = "SUCCESS" | "BLOCKED" | "FAILED";

function roleDisplayName(
  activity: SubagentActivity | undefined,
  args: Record<string, unknown> | undefined,
): string {
  const raw =
    activity?.role || (typeof args?.role === "string" ? args.role : "");
  if (raw) {
    const label = creatorRoleLabel(raw);
    if (label !== "专业制作") return label;
  }
  const displayName =
    activity?.roleDisplayName ||
    (typeof args?.roleDisplayName === "string" ? args.roleDisplayName : "");
  return displayName || "专业制作";
}

function delegationText(
  activity: SubagentActivity | undefined,
  args: Record<string, unknown> | undefined,
): string {
  if (activity?.delegationText) return activity.delegationText;
  for (const key of ["task", "delegationText", "instruction"]) {
    const value = args?.[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function delegationTargets(
  activity: SubagentActivity | undefined,
  args: Record<string, unknown> | undefined,
): string[] {
  if (activity?.targetRefs.length) return activity.targetRefs;
  for (const key of ["target_refs", "targetRefs"]) {
    const value = args?.[key];
    if (Array.isArray(value))
      return value.filter(
        (item): item is string => typeof item === "string" && Boolean(item),
      );
  }
  return [];
}

function subagentMessageText(item: SubagentStreamMessage): string {
  if (item.completedText !== undefined) return item.completedText;
  return Object.entries(item.deltas)
    .sort(([left], [right]) => Number(left) - Number(right))
    .map(([, delta]) => delta)
    .join("");
}

function orderedDeltas(deltas: Record<number, string>): string {
  return Object.entries(deltas)
    .sort(([left], [right]) => Number(left) - Number(right))
    .map(([, delta]) => delta)
    .join("");
}

function subagentThinkingText(item: SubagentStreamMessage): string {
  return item.completedThinking ?? orderedDeltas(item.thinkingDeltas);
}

const SPECIALIST_OUTCOME_META: Record<
  SpecialistOutcome,
  { label: string; tone: string }
> = {
  SUCCESS: {
    label: "已完成",
    tone: "bg-[var(--color-success-soft)] text-[var(--color-success)]",
  },
  BLOCKED: {
    label: "受阻",
    tone: "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
  },
  FAILED: {
    label: "失败",
    tone: "bg-[var(--color-danger-soft)] text-[var(--color-danger)]",
  },
};

const SUBAGENT_TERMINAL_META: Record<
  NonNullable<SubagentActivity["terminalKind"]>,
  { label: string; tone: string }
> = {
  SUCCESS: SPECIALIST_OUTCOME_META.SUCCESS,
  BLOCKED: SPECIALIST_OUTCOME_META.BLOCKED,
  FAILED: SPECIALIST_OUTCOME_META.FAILED,
  STALE: {
    label: "已失效",
    tone: "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
  },
  CANCELLED: {
    label: "已取消",
    tone: "bg-[var(--color-bg-secondary)] text-[var(--color-text-tertiary)]",
  },
};

const SUBAGENT_RUNNING_META = {
  label: "运行中",
  tone: "bg-[var(--color-warning-soft)] text-[var(--color-warning)]",
};

function SubagentMessageBubble({
  item,
  materializedTool,
}: {
  item: SubagentStreamMessage;
  materializedTool: boolean;
}) {
  const body = subagentMessageText(item);
  const thinking = subagentThinkingText(item);
  const envelope = actionEnvelopeFromStreamText(body);
  const visibleBody = envelope?.narration ?? body;
  if (
    typeof window !== "undefined" &&
    window.location.hostname === "localhost"
  ) {
    console.log("[SubagentMessageBubble]", {
      completed: item.completed,
      thinking: !!thinking,
      thinkingLen: thinking.length,
      bodyLen: body.length,
      visibleBodyLen: visibleBody.length,
      messageId: item.messageId,
    });
  }
  if (!body && !thinking && item.completed) return null;
  return (
    <div
      data-subagent-message={item.messageId}
      className="text-[11px] leading-5 text-[var(--color-text-secondary)]"
    >
      {!item.completed && (
        <div className="mb-1 flex items-center gap-1.5">
          <span className="flex items-center gap-1 text-[9px] text-[var(--color-text-tertiary)]">
            <span className="h-1 w-1 animate-pulse rounded-full bg-[var(--color-warning)]" />
            实时输出中
          </span>
        </div>
      )}
      {thinking && (
        <ThinkingDisclosure active={!item.completed}>
          {thinking}
        </ThinkingDisclosure>
      )}
      {visibleBody && item.completed && (
        <pre className="mt-1 whitespace-pre-wrap break-words font-sans text-[11px] leading-5 text-[var(--color-text-secondary)]">
          {visibleBody}
        </pre>
      )}
      {envelope && !materializedTool && (
        <ActionDisclosure envelope={envelope} active={!item.completed} />
      )}
    </div>
  );
}

function NestedSubagentToolCard({ item }: { item: SubagentStreamTool }) {
  const allowExpand = useAgentDockUiStore((state) => state.allowExpandDetails);
  const isReplaying = useCreatorSessionStore((state) => state.isReplaying);
  const session = useCreatorSessionStore((state) => state.session);
  const isProjectDone =
    session?.status === "IDLE" ||
    session?.status === "CANCELLED" ||
    session?.status === "ERROR";
  const isProjectFailed =
    session?.status === "CANCELLED" || session?.status === "ERROR";
  const resolvedStatus =
    isProjectDone && item.status === "started"
      ? isProjectFailed
        ? "failed"
        : "succeeded"
      : item.status;
  const active = resolvedStatus === "started";
  const { expanded, setExpanded } = useLiveDisclosure(active);
  const rawArguments = Object.entries(item.argumentDeltas ?? {})
    .sort(([left], [right]) => Number(left) - Number(right))
    .map(([, value]) => value)
    .join("");
  const renderedArguments = item.arguments
    ? JSON.stringify(item.arguments, null, 2)
    : rawArguments;
  const hasArgs = Boolean(renderedArguments);
  const hasResult = item.result !== undefined && item.result !== null;
  const hasOutputEvents = item.outputEvents.length > 0;
  const hasDetails = hasArgs || hasResult || hasOutputEvents;
  const tone =
    resolvedStatus === "succeeded"
      ? "text-[var(--color-success)]"
      : resolvedStatus === "failed"
      ? "text-[var(--color-danger)]"
      : "text-[var(--color-text-tertiary)]";
  const displayLabel = creatorToolLabel(item.tool);
  return (
    <div
      data-subagent-tool={item.toolCallId}
      data-expanded={expanded ? "true" : "false"}
      className="border-l-2 border-[var(--color-accent)]/25 pl-2 text-[10px]"
    >
      <div className="flex items-center gap-2">
        <span className={`flex items-center gap-1.5 ${tone}`}>
          {isReplaying ? (
            <CircleCheck className="h-3 w-3 opacity-50" />
          ) : resolvedStatus === "started" ? (
            <Loader2 className="h-3 w-3 animate-spin" />
          ) : resolvedStatus === "succeeded" ? (
            <CircleCheck className="h-3 w-3" />
          ) : (
            <XCircle className="h-3 w-3" />
          )}
          <span>
            {displayLabel}
            {isReplaying
              ? ""
              : active
              ? "中"
              : resolvedStatus === "succeeded"
              ? "完成"
              : "失败"}
          </span>
        </span>
        {hasDetails && allowExpand && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
          >
            {expanded ? "收起" : "详情"}
          </button>
        )}
      </div>
      {expanded && (
        <div className="mt-1 min-h-0 space-y-1">
          {hasArgs && (
            <pre
              data-subagent-tool-arguments
              tabIndex={0}
              className="max-h-52 touch-pan-y overflow-auto overscroll-contain whitespace-pre-wrap break-words rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] leading-4 text-[var(--color-text-secondary)] [scrollbar-gutter:stable]"
            >
              {renderedArguments}
            </pre>
          )}
          {hasOutputEvents && (
            <pre
              data-subagent-tool-stream
              tabIndex={0}
              className="max-h-52 touch-pan-y overflow-auto overscroll-contain whitespace-pre-wrap rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] leading-4 text-[var(--color-text-secondary)] [scrollbar-gutter:stable]"
            >
              {item.outputEvents
                .map((event) =>
                  JSON.stringify({ type: event.type, ...event.data }),
                )
                .join("\n")}
            </pre>
          )}
          {hasResult && (
            <pre
              tabIndex={0}
              className="max-h-52 touch-pan-y overflow-auto overscroll-contain rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] leading-4 text-[var(--color-text-secondary)] [scrollbar-gutter:stable]"
            >
              {JSON.stringify(item.result, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

function SubagentActivityBubble({ activity }: { activity: SubagentActivity }) {
  const tools = Object.values(activity.tools);
  const items = [
    ...Object.values(activity.messages).map((item) => ({
      kind: "message" as const,
      order: item.firstEventSeq,
      item,
    })),
    ...tools.map((item) => ({
      kind: "tool" as const,
      order: item.firstEventSeq,
      item,
    })),
  ].sort((left, right) => left.order - right.order);
  const terminal = activity.terminalKind
    ? SUBAGENT_TERMINAL_META[activity.terminalKind]
    : null;
  const activityStatus = terminal ?? SUBAGENT_RUNNING_META;
  return (
    <div
      data-subagent-activity={activity.parentActionId}
      className="rounded-lg border border-[var(--color-accent)]/30 bg-[var(--color-accent-soft)] px-2.5 py-2"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2 text-[10px]">
        <div className="flex min-w-0 items-center gap-1.5">
          <b className="truncate text-[var(--color-accent)]">
            {activity.role
              ? creatorRoleLabel(activity.role)
              : roleDisplayName(activity, undefined)}
          </b>
          <span
            className={`shrink-0 rounded px-1.5 py-0.5 text-[9px] font-semibold ${activityStatus.tone}`}
          >
            {activityStatus.label}
          </span>
        </div>
        {activity.runId && (
          <span className="shrink-0 font-mono text-[9px] text-[var(--color-text-tertiary)]">
            运行 #{activity.runId.slice(0, 8)}
          </span>
        )}
      </div>
      <div
        data-subagent-output
        tabIndex={0}
        className="max-h-[min(24rem,50vh)] min-h-0 touch-pan-y space-y-1.5 overflow-y-auto overscroll-contain pr-1 outline-none [scrollbar-gutter:stable]"
      >
        {items.length > 0 ? (
          items.map((entry) =>
            entry.kind === "message" ? (
              <SubagentMessageBubble
                key={`message:${entry.item.runId}:${entry.item.messageId}`}
                item={entry.item}
                materializedTool={Boolean(
                  actionEnvelopeFromStreamText(subagentMessageText(entry.item))
                    ?.tool &&
                    tools.some(
                      (tool) =>
                        tool.tool ===
                          actionEnvelopeFromStreamText(
                            subagentMessageText(entry.item),
                          )?.tool &&
                        tool.firstEventSeq >= entry.item.firstEventSeq,
                    ),
                )}
              />
            ) : (
              <NestedSubagentToolCard
                key={`tool:${entry.item.runId}:${entry.item.toolCallId}`}
                item={entry.item}
              />
            ),
          )
        ) : activity.summaryText ? (
          <div className="text-[11px] leading-5 text-[var(--color-text-secondary)]">
            <MarkdownContent compact>
              {simplifyErrorMessage(activity.summaryText)}
            </MarkdownContent>
          </div>
        ) : (
          <p
            className={`${
              activity.completed ? "" : "animate-pulse"
            } text-[10px] text-[var(--color-text-tertiary)]`}
          >
            {activity.completed ? "已完成" : "等待输出中"}
          </p>
        )}
      </div>
    </div>
  );
}

function ToolCallCard({ data }: { data: ToolCallPresentation }) {
  const allowExpand = useAgentDockUiStore((state) => state.allowExpandDetails);
  const isReplaying = useCreatorSessionStore((state) => state.isReplaying);
  const session = useCreatorSessionStore((state) => state.session);
  const isProjectDone =
    session?.status === "IDLE" ||
    session?.status === "CANCELLED" ||
    session?.status === "ERROR";
  const isProjectFailed =
    session?.status === "CANCELLED" || session?.status === "ERROR";
  const activity = useCreatorSessionStore(
    (state) => state.subagentActivities[data.actionId],
  );
  const status = String(data.status ?? "");
  const tool = String(data.tool ?? "");
  const args = data.arguments;
  const rawArgs = data.argumentsText;
  const result = data.result;
  const delegated = tool === "delegate_to_agent" || Boolean(activity);
  const task = delegated ? delegationText(activity, args) : "";
  const targets = delegated ? delegationTargets(activity, args) : [];
  const role = delegated ? roleDisplayName(activity, args) : "";
  const rawDelegateResult =
    delegated && result !== undefined && result !== null
      ? typeof result === "string"
        ? result
        : JSON.stringify(result, null, 2)
      : "";

  const fileTools = [
    "read_file",
    "write_file",
    "edit_file",
    "append_file",
    "read_project",
    "read_project_file",
    "jq_project",
    "grep_search",
    "glob_search",
    "ast_search",
  ];
  const isFileTool = fileTools.includes(tool);

  const hasArgs =
    !delegated &&
    !isFileTool &&
    Boolean((args && Object.keys(args).length > 0) || rawArgs);
  const hasResult =
    !delegated && !isFileTool && result !== undefined && result !== null;
  const hasDetails = delegated || hasArgs || hasResult;

  const effectiveStatus =
    delegated && activity
      ? activity.completed
        ? activity.terminalKind === "FAILED" ||
          activity.terminalKind === "BLOCKED"
          ? "failed"
          : activity.terminalKind === "CANCELLED" ||
            activity.terminalKind === "STALE"
          ? "cancelled"
          : "succeeded"
        : "started"
      : status;
  // When the project reached a terminal state, force "started" tools terminal too.
  const resolvedStatus =
    isProjectDone && effectiveStatus === "started"
      ? isProjectFailed
        ? "failed"
        : "succeeded"
      : effectiveStatus;
  const active = resolvedStatus === "started";
  const { expanded, setExpanded } = useLiveDisclosure(active);
  const tone =
    resolvedStatus === "succeeded"
      ? "text-[var(--color-success)]"
      : resolvedStatus === "failed"
      ? "text-[var(--color-danger)]"
      : resolvedStatus === "cancelled"
      ? "text-[var(--color-text-tertiary)]"
      : "text-[var(--color-text-secondary)]";

  let displayLabel: string;
  let subLabel: string | null = null;
  if (delegated) {
    const activeTool = activity
      ? Object.values(activity.tools).find((t) => t.status === "started")
      : null;
    if (activeTool) {
      subLabel = creatorToolLabel(activeTool.tool);
    }
    displayLabel = role || "专业制作";
  } else {
    displayLabel = creatorToolLabel(tool);
  }

  const estimatedDuration = active ? getEstimatedDuration(tool) : null;
  const rawError = delegated ? activity?.summaryText || "" : data.error || "";
  const errorMessage = simplifyErrorMessage(rawError);

  return (
    <div
      data-agent-tool={data.actionId}
      data-expanded={expanded ? "true" : "false"}
      className="text-[10px]"
    >
      <div className="flex items-center gap-2">
        <span className={`flex items-center gap-1.5 ${tone}`}>
          {isReplaying ? (
            <CircleCheck className="h-3.5 w-3.5 opacity-50" />
          ) : resolvedStatus === "started" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : resolvedStatus === "succeeded" ? (
            <CircleCheck className="h-3.5 w-3.5" />
          ) : resolvedStatus === "cancelled" ? (
            <XCircle className="h-3.5 w-3.5 opacity-50" />
          ) : (
            <XCircle className="h-3.5 w-3.5" />
          )}
          <span>
            {displayLabel}
            {isReplaying
              ? ""
              : active
              ? "中"
              : resolvedStatus === "succeeded"
              ? "完成"
              : resolvedStatus === "cancelled"
              ? "已中止"
              : "失败"}
          </span>
          {subLabel && active && (
            <span className="text-[10px] text-[var(--color-text-tertiary)]">
              · {subLabel}
            </span>
          )}
          {estimatedDuration && (
            <span className="text-[10px] text-[var(--color-text-tertiary)]">
              {estimatedDuration}
            </span>
          )}
        </span>
        {hasDetails && allowExpand && (
          <button
            onClick={() => setExpanded((e) => !e)}
            className="text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
          >
            {expanded ? "收起" : "详情"}
          </button>
        )}
      </div>
      {resolvedStatus === "failed" && errorMessage && (
        <div className="mt-1 rounded-md bg-[var(--color-danger-soft)] px-2 py-1.5 text-[10px] text-[var(--color-danger)]">
          {errorMessage}
        </div>
      )}
      {expanded && (
        <div className="mt-1 space-y-1">
          {delegated && (task || targets.length > 0) && (
            <div
              data-subagent-input
              className="max-h-32 overflow-y-auto rounded-md bg-[var(--color-bg-secondary)] px-2 py-1.5 text-[10px] leading-4 text-[var(--color-text-secondary)]"
            >
              {task && (
                <p className="whitespace-pre-wrap break-words">{task}</p>
              )}
              {targets.length > 0 && (
                <p className="mt-0.5 text-[10px] text-[var(--color-text-tertiary)]">
                  目标：
                  {targets.map((ref) => creatorTargetLabel(ref)).join("、")}
                </p>
              )}
            </div>
          )}
          {delegated && activity && (
            <SubagentActivityBubble activity={activity} />
          )}
          {delegated && !activity && rawDelegateResult && (
            <div className="text-[10px] leading-4 text-[var(--color-text-secondary)]">
              <pre className="whitespace-pre-wrap break-words font-sans">
                {rawDelegateResult}
              </pre>
            </div>
          )}
          {delegated && !args && rawArgs && (
            <pre className="overflow-x-auto rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] leading-4 text-[var(--color-text-secondary)]">
              {rawArgs}
            </pre>
          )}
          {hasArgs && (
            <pre className="overflow-x-auto rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] leading-4 text-[var(--color-text-secondary)]">
              {args ? JSON.stringify(args, null, 2) : rawArgs}
            </pre>
          )}
          {hasResult && (
            <pre className="max-h-56 touch-pan-y overflow-auto overscroll-contain rounded-md bg-[var(--color-bg-secondary)] p-2 text-[10px] leading-4 text-[var(--color-text-secondary)] [scrollbar-gutter:stable]">
              {JSON.stringify(result, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}

interface PlanPresentation {
  summary: string;
  steps: string[];
  scope?: unknown;
}

function withoutDuplicateStepNumber(step: string): string {
  return step.replace(/^\s*(?:\d+[.\u3001、):：）]|[\(（]\d+[\)）])\s*/u, "");
}

function planPresentation(message: CreatorMessage): PlanPresentation | null {
  const envelope = creatorActionEnvelope(message);
  if (envelope?.action !== "plan" || !envelope.payload) return null;
  const data = envelope.payload;
  return {
    summary: typeof data.summary === "string" ? data.summary : "",
    steps: Array.isArray(data.steps) ? data.steps.map(String) : [],
    scope: data.scope,
  };
}

function PlanCard({ data }: { data: PlanPresentation }) {
  return (
    <div className="rounded-lg border border-[var(--color-accent)]/30 bg-[var(--color-accent-soft)] p-3 text-[11px] leading-5 text-[var(--color-text-primary)]">
      <b className="block text-[var(--color-accent)]">
        执行计划：{data.summary}
      </b>
      {data.steps.length > 0 && (
        <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-[var(--color-text-secondary)]">
          {data.steps.map((step, index) => (
            <li key={index}>{withoutDuplicateStepNumber(step)}</li>
          ))}
        </ol>
      )}
      {Boolean(data.scope) && (
        <p className="mt-1 text-[var(--color-text-tertiary)]">
          范围：
          {(Array.isArray(data.scope) ? data.scope : [data.scope])
            .map((ref) => creatorTargetLabel(String(ref)))
            .join("、")}
        </p>
      )}
    </div>
  );
}

const REF_TYPE_LABELS: Record<RefSearchItem["type"], string> = {
  timeline: "主时间轴",
  element: "时间线内容",
  asset: "素材",
  artifact: "生成产物",
  visual: "视觉设定",
};

function refTypeLabel(type: RefSearchItem["type"]): string {
  return REF_TYPE_LABELS[type] ?? "";
}

function fallbackRefName(ref: string): string {
  const value = ref.split(/[:/]/).filter(Boolean).at(-1) || ref;
  return value.length > 20 ? `${value.slice(0, 20)}…` : value;
}

function eventSummary(data: Record<string, unknown>): string {
  for (const key of ["summary", "message", "text", "delta", "outcome"]) {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function projectRefItems(
  project: ProjectDocument | null,
  query: string,
  limit = 6,
): RefSearchItem[] {
  if (!project) return [];
  const timeline = selectPrimaryTimeline(project);
  const needle = query.trim().toLocaleLowerCase();
  const items: RefSearchItem[] = [];
  if (timeline) {
    items.push({
      ref: `timeline:${timeline.timeline_id}`,
      name: "主时间轴",
      type: "timeline",
      uiLocator: { page: "plan" },
    });
    Object.values(timeline.elements_by_id).forEach((element) =>
      items.push({
        ref: `element:${element.element_id}`,
        name: element.label || element.element_id,
        type: "element",
        uiLocator: { page: "element", elementId: element.element_id },
      }),
    );
  }
  // Visual settings (scenes/characters/props) join references as entities;
  // generated images they own no longer appear again as standalone artifacts,
  // avoiding duplicate entries like "scene" plus "scene visual image".
  Object.values(project.visual.entities.items).forEach((entity) =>
    items.push({
      ref: `visual-entity:${entity.entity_id}`,
      name: entity.name || entity.entity_id,
      type: "visual",
      thumbnailUrl: entity.selected_artifact_version_id
        ? getArtifactVersionMediaUrl(entity.selected_artifact_version_id)
        : undefined,
      uiLocator: { page: "assets", assetId: entity.entity_id },
    }),
  );
  Object.values(project.assets.source_versions_by_id).forEach((version) =>
    items.push({
      ref: `asset-version:${version.version_id}`,
      name: version.name,
      type: "asset",
      version: version.version_id,
      thumbnailUrl:
        version.media_kind === "image" || version.media_kind === "video"
          ? getAssetVersionMediaUrl(version.version_id)
          : undefined,
      uiLocator: { page: "assets", assetId: version.version_id },
    }),
  );
  Object.values(project.assets.artifact_versions_by_id)
    .filter((version) => {
      // Entity ownership uses multiple prefixes in historical data
      // (visual-entity: / asset:); after normalization, outputs owned by a
      // visual entity are not listed again.
      const entityId = (version.owner_ref ?? "").replace(
        /^(?:visual-entity|asset):/,
        "",
      );
      return !project.visual.entities.items[entityId];
    })
    .forEach((version) =>
      items.push({
        ref: `artifact-version:${version.version_id}`,
        name: version.name,
        type: "artifact",
        version: version.version_id,
        thumbnailUrl: getArtifactVersionMediaUrl(version.version_id),
        uiLocator: { page: "assets", assetId: version.version_id },
      }),
    );
  return items
    .filter(
      (item) =>
        !needle ||
        `${item.name} ${item.ref}`.toLocaleLowerCase().includes(needle),
    )
    .slice(0, limit);
}

function WorkspacePanel() {
  const session = useCreatorSessionStore((state) => state.session);
  const status = useCreatorSessionStore((state) => state.agentStatusBar);
  const events = useCreatorSessionStore((state) => state.events);
  const runs = useCreatorTaskViewStore((state) => state.runs);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const project = useProjectSnapshotStore((state) => state.project);
  const timeline = selectPrimaryTimeline(project);
  const sourceCount = project
    ? Object.keys(project.assets.source_versions_by_id).length
    : 0;
  const artifactCount = project
    ? Object.keys(project.assets.artifact_versions_by_id).length
    : 0;
  const materialCount = sourceCount + artifactCount;
  const elementCount = timeline
    ? Object.keys(timeline.elements_by_id).length
    : 0;
  const recentWrites = events
    .filter(
      (event) =>
        event.type.startsWith("workspace.") ||
        event.type.startsWith("review.") ||
        event.type.startsWith("task."),
    )
    .slice(-5)
    .reverse();

  return (
    <div className="space-y-2.5 text-[10px] leading-4">
      <div>
        <p className="font-semibold text-[var(--color-text-secondary)]">
          当前任务
        </p>
        <p className="text-[var(--color-text-tertiary)]">
          阶段{" "}
          <b className="text-[var(--color-text-primary)]">
            {status?.progress.label || "—"}
          </b>
          {" · "}状态{" "}
          <b className="text-[var(--color-text-primary)]">
            {creatorStatusLabel(session?.status)}
          </b>
        </p>
        {status?.progress.latestMilestone && (
          <p className="line-clamp-2 text-[var(--color-text-secondary)]">
            目标：{status.progress.latestMilestone}
          </p>
        )}
      </div>

      <div>
        <p className="font-semibold text-[var(--color-text-secondary)]">
          素材概况（{materialCount}）
        </p>
        <div className="mt-0.5 flex flex-wrap gap-1">
          {!project ? (
            <span className="text-[var(--color-text-tertiary)]">暂无素材</span>
          ) : (
            <>
              <span className="rounded bg-[var(--color-bg-secondary)] px-1.5 py-0.5 text-[10px] text-[var(--color-text-secondary)]">
                源素材: {sourceCount}
              </span>
              <span className="rounded bg-[var(--color-bg-secondary)] px-1.5 py-0.5 text-[10px] text-[var(--color-text-secondary)]">
                生成产物: {artifactCount}
              </span>
            </>
          )}
        </div>
      </div>

      <div>
        <p className="font-semibold text-[var(--color-text-secondary)]">
          主时间轴
        </p>
        <p className="text-[var(--color-text-tertiary)]">
          {elementCount} 项内容
        </p>
      </div>

      {(runs.length > 0 || tasks.length > 0) && (
        <div>
          <p className="font-semibold text-[var(--color-text-secondary)]">
            专业制作进度
          </p>
          <ul className="mt-0.5 space-y-0.5">
            {runs.slice(0, 4).map((run) => (
              <li
                key={run.id}
                className="flex items-center gap-1.5 text-[var(--color-text-tertiary)]"
              >
                <span className="min-w-0 flex-1 truncate text-[var(--color-text-secondary)]">
                  {run.displayName} ·{" "}
                  {run.targetRefs
                    .map((ref) => creatorTargetLabel(ref, project))
                    .join("、") || "当前项目"}
                </span>
                <span className="shrink-0 text-[9px]">
                  {creatorStatusLabel(run.status)}
                </span>
              </li>
            ))}
            {tasks
              .filter(
                (task) => task.status === "QUEUED" || task.status === "RUNNING",
              )
              .slice(0, 3)
              .map((task) => (
                <li
                  key={task.id}
                  className="truncate text-[var(--color-text-tertiary)]"
                >
                  {taskKindLabel(task.kind)} →{" "}
                  {creatorTargetLabel(task.targetRef, project)}
                </li>
              ))}
          </ul>
        </div>
      )}

      {recentWrites.length > 0 && (
        <div>
          <p className="font-semibold text-[var(--color-text-secondary)]">
            最近写入
          </p>
          <ul className="mt-0.5 space-y-0.5">
            {recentWrites.map((event) => (
              <li
                key={event.eventId}
                className="truncate text-[var(--color-text-tertiary)]"
              >
                <span className="text-[var(--color-text-secondary)]">
                  {creatorEventLabel(event.type)}
                </span>
                {eventSummary(event.data)
                  ? ` → ${eventSummary(event.data)}`
                  : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function AgentDock({ sidebar = false }: { sidebar?: boolean }) {
  const { id: projectId = "" } = useParams();
  const open = useAgentDockUiStore((state) => state.open);
  const tab = useAgentDockUiStore((state) => state.tab);
  const width = useAgentDockUiStore((state) => state.width);
  const height = useAgentDockUiStore((state) => state.height);
  const draft = useAgentDockUiStore((state) => state.draft);
  const selectionAttachment = useAgentDockUiStore((state) => state.selection);
  const setOpen = useAgentDockUiStore((state) => state.setOpen);
  const setTab = useAgentDockUiStore((state) => state.setTab);
  const setSize = useAgentDockUiStore((state) => state.setSize);
  const setDraft = useAgentDockUiStore((state) => state.setDraft);
  const setSelectionAttachment = useAgentDockUiStore(
    (state) => state.setSelection,
  );
  const setDecisionTrayCollapsed = useAgentDockUiStore(
    (state) => state.setDecisionTrayCollapsed,
  );

  const session = useCreatorSessionStore((state) => state.session);
  const agentStatusBar = useCreatorSessionStore(
    (state) => state.agentStatusBar,
  );
  const messages = useCreatorSessionStore((state) => state.messages);
  const streamingAssistantMessages = useCreatorSessionStore(
    (state) => state.streamingAssistantMessages,
  );
  const events = useCreatorSessionStore((state) => state.events);
  const queued = useCreatorSessionStore((state) => state.queuedUi);
  const hasMoreMessages = useCreatorSessionStore(
    (state) => state.hasMoreMessages,
  );
  const loadOlderMessages = useCreatorSessionStore(
    (state) => state.loadOlderMessages,
  );
  const sendMessage = useCreatorSessionStore((state) => state.sendMessage);
  const stopping = useCreatorSessionStore((state) => state.stopping);
  const isReplaying = useCreatorSessionStore((state) => state.isReplaying);
  const stopAllAgents = useCreatorSessionStore((state) => state.stopAllAgents);
  const subagentActivities = useCreatorSessionStore(
    (state) => state.subagentActivities,
  );

  const runs = useCreatorTaskViewStore((state) => state.runs);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const authorizations = useExecutionAuthorizationStore((state) => state.items);
  const fileReviews =
    useFileProjectReviewStore((state) =>
      state.projectId === projectId ? state.reviews : null,
    ) ?? [];
  const selectedRef = useCreatorInteractionStore((state) => state.selectedRef);
  const editingField = useCreatorInteractionStore(
    (state) => state.editingField,
  );
  const interactionPanel = useCreatorInteractionStore((state) => state.panel);
  const extraRefs = useCreatorInteractionStore((state) => state.extraRefs);

  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const timeline = selectPrimaryTimeline(project);

  const streaming = Boolean(
    session &&
      ["RUNNING", "RESUMING", "INTERRUPT_REQUESTED"].includes(session.status),
  );
  const stoppable =
    Object.values(subagentActivities).some((activity) => !activity.completed) ||
    runs.some((run) => ACTIVE_RUN_STATUSES.has(run.status)) ||
    Boolean(session && STOPPABLE_SESSION_STATUSES.includes(session.status));
  const showWorkspace = tab === "activity";

  const [removedContextRefs, setRemovedContextRefs] = useState<string[]>([]);
  const [canSend, setCanSend] = useState(false);
  const [inlineRefs, setInlineRefs] = useState<string[]>([]);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionOptions, setMentionOptions] = useState<RefSearchItem[]>([]);
  const [mentionIndex, setMentionIndex] = useState(0);
  const [showJump, setShowJump] = useState(false);
  const inputRef = useRef<MentionInputHandle>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickBottom = useRef(true);
  const previousPendingAuthorizationCount = useRef(0);
  const lastOpenedFileReviewToken = useRef<string | null>(null);
  const resizeRef = useRef<{
    startX: number;
    startY: number;
    startW: number;
    startH: number;
  } | null>(null);

  const orderedMessages = useMemo(() => {
    const nextMessageSeq = (messages.at(-1)?.messageSeq ?? 0) + 1;
    const streamingMessages: CreatorMessage[] = Object.values(
      streamingAssistantMessages,
    )
      .sort((left, right) => left.firstEventSeq - right.firstEventSeq)
      .map((item, index) => ({
        messageId: item.messageId,
        messageSeq: nextMessageSeq + index,
        role: "assistant",
        source: "creator_agent_stream",
        content: [
          {
            type: "text",
            text: Object.entries(item.deltas)
              .sort(([left], [right]) => Number(left) - Number(right))
              .map(([, delta]) => delta)
              .join(""),
          },
        ],
        metadata: {
          streaming: true,
          providerThinking: orderedDeltas(item.thinkingDeltas),
          ...(item.toolCall
            ? {
                toolCall: {
                  id: item.toolCall.id,
                  name: item.toolCall.name,
                  ...(item.toolCall.arguments
                    ? { arguments: item.toolCall.arguments }
                    : {
                        argumentsDelta: orderedDeltas(
                          item.toolCall.argumentDeltas,
                        ),
                      }),
                },
                actionId: item.toolCall.id,
              }
            : {}),
        },
        createdAt: item.createdAt,
      }));
    return [...messages, ...streamingMessages]
      .filter(shouldRenderConversationMessage)
      .sort((left, right) => left.messageSeq - right.messageSeq);
  }, [messages, streamingAssistantMessages]);
  const conversationFlow = useMemo(() => {
    const turns: ConversationTurn[] = [];
    const orphanMessages: CreatorMessage[] = [];
    let currentTurn: ConversationTurn | null = null;
    orderedMessages.forEach((item) => {
      if (item.role === "user") {
        currentTurn = { user: item, responses: [] };
        turns.push(currentTurn);
      } else if (currentTurn) {
        currentTurn.responses.push(item);
      } else {
        orphanMessages.push(item);
      }
    });
    return { turns, orphanMessages };
  }, [orderedMessages]);
  const toolCalls = useMemo(
    () => toolCallPresentations(messages, events),
    [events, messages],
  );
  const toolCallsByMessage = useMemo(() => {
    const byMessage = new Map<string, ToolCallPresentation[]>();
    toolCalls.forEach((call) => {
      if (!call.anchorMessageId) return;
      const values = byMessage.get(call.anchorMessageId) ?? [];
      values.push(call);
      byMessage.set(call.anchorMessageId, values);
    });
    return byMessage;
  }, [toolCalls]);
  const unanchoredToolCalls = useMemo(
    () => toolCalls.filter((call) => !call.anchorMessageId),
    [toolCalls],
  );

  // Live status row above the input: derived purely on the frontend, no data
  // structures are mutated.
  const liveStatus = useMemo(
    () =>
      deriveAgentLiveStatus({
        session,
        agentStatusBar,
        stopping,
        hasQueuedInput: queued.some((item) => item.state !== "failed"),
        isReplaying,
        subagentActivities,
        toolCalls,
        tasks,
        project,
      }),
    [
      session,
      agentStatusBar,
      stopping,
      queued,
      isReplaying,
      subagentActivities,
      toolCalls,
      tasks,
      project,
    ],
  );

  const contextChips = useMemo(() => {
    const chips: RefSearchItem[] = [];
    const add = (item: RefSearchItem | null) => {
      if (
        item &&
        !removedContextRefs.includes(item.ref) &&
        !chips.some((candidate) => candidate.ref === item.ref)
      )
        chips.push(item);
    };
    if (selectedRef) {
      let item: RefSearchItem | null = null;
      if (selectedRef.startsWith("element:")) {
        const elementId = selectedRef.slice("element:".length);
        const element = timeline?.elements_by_id[elementId];
        if (element)
          item = {
            ref: selectedRef,
            name: element.label || elementId,
            type: "element",
            uiLocator: { page: "element", elementId },
          };
      } else if (selectedRef.startsWith("timeline:")) {
        item = {
          ref: selectedRef,
          name: "主时间轴",
          type: "timeline",
          uiLocator: { page: "plan" },
        };
      } else if (selectedRef.startsWith("asset-version:")) {
        const versionId = selectedRef.slice("asset-version:".length);
        const source = project?.assets.source_versions_by_id[versionId];
        if (source)
          item = {
            ref: selectedRef,
            name: source.name,
            type: "asset",
            uiLocator: { page: "assets", assetId: versionId },
          };
      } else if (selectedRef.startsWith("artifact-version:")) {
        const versionId = selectedRef.slice("artifact-version:".length);
        const artifact = project?.assets.artifact_versions_by_id[versionId];
        if (artifact)
          item = {
            ref: selectedRef,
            name: artifact.name,
            type: "artifact",
            uiLocator: { page: "assets", assetId: versionId },
          };
      }
      add(
        item ?? {
          ref: selectedRef,
          name: fallbackRefName(selectedRef),
          type: selectedRef.startsWith("element:")
            ? "element"
            : selectedRef.startsWith("timeline:")
            ? "timeline"
            : "asset",
          uiLocator: {},
        },
      );
    }
    extraRefs.forEach(add);
    return chips;
  }, [extraRefs, project, removedContextRefs, selectedRef, timeline]);
  const visibleChips = useMemo(
    () => contextChips.filter((chip) => !inlineRefs.includes(chip.ref)),
    [contextChips, inlineRefs],
  );

  const pendingAuthorizationCount = authorizations.filter(
    (item) => item.status === "PENDING",
  ).length;
  const pendingFileReviewCount = fileReviews.reduce(
    (total, review) => total + reviewPendingUnits(review),
    0,
  );
  const backendBadgeCount =
    agentStatusBar?.badges
      .filter(
        (badge) =>
          badge.kind === "review" || badge.kind === "execution_authorization",
      )
      .reduce((total, badge) => total + (badge.count ?? 1), 0) ?? 0;
  const decisionCount = Math.max(
    pendingAuthorizationCount + pendingFileReviewCount,
    backendBadgeCount,
  );
  const hasUrgentDecision = pendingAuthorizationCount > 0;

  useEffect(() => {
    const previous = previousPendingAuthorizationCount.current;
    previousPendingAuthorizationCount.current = pendingAuthorizationCount;
    if (pendingAuthorizationCount > previous) {
      // A production authorization is a blocking user decision.  Pop the dock
      // open and force the inline decision tray to expand as soon as
      // polling/SSE observes it; do not wait for a route refresh.
      setOpen(true);
      setDecisionTrayCollapsed(false);
    }
  }, [pendingAuthorizationCount, setDecisionTrayCollapsed, setOpen]);

  useEffect(() => {
    if (fileReviews.length === 0 || pendingFileReviewCount === 0) return;
    const compositeToken = fileReviews.map((r) => r.decision_token).join("|");
    if (lastOpenedFileReviewToken.current === compositeToken) return;
    lastOpenedFileReviewToken.current = compositeToken;
    // New review content lands in the inline tray; surface the dock so the
    // pending badge and tray summary are visible without navigation.
    setOpen(true);
  }, [fileReviews, pendingFileReviewCount, setOpen]);

  useEffect(() => {
    const stored = loadDockSize();
    setSize(stored.width, stored.height);
  }, [setSize]);

  useEffect(() => {
    try {
      window.localStorage.setItem(
        DOCK_SIZE_STORAGE_KEY,
        JSON.stringify({ width, height }),
      );
    } catch {
      /* optional */
    }
  }, [height, width]);

  useEffect(() => {
    const onResize = () => {
      const clamped = clampDockSize({ width, height });
      setSize(clamped.width, clamped.height);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [height, setSize, width]);

  useEffect(() => {
    if (!open) return;
    stickBottom.current = true;
    setShowJump(false);
    const timer = window.setTimeout(() => {
      inputRef.current?.focus();
    }, 60);
    return () => window.clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape" && mentionQuery === null) setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [mentionQuery, open, setOpen]);

  useEffect(() => {
    if (open && scrollRef.current && stickBottom.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [open, orderedMessages, queued, toolCalls]);

  useEffect(() => {
    if (!open || !selectionAttachment) return;
    inputRef.current?.insertSelection(selectionAttachment);
    setSelectionAttachment(null);
    useCreatorInteractionStore.getState().setSelection(null);
    const content = inputRef.current?.getContent();
    setCanSend(Boolean(content?.text.trim()));
    const timer = window.setTimeout(() => inputRef.current?.focus(), 40);
    return () => window.clearTimeout(timer);
  }, [open, selectionAttachment, setSelectionAttachment]);

  useEffect(() => {
    if (!open || !draft || inputRef.current?.getContent().text) return;
    inputRef.current?.setText(draft);
    setCanSend(Boolean(draft.trim()));
  }, [draft, open]);

  useEffect(() => {
    if (mentionQuery === null || !projectId) {
      setMentionOptions([]);
      return;
    }
    let cancelled = false;
    const timer = window.setTimeout(() => {
      if (!cancelled)
        setMentionOptions(projectRefItems(project, mentionQuery, 6));
    }, 100);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [mentionQuery, project, projectId]);

  useEffect(() => {
    setMentionIndex(0);
  }, [mentionQuery]);

  const beginResize =
    (axis: "x" | "y" | "xy") => (event: ReactPointerEvent) => {
      event.preventDefault();
      resizeRef.current = {
        startX: event.clientX,
        startY: event.clientY,
        startW: width,
        startH: height,
      };
      const onMove = (moveEvent: PointerEvent) => {
        const start = resizeRef.current;
        if (!start) return;
        const next = clampDockSize({
          width:
            axis === "y"
              ? start.startW
              : start.startW + (start.startX - moveEvent.clientX),
          height:
            axis === "x"
              ? start.startH
              : start.startH + (start.startY - moveEvent.clientY),
        });
        setSize(next.width, next.height);
      };
      const onUp = () => {
        resizeRef.current = null;
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
      };
      window.addEventListener("pointermove", onMove);
      window.addEventListener("pointerup", onUp);
    };

  const panelStyle: CSSProperties = { width, height };

  const toggleWorkspace = () => {
    setTab(showWorkspace ? "conversation" : "activity");
  };

  const handleScroll = () => {
    const element = scrollRef.current;
    if (!element) return;
    const nearBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 60;
    stickBottom.current = nearBottom;
    setShowJump(!nearBottom);
  };
  const jumpToBottom = () => {
    if (scrollRef.current)
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    stickBottom.current = true;
    setShowJump(false);
  };

  const handleInputChange = (text: string) => {
    const content = inputRef.current?.getContent();
    setCanSend(Boolean(content?.text.trim()));
    setInlineRefs(content?.refs.map((item) => item.ref) ?? []);
    setDraft(text);
  };

  const pickMention = (item: RefSearchItem) => {
    inputRef.current?.insertMention({
      ref: item.ref,
      name: item.name,
      type: item.type,
      thumbnailUrl: item.thumbnailUrl,
    });
    setMentionQuery(null);
    setMentionOptions([]);
  };
  const navigateMention = (direction: 1 | -1) => {
    setMentionIndex((index) => {
      const count = mentionOptions.length;
      return count ? (index + direction + count) % count : 0;
    });
  };
  const confirmMention = () => {
    const item = mentionOptions[mentionIndex] ?? mentionOptions[0];
    if (item) pickMention(item);
  };

  const removeChip = (chip: RefSearchItem) => {
    if (extraRefs.some((item) => item.ref === chip.ref)) {
      useCreatorInteractionStore
        .getState()
        .setExtraRefs(extraRefs.filter((item) => item.ref !== chip.ref));
    } else {
      setRemovedContextRefs((refs) => [...new Set([...refs, chip.ref])]);
    }
  };
  const clearContext = () => {
    setRemovedContextRefs((refs) => [
      ...new Set([...refs, ...contextChips.map((chip) => chip.ref)]),
    ]);
    useCreatorInteractionStore.getState().setExtraRefs([]);
    useCreatorInteractionStore.getState().setSelection(null);
    setSelectionAttachment(null);
    inputRef.current?.clearMentions();
    handleInputChange(inputRef.current?.getContent().text ?? "");
  };

  const submit = async () => {
    const content = inputRef.current?.getContent() ?? {
      text: "",
      refs: [],
      selections: [],
    };
    const text = content.text.trim();
    if (!text) return;
    const allRefs = [
      ...new Set([
        ...contextChips.map((item) => item.ref),
        ...content.refs.map((item) => item.ref),
      ]),
    ];
    const submittedExtraRefs = extraRefs;
    try {
      const pending = sendMessage({
        message: text,
        context: {
          panel: interactionPanel,
          selected: selectedRef ? { ref: selectedRef } : undefined,
          editingField,
          selection: content.selections[0]
            ? {
                field: content.selections[0].field,
                path: content.selections[0].path,
                ref: content.selections[0].ref,
                label: content.selections[0].label,
                text: content.selections[0].text,
                start: content.selections[0].start,
                end: content.selections[0].end,
              }
            : undefined,
          selections: content.selections,
          extraRefs: allRefs,
        },
      });
      inputRef.current?.clear();
      setCanSend(false);
      setInlineRefs([]);
      setDraft("");
      setMentionQuery(null);
      useCreatorInteractionStore.getState().setExtraRefs([]);
      await pending;
    } catch (error) {
      if (!inputRef.current?.getContent().text.trim()) {
        inputRef.current?.setText(text);
        setCanSend(true);
        setDraft(text);
        useCreatorInteractionStore.getState().setExtraRefs(submittedExtraRefs);
      }
      message.error((error as Error).message);
    }
  };

  return (
    <>
      {!open && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          data-agent-dock-handle
          data-state={liveStatus.state}
          className={`fixed right-0 top-15 z-40 flex ${
            decisionCount > 0 ? "h-[96px]" : "h-[76px]"
          } w-7 flex-col items-center justify-center rounded-l-xl border border-r-0 border-[var(--color-border)] bg-[var(--color-bg-card)]/92 text-[var(--color-text-tertiary)] shadow-lg backdrop-blur-xl transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]`}
          aria-label="打开 Agent"
          title={
            decisionCount > 0
              ? "展开 Agent 面板，处理待决策项"
              : "展开 Agent 面板"
          }
        >
          <PanelRightOpen className="h-3.5 w-3.5 shrink-0" />
          {decisionCount > 0 && (
            <span
              className={`mt-1.5 text-[9px] font-semibold leading-none tracking-[3px] [writing-mode:vertical-rl] ${
                hasUrgentDecision
                  ? "text-[var(--color-warning)]"
                  : "text-[var(--color-text-secondary)]"
              }`}
            >
              待决策
            </span>
          )}
          {decisionCount > 0 && (
            <span
              className={`absolute -left-2 -top-2 flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-[10px] font-bold text-white ${
                hasUrgentDecision
                  ? "animate-pulse bg-[var(--color-warning)]"
                  : "bg-[var(--color-danger)]"
              }`}
            >
              {decisionCount}
            </span>
          )}
          {hasUrgentDecision && (
            <span
              data-agent-dock-handle-toast
              className="agent-dock-handle-toast pointer-events-none absolute right-full top-1/2 mr-3 -translate-y-1/2 whitespace-nowrap rounded-full bg-[var(--color-warning)] px-2.5 py-1 text-[10px] font-semibold text-white shadow-lg"
            >
              {pendingAuthorizationCount} 项生产确认待处理
              <span className="absolute left-full top-1/2 -translate-y-1/2 border-[5px] border-transparent border-l-[var(--color-warning)]" />
            </span>
          )}
        </button>
      )}

      {open && (
        <div
          data-agent-dock
          data-agent-dock-width={String(width)}
          data-agent-dock-height={String(height)}
          style={sidebar ? { width, flexShrink: 0 } : panelStyle}
          className={
            sidebar
              ? "relative flex h-full flex-col overflow-hidden border-l border-[var(--color-border)] bg-[var(--color-bg-card)]"
              : "agent-dock-enter fixed bottom-5 right-5 z-40 flex max-h-[calc(100vh-40px)] max-w-[calc(100vw-40px)] flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]/92 shadow-2xl backdrop-blur-xl"
          }
        >
          <>
            {!sidebar && (
              <div
                onPointerDown={beginResize("y")}
                className="absolute inset-x-4 top-0 z-20 h-1.5 cursor-ns-resize"
                title="拖拽调整高度"
              />
            )}
            <div
              onPointerDown={beginResize("x")}
              className={
                sidebar
                  ? "absolute inset-y-0 left-0 z-20 w-1 cursor-ew-resize hover:bg-[var(--color-accent)]/20"
                  : "absolute inset-y-4 left-0 z-20 w-1.5 cursor-ew-resize"
              }
              title="拖拽调整宽度"
            />
            {!sidebar && (
              <div
                onPointerDown={beginResize("xy")}
                className="group absolute left-0 top-0 z-20 h-4 w-4 cursor-nwse-resize"
                title="拖拽调整大小"
              >
                <span className="pointer-events-none absolute left-1 top-1 h-1.5 w-1.5 rounded-tl-sm border-l-2 border-t-2 border-[var(--color-border-strong)] transition-colors group-hover:border-[var(--color-accent)]" />
              </div>
            )}
          </>

          <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-[18px]">
            <div className="flex min-w-0 items-center gap-2">
              {/* Transparent brand glyph, swapped per theme. */}
              <img
                src={logoGlyphOrange}
                alt=""
                className="h-5 w-5 shrink-0 object-contain dark:hidden"
              />
              <img
                src={logoGlyphWhite}
                alt=""
                className="hidden h-5 w-5 shrink-0 object-contain dark:block"
              />
              <div className="min-w-0">
                <b className="block truncate text-sm font-medium text-[var(--color-text-primary)]">
                  创作助手
                </b>
                {contextChips.length > 0 && (
                  <span className="block truncate text-[10px] text-[var(--color-text-tertiary)]">
                    已关联 {contextChips.length} 项引用
                  </span>
                )}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              <Button
                type="text"
                size="small"
                icon={
                  <Info
                    className={`h-3.5 w-3.5 ${
                      showWorkspace ? "text-[var(--color-accent)]" : ""
                    }`}
                  />
                }
                onClick={toggleWorkspace}
                title="工作区事实"
                aria-label="工作区事实"
              />
              <Button
                type="text"
                size="small"
                icon={<PanelRightClose className="h-3.5 w-3.5" />}
                onClick={() => setOpen(false)}
                title="收起 Agent 面板"
                aria-label="收起 Agent 面板"
              />
            </div>
          </div>

          {showWorkspace && (
            <div className="max-h-56 overflow-y-auto border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]/40 px-4 py-3">
              <WorkspacePanel />
            </div>
          )}

          <>
            <div className="relative flex min-h-0 flex-1 flex-col">
              <div
                ref={scrollRef}
                onScroll={handleScroll}
                className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3"
                aria-live="polite"
              >
                {(runs.length > 0 || tasks.length > 0) && <AgentEventFeed />}
                {hasMoreMessages && (
                  <button
                    type="button"
                    onClick={() => void loadOlderMessages()}
                    className="w-full text-center text-[10px] text-[var(--color-text-tertiary)]"
                  >
                    加载更多消息
                  </button>
                )}
                {orderedMessages.length === 0 &&
                queued.length === 0 &&
                runs.length === 0 &&
                tasks.length === 0 &&
                toolCalls.length === 0 ? (
                  <p className="py-6 text-center text-[11px] leading-5 text-[var(--color-text-tertiary)]">
                    描述你的修改意图，Agent 会给出执行计划并调度生成工具。
                    <br />
                    当前选中的对象会自动带入上下文。
                  </p>
                ) : (
                  conversationFlow.orphanMessages.map((item) => (
                    <Fragment key={item.messageId}>
                      <ConversationMessage item={item} />
                      {planPresentation(item) && (
                        <PlanCard data={planPresentation(item)!} />
                      )}
                      {(toolCallsByMessage.get(item.messageId) ?? []).map(
                        (call) => (
                          <ToolCallCard key={call.actionId} data={call} />
                        ),
                      )}
                    </Fragment>
                  ))
                )}
                {conversationFlow.turns.map((turn, turnIndex) => {
                  const latest =
                    turnIndex === conversationFlow.turns.length - 1;
                  return (
                    <div
                      key={turn.user.messageId}
                      data-agent-turn
                      className="space-y-2"
                    >
                      <div
                        data-agent-message
                        className="ml-auto w-fit max-w-[85%] rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-[11px] leading-[1.5] text-white"
                      >
                        <MessageParts parts={conversationContent(turn.user)} />
                      </div>
                      <div data-agent-response-flow className="space-y-2">
                        {turn.responses.map((item) => (
                          <Fragment key={item.messageId}>
                            <ConversationMessage item={item} />
                            {planPresentation(item) && (
                              <PlanCard data={planPresentation(item)!} />
                            )}
                            {(toolCallsByMessage.get(item.messageId) ?? []).map(
                              (call) => (
                                <ToolCallCard key={call.actionId} data={call} />
                              ),
                            )}
                          </Fragment>
                        ))}
                        {latest &&
                          unanchoredToolCalls.map((call) => (
                            <ToolCallCard key={call.actionId} data={call} />
                          ))}
                      </div>
                    </div>
                  );
                })}
                {conversationFlow.turns.length === 0 &&
                  unanchoredToolCalls.map((call) => (
                    <ToolCallCard key={call.actionId} data={call} />
                  ))}
                {queued.map((item) => (
                  <div key={item.clientMessageId} className="space-y-2">
                    <div className="ml-auto w-fit max-w-[85%] rounded-lg bg-[var(--color-accent)] px-3 py-1.5 text-[11px] leading-[1.5] text-white">
                      {item.text}
                    </div>
                    {item.state === "failed" && (
                      <p className="text-right text-[10px] text-[var(--color-danger)]">
                        {simplifyErrorMessage(item.error || "")}
                      </p>
                    )}
                  </div>
                ))}
              </div>
              {showJump && (
                <button
                  type="button"
                  onClick={jumpToBottom}
                  className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1 text-[11px] text-[var(--color-text-secondary)] shadow-md transition-colors hover:text-[var(--color-accent)]"
                >
                  回到底部 ↓
                </button>
              )}
            </div>

            {/* Inline decision tray: pinned between the chat stream and the live
                status bar so reviews and production confirmations are handled in place. */}
            <DecisionTray projectId={projectId} />

            <div
              data-agent-composer
              className="relative border-t border-[var(--color-border)] p-3"
            >
              <div
                data-agent-live-status
                data-state={liveStatus.state}
                className="mb-2 flex items-center gap-2 text-[10px] leading-4"
              >
                <span
                  className="agent-live-dot"
                  data-state={liveStatus.state}
                />
                <span
                  className={`min-w-0 flex-1 truncate ${
                    liveStatus.state === "working"
                      ? "agent-live-shimmer font-medium"
                      : liveStatus.state === "stopping"
                      ? "font-medium text-[var(--color-danger)]"
                      : "text-[var(--color-text-tertiary)]"
                  }`}
                >
                  {liveStatus.label}
                </span>
                {liveStatus.progressPercent != null && (
                  <span
                    data-agent-live-progress
                    className="flex shrink-0 items-center gap-1.5"
                  >
                    <span className="h-1 w-16 overflow-hidden rounded-full bg-[var(--color-bg-secondary)]">
                      <span
                        className="block h-full rounded-full bg-[var(--color-accent)] transition-[width] duration-500"
                        style={{ width: `${liveStatus.progressPercent}%` }}
                      />
                    </span>
                    <span className="tabular-nums text-[10px] text-[var(--color-text-secondary)]">
                      {liveStatus.progressPercent}%
                    </span>
                  </span>
                )}
              </div>
              {visibleChips.length > 0 && (
                <div className="mb-2 flex flex-wrap items-center gap-1">
                  {visibleChips.map((chip) => {
                    const manual = extraRefs.some(
                      (item) => item.ref === chip.ref,
                    );
                    const chipNode = (
                      <span
                        key={chip.ref}
                        className={`flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] ${
                          manual
                            ? "border border-[var(--color-accent)]/40 bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                            : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]"
                        }`}
                        title={
                          chip.thumbnailUrl
                            ? undefined
                            : manual
                            ? "手动引用"
                            : "自动带入的上下文"
                        }
                      >
                        @{chip.name}
                        <button
                          type="button"
                          onClick={() => removeChip(chip)}
                          className="text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)]"
                          aria-label={`移除 ${chip.name}`}
                        >
                          ×
                        </button>
                      </span>
                    );
                    if (!chip.thumbnailUrl) return chipNode;
                    return (
                      <Tooltip
                        key={chip.ref}
                        title={
                          <img
                            src={chip.thumbnailUrl}
                            alt={chip.name}
                            className="max-h-40 max-w-[220px] rounded object-contain"
                          />
                        }
                      >
                        {chipNode}
                      </Tooltip>
                    );
                  })}
                  <button
                    type="button"
                    onClick={clearContext}
                    className="flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[10px] text-[var(--color-text-tertiary)] transition-colors hover:text-[var(--color-danger)]"
                    title="清空全部引用、划选文本与输入框内的 @ 引用"
                  >
                    <Eraser className="h-3 w-3" />
                    清空
                  </button>
                </div>
              )}

              {mentionOptions.length > 0 && (
                <div
                  role="listbox"
                  aria-label="引用对象补全"
                  className="absolute bottom-full left-3 right-3 mb-1 overflow-hidden rounded-lg border border-[var(--color-border)] bg-[var(--color-bg-card)] shadow-lg"
                >
                  {mentionOptions.map((item, index) => (
                    <button
                      key={item.ref}
                      type="button"
                      role="option"
                      aria-selected={index === mentionIndex}
                      onMouseEnter={() => setMentionIndex(index)}
                      onMouseDown={(event) => event.preventDefault()}
                      onClick={() => pickMention(item)}
                      className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-[11px] ${
                        index === mentionIndex
                          ? "bg-[var(--color-accent-soft)]"
                          : "hover:bg-[var(--color-accent-soft)]"
                      }`}
                    >
                      {item.thumbnailUrl && (
                        <img
                          src={item.thumbnailUrl}
                          alt=""
                          className="h-6 w-6 shrink-0 rounded object-cover"
                          loading="lazy"
                        />
                      )}
                      {refTypeLabel(item.type) &&
                        refTypeLabel(item.type) !== item.name && (
                          <span className="rounded bg-[var(--color-bg-secondary)] px-1 text-[10px] text-[var(--color-text-tertiary)]">
                            {refTypeLabel(item.type)}
                          </span>
                        )}
                      <span className="truncate text-[var(--color-text-primary)]">
                        {item.name}
                      </span>
                    </button>
                  ))}
                </div>
              )}

              <OnboardingHint hintKey="mention" className="mb-2">
                输入 @
                可引用分镜、素材等对象作为上下文；当前选中的对象也会自动带入对话。
              </OnboardingHint>
              <div className="flex items-end gap-2">
                <MentionInput
                  ref={inputRef}
                  placeholder="输入修改意图，@ 可引用对象…"
                  onQueryChange={setMentionQuery}
                  onChange={handleInputChange}
                  onSubmit={() => void submit()}
                  mentionOpen={mentionOptions.length > 0}
                  onMentionNavigate={navigateMention}
                  onMentionConfirm={confirmMention}
                  onMentionClose={() => setMentionQuery(null)}
                />
                {(stoppable || stopping) && !canSend ? (
                  <Button
                    type="primary"
                    danger
                    aria-label="停止所有 Agent"
                    icon={<Square className="h-3 w-3 fill-current" />}
                    disabled={stopping}
                    onClick={() =>
                      void stopAllAgents()
                        .then(() => message.success("已停止所有 Agent 活动"))
                        .catch((error) =>
                          message.error((error as Error).message),
                        )
                    }
                    className="agent-dock-stop-glow !flex !h-8 !w-8 !items-center !justify-center !p-0"
                    title={
                      session?.status === "INTERRUPT_REQUESTED"
                        ? "停止请求已发送，点击再次停止"
                        : "立即停止当前项目的主 Agent、子 Agent 与未完成任务"
                    }
                  />
                ) : (
                  <Button
                    type="primary"
                    aria-label="发送"
                    icon={<ArrowUpOutlined />}
                    disabled={!canSend}
                    onClick={() => void submit()}
                    className="!flex !h-8 !w-8 !items-center !justify-center !p-0"
                  />
                )}
              </div>
            </div>
          </>
        </div>
      )}
    </>
  );
}
