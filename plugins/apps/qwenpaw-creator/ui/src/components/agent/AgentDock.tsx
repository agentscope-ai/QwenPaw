import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type {
  CSSProperties,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from "react";
import { Button, Tooltip, message } from "antd";
import { ArrowUpOutlined, MenuFoldOutlined } from "@ant-design/icons";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  ChevronDown,
  Eraser,
  Info,
  Loader2,
  PanelLeftClose,
  PanelLeftOpen,
  PanelRightClose,
  PanelRightOpen,
  RotateCcw,
  Square,
  Undo2,
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
import { useCreatorEditBufferStore } from "@/store/creatorEditBufferStore";
import { useCreatorInteractionStore } from "@/store/creatorInteractionStore";
import {
  useCreatorSessionStore,
  type SubagentActivity,
  type SubagentStreamMessage,
  type SubagentStreamTool,
} from "@/store/creatorSessionStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useWorkGraphStore } from "@/store/workGraphStore";
import WorkGraphPanel from "@/components/agent/WorkGraphPanel";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useTimelineStore } from "@/store/timelineStore";
import { selectPrimaryTimeline } from "@/selectors/timelineElementSelectors";
import SourceCacheGate from "@/components/creator/SourceCacheGate";
import { useSourceCache } from "@/lib/sourceCache";
import {
  creatorRoleLabel,
  creatorStatusLabel,
  creatorTargetLabel,
  creatorReferenceLabel,
  creatorToolLabel,
  taskKindLabel,
} from "@/lib/creatorPresentation";
import {
  publicAssistantText,
  actionAwareConversationContent,
  conversationContent,
  creatorActionEnvelope,
  deduplicateReviewFeedbackMessages,
  isReviewFeedbackMessage,
  shouldRenderConversationMessage,
  toolCallPresentations,
  type CreatorActionEnvelope,
  type ToolCallPresentation,
} from "@/lib/creatorMessagePresentation";
import {
  deriveAgentLiveStatus,
  toolActivityPhase,
} from "@/lib/agentLiveStatus";
import AgentProgressOverview from "./AgentProgressOverview";
import AgentWaitHint from "./AgentWaitHint";
import AgentActivityIndicator from "./AgentActivityIndicator";
import DecisionTray from "./DecisionTray";
import MentionInput, { type MentionInputHandle } from "./MentionInput";
import { reviewPendingUnits } from "./FileProjectReviewPanel";
import OnboardingHint from "@/components/onboarding/OnboardingHint";
import { useTranslation } from "react-i18next";
import i18n from "@/i18n";

interface DockSize {
  width: number;
  height: number;
}

const DOCK_MIN_WIDTH = 240;
const DOCK_MIN_HEIGHT = 420;
const DOCK_DEFAULT_SIZE: DockSize = { width: 340, height: 620 };
const DOCK_SIZE_STORAGE_KEY = "agentDock.size.v1";
// The workspace keeps at least this many pixels no matter how wide the dock
// is dragged; below that width its container queries switch to the drawer
// layout, so the pages stay usable instead of being squeezed out.
const WORKSPACE_MIN_WIDTH = 360;

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

function dockMaxSize(sidebar = false): DockSize {
  if (typeof window === "undefined") return { width: 960, height: 1200 };
  return {
    width: Math.max(
      DOCK_MIN_WIDTH,
      Math.min(
        window.innerWidth - WORKSPACE_MIN_WIDTH,
        sidebar ? Math.min(560, window.innerWidth * 0.38) : Infinity,
      ),
    ),
    height: Math.max(DOCK_MIN_HEIGHT, window.innerHeight - 40),
  };
}

function clampDockSize(size: DockSize, sidebar = false): DockSize {
  const maximum = dockMaxSize(sidebar);
  return {
    width: Math.min(Math.max(size.width, DOCK_MIN_WIDTH), maximum.width),
    height: Math.min(Math.max(size.height, DOCK_MIN_HEIGHT), maximum.height),
  };
}

function loadDockSize(sidebar = false): DockSize {
  if (typeof window === "undefined") return DOCK_DEFAULT_SIZE;
  try {
    const raw = window.localStorage.getItem(DOCK_SIZE_STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<DockSize>;
      if (
        typeof parsed.width === "number" &&
        typeof parsed.height === "number"
      ) {
        return clampDockSize(
          { width: parsed.width, height: parsed.height },
          sidebar,
        );
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
    <pre className="my-1.5 max-w-full overflow-x-auto rounded-md bg-[var(--color-bg-secondary)] p-2 text-[11px] leading-4 text-[var(--color-text-secondary)]">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <table className="my-1.5 w-full border-collapse text-left text-[11px] leading-4">
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
  const { t } = useTranslation();
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
              alt={t("agent.messageImage")}
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
            className="mt-1 block rounded bg-[var(--color-bg-secondary)] px-2 py-1 text-[11px] text-[var(--color-text-secondary)]"
          >
            {part.type === "audio"
              ? t("agent.audioAttachment")
              : part.type === "document"
              ? t("agent.documentAttachment")
              : part.type}{" "}
            ·{" "}
            {String(
              part.attachment.name ||
                part.attachment.filename ||
                t("agent.attachment"),
            )}
          </span>
        );
      })}
    </>
  );
}

function ThinkingDisclosure({
  children,
  active,
}: {
  children: string;
  active: boolean;
}) {
  const { t } = useTranslation();
  if (!children || !active) return null;
  // Thinking is intentionally status-only, including when legacy detail settings are enabled.
  return (
    <div data-agent-thinking className="agent-activity-row">
      <AgentActivityIndicator phase="running" />
      <span>{t("agentActivity.thinking")}</span>
    </div>
  );
}

function simplifyErrorMessage(_text: string): string {
  // Provider/runtime errors may contain prompts, local paths and protocol data.
  return i18n.t("agentActivity.failureHint");
}

function ActionDisclosure({
  envelope,
  active,
}: {
  envelope: CreatorActionEnvelope;
  active: boolean;
}) {
  const { t } = useTranslation();
  const session = useCreatorSessionStore((state) => state.session);
  const waiting =
    envelope.action === "yield_until_runtime_event" &&
    session?.status === "WAITING_RUNTIME";
  if (!active && !waiting) return null;
  return (
    <div data-agent-action={envelope.action} className="agent-activity-row">
      <AgentActivityIndicator phase="waiting" />
      <span>
        {waiting ? t("agentActivity.background") : t("agentActivity.preparing")}
      </span>
    </div>
  );
}

function ConversationMessage({ item }: { item: CreatorMessage }) {
  const project = useProjectSnapshotStore((state) => state.project);
  const waitingForRuntime = useCreatorSessionStore(
    (state) => state.session?.status === "WAITING_RUNTIME",
  );
  if (isReviewFeedbackMessage(item)) return <ReviewFeedbackCard item={item} />;
  if (item.role === "tool") return null;
  const envelope =
    item.role === "assistant" ? creatorActionEnvelope(item) : null;
  const streaming = item.metadata?.streaming === true;
  const parts =
    item.role === "assistant"
      ? actionAwareConversationContent(item, envelope, project)
      : conversationContent(item, project);
  const content =
    item.role === "assistant"
      ? parts
          .map((part) =>
            part.type === "text"
              ? {
                  ...part,
                  text: publicAssistantText(part.text, { streaming, project }),
                }
              : part,
          )
          .filter((part) => part.type !== "text" || part.text)
      : parts;
  const thinking =
    typeof item.metadata?.providerThinking === "string"
      ? item.metadata.providerThinking
      : "";
  const showThinking = !content.length && streaming && Boolean(thinking);
  const showAction =
    !content.length &&
    !thinking &&
    envelope &&
    !(envelope.syntax === "native" && envelope.action === "tool_call") &&
    (streaming ||
      (envelope.action === "yield_until_runtime_event" && waitingForRuntime));
  // A persisted tool envelope or hidden thinking has no conversation body.
  // Do not leave an empty sibling between otherwise consecutive tool rows.
  if (!content.length && !showThinking && !showAction) return null;
  if (item.role === "user")
    return (
      <div data-agent-message className="agent-user-message">
        <MessageParts parts={content} />
      </div>
    );
  return (
    <div
      data-agent-message
      data-streaming={streaming && content.length > 0}
      className="agent-assistant-message"
    >
      {showThinking && (
        <ThinkingDisclosure active={streaming}>{thinking}</ThinkingDisclosure>
      )}
      {content.length > 0 && <MessageParts parts={content} richText />}
      {showAction && (
        <ActionDisclosure envelope={envelope} active={streaming} />
      )}
    </div>
  );
}

function recordValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function feedbackText(feedback: Record<string, unknown>): string {
  const unified = feedback.feedbackNote ?? feedback.feedback_note;
  if (typeof unified === "string" && unified.trim()) return unified.trim();
  return [
    feedback.problemNote ?? feedback.problem_note,
    feedback.regenerationInstruction ?? feedback.regeneration_instruction,
  ]
    .filter((value): value is string => typeof value === "string")
    .map((value) => value.trim())
    .filter(Boolean)
    .join("；");
}

function ReviewFeedbackCard({ item }: { item: CreatorMessage }) {
  const { t } = useTranslation();
  const feedback = recordValue(item.metadata.rejectionFeedback) ?? {};
  const regenerate = feedback.action === "UNDO_AND_REGENERATE";
  const note = feedbackText(feedback);
  const targets = Array.isArray(item.metadata.targets)
    ? item.metadata.targets
        .map(recordValue)
        .filter((target): target is Record<string, unknown> => target !== null)
    : [];
  const targetLabels = targets
    .map((target) =>
      creatorReferenceLabel({
        ref: String(target.target_ref ?? target.targetRef ?? ""),
        name: String(target.label ?? ""),
      }),
    )
    .filter((value): value is string => typeof value === "string" && !!value);

  return (
    <div
      data-agent-message
      data-agent-review-feedback
      data-review-action={regenerate ? "regenerate" : "undo"}
      className="rounded-xl border border-[var(--color-accent)]/25 bg-[var(--color-accent-soft)] px-3 py-2.5 text-[11px] text-[var(--color-text-secondary)]"
    >
      <div className="flex min-w-0 items-start gap-2.5">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-bg-card)] text-[var(--color-accent)]">
          {regenerate ? (
            <RotateCcw className="h-3.5 w-3.5" />
          ) : (
            <Undo2 className="h-3.5 w-3.5" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="font-medium leading-5 text-[var(--color-text-primary)]">
            {regenerate ? t("agent.undoneAndRedo") : t("agent.undone")}
          </div>
          <div className="leading-4 text-[var(--color-text-tertiary)]">
            {regenerate ? t("agent.undoAndRedoDesc") : t("agent.undoneDesc")}
          </div>
        </div>
      </div>
      {targetLabels.length > 0 && (
        <div className="mt-2 truncate text-[11px] text-[var(--color-text-tertiary)]">
          {t("agent.targets")}
          {targetLabels.join("、")}
        </div>
      )}
      {note && (
        <div className="mt-2 rounded-lg bg-[var(--color-bg-card)] px-2.5 py-2 leading-4 text-[var(--color-text-secondary)]">
          <span className="font-medium text-[var(--color-text-primary)]">
            {t("agent.feedback")}
          </span>
          {note}
        </div>
      )}
    </div>
  );
}

interface ConversationTurn {
  user: CreatorMessage;
  responses: CreatorMessage[];
}

function orderedDeltas(deltas: Record<number, string>): string {
  return Object.entries(deltas)
    .sort(([a], [b]) => Number(a) - Number(b))
    .map(([, value]) => value)
    .join("");
}
function subagentMessageText(item: SubagentStreamMessage): string {
  return item.completedText ?? orderedDeltas(item.deltas);
}

function SubagentMessageBubble({ item }: { item: SubagentStreamMessage }) {
  const project = useProjectSnapshotStore((state) => state.project);
  const text = publicAssistantText(subagentMessageText(item), {
    streaming: !item.completed,
    project,
  });
  if (!text) return null;
  return (
    <div
      data-subagent-message={item.messageId}
      data-streaming={!item.completed}
      className="agent-specialist-response"
    >
      <MarkdownContent compact>{text}</MarkdownContent>
    </div>
  );
}

function statusCopy(status: string): string {
  return i18n.t(
    `agentActivity.${
      (
        {
          started: "running",
          succeeded: "done",
          failed: "failed",
          cancelled: "cancelled",
          waiting_review: "waiting_review",
          unknown: "unknown",
        } as Record<string, string>
      )[status] || "waiting"
    }`,
  );
}

function NestedSubagentToolCard({
  item,
  completed,
  waiting,
}: {
  item: SubagentStreamTool;
  completed: boolean;
  waiting: boolean;
}) {
  const status =
    completed && item.status === "started" ? "unknown" : item.status;
  const preparing = status === "started" && item.executing !== true;
  return (
    <div
      data-subagent-tool={item.toolCallId}
      data-status={status}
      className="agent-activity-row"
    >
      <AgentActivityIndicator
        phase={
          waiting && status === "started"
            ? "waiting"
            : toolActivityPhase({ status, executing: item.executing })
        }
      />
      <span className="min-w-0 flex-1">
        {creatorToolLabel(item.tool, item.arguments)}
      </span>
      <span className="agent-activity-caption">
        {waiting && status === "started"
          ? i18n.t("agentActivity.waiting")
          : preparing
          ? i18n.t("agentActivity.preparing")
          : statusCopy(status)}
      </span>
    </div>
  );
}

function SubagentActivityBubble({ activity }: { activity: SubagentActivity }) {
  const items = [
    ...Object.values(activity.messages).map((item) => ({
      kind: "message" as const,
      order: item.firstEventSeq,
      item,
    })),
    ...Object.values(activity.tools).map((item) => ({
      kind: "tool" as const,
      order: item.firstEventSeq,
      item,
    })),
  ].sort((a, b) => a.order - b.order);
  return (
    <div
      data-subagent-activity={activity.parentActionId}
      data-subagent-output
      className="agent-specialist-history"
    >
      {items.map((entry) =>
        entry.kind === "message" ? (
          <SubagentMessageBubble
            key={`m:${entry.item.runId}:${entry.item.messageId}`}
            item={entry.item}
          />
        ) : (
          <NestedSubagentToolCard
            key={`t:${entry.item.runId}:${entry.item.toolCallId}`}
            item={entry.item}
            completed={activity.completed}
            waiting={
              activity.waitingReview ||
              [
                "QUEUED",
                "QUEUED_CAPACITY",
                "WAITING_RUNTIME",
                "WAITING_AUTHORIZATION",
              ].includes(activity.status ?? "")
            }
          />
        ),
      )}
    </div>
  );
}

function ToolCallCard({ data }: { data: ToolCallPresentation }) {
  const { t } = useTranslation();
  const session = useCreatorSessionStore((state) => state.session);
  const activity = useCreatorSessionStore(
    (state) => state.subagentActivities[data.actionId],
  );
  const project = useProjectSnapshotStore((state) => state.project);
  const [expanded, setExpanded] = useState(false);
  const delegated = data.tool === "delegate_to_agent" || Boolean(activity);
  const role = creatorRoleLabel(
    activity?.role || String(data.arguments?.role || ""),
  );
  const targets = activity?.targetRefs || [];
  // Main-session IDLE never proves a detached task succeeded. Missing terminal
  // events remain unconfirmed, instead of manufacturing a green check.
  const status = activity
    ? activity.waitingReview
      ? "waiting_review"
      : !activity.completed
      ? "started"
      : activity.terminalKind === "SUCCESS" || activity.status === "SUCCEEDED"
      ? "succeeded"
      : ["FAILED", "BLOCKED", "STALE"].includes(
          activity.terminalKind ?? activity.status ?? "",
        )
      ? "failed"
      : "cancelled"
    : data.status === "started" &&
      session &&
      ["IDLE", "ERROR", "CANCELLED"].includes(session.status)
    ? "unknown"
    : data.status;
  const activeTool =
    activity &&
    !activity.waitingReview &&
    ![
      "QUEUED",
      "QUEUED_CAPACITY",
      "WAITING_RUNTIME",
      "WAITING_AUTHORIZATION",
    ].includes(activity.status ?? "") &&
    Object.values(activity.tools)
      .filter((tool) => tool.status === "started" && tool.executing === true)
      .sort((a, b) => b.firstEventSeq - a.firstEventSeq)[0];
  const phaseCopy =
    data.waitingAuthorization && status === "started"
      ? t("agentActivity.confirmation")
      : activity?.status === "WAITING_RUNTIME"
      ? t("agentActivity.background")
      : activity?.status === "WAITING_AUTHORIZATION"
      ? t("agentActivity.confirmation")
      : activity?.status === "QUEUED" || activity?.status === "QUEUED_CAPACITY"
      ? t("agentActivity.queued")
      : !activity && data.executing !== true
      ? t("agentActivity.preparing")
      : statusCopy(status);
  const latestMessage =
    activity &&
    Object.values(activity.messages).sort(
      (a, b) => b.firstEventSeq - a.firstEventSeq,
    )[0];
  const preview = latestMessage
    ? publicAssistantText(subagentMessageText(latestMessage), {
        streaming: !latestMessage.completed,
        project,
      })
    : "";
  return (
    <div
      data-agent-tool={data.actionId}
      data-expanded={expanded ? "true" : "false"}
      data-status={status}
      className={delegated ? "agent-specialist-card" : "agent-tool-row"}
    >
      <div className="agent-activity-row">
        <AgentActivityIndicator
          phase={
            data.productionOutcome ||
            (data.waitingAuthorization && status === "started")
              ? "attention"
              : toolActivityPhase(
                  { status, executing: data.executing },
                  activity,
                )
          }
        />
        <span className="min-w-0 flex-1 font-medium">
          {delegated ? role : creatorToolLabel(data.tool, data.arguments)}
        </span>
        <span className="agent-activity-caption">
          {data.productionOutcome
            ? t(`agentActivity.productionOutcome.${data.productionOutcome}`)
            : status === "cancelled" && data.superseded
            ? t("agentActivity.continued")
            : status === "started"
            ? phaseCopy
            : statusCopy(status)}
        </span>
        {activity && (
          <button
            type="button"
            className="agent-detail-toggle"
            aria-label={t(
              expanded
                ? "agentActivity.hideProgress"
                : "agentActivity.viewProgress",
            )}
            aria-expanded={expanded}
            onClick={() => setExpanded((value) => !value)}
          >
            <ChevronDown
              className={`h-3.5 w-3.5 transition-transform ${
                expanded ? "rotate-180" : ""
              }`}
            />
          </button>
        )}
      </div>
      {delegated && targets.length > 0 && (
        <div className="agent-targets">
          {targets.map((ref) => (
            <span key={ref}>{creatorTargetLabel(ref, project)}</span>
          ))}
        </div>
      )}
      {activeTool && status === "started" && (
        <p className="agent-specialist-subtitle">
          {creatorToolLabel(activeTool.tool, activeTool.arguments)}
        </p>
      )}
      {!expanded && preview && (
        <div data-subagent-public-preview className="agent-specialist-preview">
          <MarkdownContent compact>{preview}</MarkdownContent>
        </div>
      )}
      {status === "failed" && (
        <p className="agent-activity-notice">
          {t("agentActivity.failureHint")}
        </p>
      )}
      {status === "waiting_review" && (
        <p data-agent-waiting-review className="agent-activity-notice">
          {t("agentActivity.reviewHint")}
        </p>
      )}
      {expanded && activity && <SubagentActivityBubble activity={activity} />}
    </div>
  );
}

function refTypeLabel(type: RefSearchItem["type"]): string {
  const labels: Record<RefSearchItem["type"], string> = {
    timeline: i18n.t("agent.mainTimeline"),
    element: i18n.t("agentActivity.reference"),
    asset: i18n.t("common.content"),
    artifact: i18n.t("agent.artifactType"),
    visual: i18n.t("common.setting"),
  };
  return labels[type] ?? "";
}

function fallbackRefName(ref: string): string {
  return creatorTargetLabel(ref);
}

function projectRefItems(
  project: ProjectDocument | null,
  query: string,
  limit = 6,
): RefSearchItem[] {
  if (!project) return [];
  const timeline = selectPrimaryTimeline(
    project,
    useTimelineStore.getState().activeTimelineId,
  );
  const needle = query.trim().toLocaleLowerCase();
  const items: RefSearchItem[] = [];
  if (timeline) {
    items.push({
      ref: `timeline:${timeline.timeline_id}`,
      name: creatorTargetLabel(`timeline:${timeline.timeline_id}`, project),
      type: "timeline",
      uiLocator: { page: "plan" },
    });
    Object.values(timeline.elements_by_id).forEach((element) =>
      items.push({
        ref: `element:${element.element_id}`,
        name: creatorTargetLabel(`element:${element.element_id}`, project),
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
      name: creatorTargetLabel(`visual-entity:${entity.entity_id}`, project),
      type: "visual",
      thumbnailUrl:
        entity.variants.order.length === 1
          ? (() => {
              const variant = entity.variants.items[entity.variants.order[0]];
              return variant?.selected_artifact_version_id
                ? getArtifactVersionMediaUrl(
                    variant.selected_artifact_version_id,
                  )
                : undefined;
            })()
          : entity.variants.order.length === 0 &&
            entity.selected_artifact_version_id
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
  const { t } = useTranslation();
  const session = useCreatorSessionStore((state) => state.session);
  const runs = useCreatorTaskViewStore((state) => state.runs);
  const tasks = useCreatorTaskViewStore((state) => state.tasks);
  const workGraph = useWorkGraphStore((state) => state.graph);
  const project = useProjectSnapshotStore((state) => state.project);
  const activeTimelineId = useTimelineStore((s) => s.activeTimelineId);
  const timeline = selectPrimaryTimeline(project, activeTimelineId);
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

  return (
    <div className="space-y-2.5 text-[11px] leading-4">
      <div>
        <p className="font-semibold text-[var(--color-text-secondary)]">
          {t("agent.currentTask")}
        </p>
        <p className="text-[var(--color-text-tertiary)]">
          {t("agent.statusLabel")}{" "}
          <b className="text-[var(--color-text-primary)]">
            {creatorStatusLabel(session?.status)}
          </b>
        </p>
      </div>

      <div>
        <p className="font-semibold text-[var(--color-text-secondary)]">
          {t("agent.materialOverview", { count: materialCount })}
        </p>
        <div className="mt-0.5 flex flex-wrap gap-1">
          {!project ? (
            <span className="text-[var(--color-text-tertiary)]">
              {t("agent.noMaterials")}
            </span>
          ) : (
            <>
              <span className="rounded bg-[var(--color-bg-secondary)] px-1.5 py-0.5 text-[11px] text-[var(--color-text-secondary)]">
                {t("agent.sourceMaterials", { count: sourceCount })}
              </span>
              <span className="rounded bg-[var(--color-bg-secondary)] px-1.5 py-0.5 text-[11px] text-[var(--color-text-secondary)]">
                {t("agent.artifacts", { count: artifactCount })}
              </span>
            </>
          )}
        </div>
      </div>

      <div>
        <p className="font-semibold text-[var(--color-text-secondary)]">
          {t("agent.mainTimeline")}
        </p>
        <p className="text-[var(--color-text-tertiary)]">
          {t("agent.elementCount", { count: elementCount })}
        </p>
      </div>

      {project && workGraph && workGraph.nodes.length > 0 ? (
        // The derived work graph supersedes the flat specialist list: the
        // production DAG with per-node status, dependencies and actions.
        <WorkGraphPanel projectId={project.project_id} />
      ) : (
        (runs.length > 0 || tasks.length > 0) && (
          <div>
            <p className="font-semibold text-[var(--color-text-secondary)]">
              {t("agent.specialistProgress")}
            </p>
            <ul className="mt-0.5 space-y-0.5">
              {runs.slice(0, 4).map((run) => (
                <li
                  key={run.id}
                  className="flex items-center gap-1.5 text-[var(--color-text-tertiary)]"
                >
                  <span className="min-w-0 flex-1 truncate text-[var(--color-text-secondary)]">
                    {creatorRoleLabel(run.role)} ·{" "}
                    {run.targetRefs
                      .map((ref) => creatorTargetLabel(ref, project))
                      .join("、") || t("agent.currentProject")}
                  </span>
                  <span className="shrink-0 text-[11px]">
                    {creatorStatusLabel(run.status)}
                  </span>
                </li>
              ))}
              {tasks
                .filter(
                  (task) =>
                    task.status === "QUEUED" || task.status === "RUNNING",
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
        )
      )}
    </div>
  );
}

export default function AgentDock({
  sidebar = false,
  anchor = "right",
  headerSlot,
  feedSlot,
}: {
  sidebar?: boolean;
  /** Which screen edge the sidebar dock is attached to. */
  anchor?: "left" | "right";
  /** Replaces the brand/title block in the dock header. */
  headerSlot?: ReactNode;
  /** Rendered instead of the conversation feed (composer stays). */
  feedSlot?: ReactNode;
}) {
  const { t } = useTranslation();
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
  const loadingOlder = useCreatorSessionStore((state) => state.loadingOlder);
  const loadOlderMessages = useCreatorSessionStore(
    (state) => state.loadOlderMessages,
  );
  const sendMessage = useCreatorSessionStore((state) => state.sendMessage);
  const stopping = useCreatorSessionStore((state) => state.stopping);
  const isReplaying = useCreatorSessionStore((state) => state.isReplaying);
  const stopAllAgents = useCreatorSessionStore((state) => state.stopAllAgents);
  const connectionState = useCreatorSessionStore(
    (state) => state.connectionState,
  );
  const rateLimitRetry = useCreatorSessionStore(
    (state) => state.rateLimitRetry,
  );
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
  const pendingFileReviewCount = fileReviews.reduce(
    (total, review) =>
      total + (review.status === "PENDING" ? reviewPendingUnits(review) : 0),
    0,
  );
  const selectedRef = useCreatorInteractionStore((state) => state.selectedRef);
  const editingField = useCreatorInteractionStore(
    (state) => state.editingField,
  );
  const interactionPanel = useCreatorInteractionStore((state) => state.panel);
  const extraRefs = useCreatorInteractionStore((state) => state.extraRefs);
  const pendingEditCount = useCreatorEditBufferStore((state) =>
    state.projectId === projectId ? state.entries.length : 0,
  );

  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const builtinExample = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.builtinExample : false,
  );
  // Bundled examples ship trimmed clips only; follow-up agent questions need
  // the full originals cached locally, so gate sending until they land.
  const sourceCache = useSourceCache(projectId, builtinExample);
  const originalsGate = builtinExample && sourceCache.originalsMissing;
  const dockActiveTimelineId = useTimelineStore((s) => s.activeTimelineId);
  const timeline = selectPrimaryTimeline(project, dockActiveTimelineId);

  const streaming = Boolean(
    session &&
      ["RUNNING", "RESUMING", "INTERRUPT_REQUESTED"].includes(session.status),
  );
  const stoppable =
    Object.values(subagentActivities).some((activity) => !activity.completed) ||
    runs.some((run) => ACTIVE_RUN_STATUSES.has(run.status)) ||
    Boolean(session && STOPPABLE_SESSION_STATUSES.includes(session.status));
  const showWorkspace = tab === "activity";

  const currentProject = useRef(projectId);
  currentProject.current = projectId;
  const submissionVersion = useRef(0);
  const projectLifecycleVersion = useRef(0);
  const [removedContextRefs, setRemovedContextRefs] = useState<string[]>([]);
  const [canSend, setCanSend] = useState(false);
  const [rateLimitResuming, setRateLimitResuming] = useState(false);
  const [inlineRefs, setInlineRefs] = useState<string[]>([]);
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionOptions, setMentionOptions] = useState<RefSearchItem[]>([]);
  const [mentionIndex, setMentionIndex] = useState(0);
  useEffect(() => {
    setRemovedContextRefs([]);
    setRateLimitResuming(false);
    submissionVersion.current += 1;
    projectLifecycleVersion.current += 1;
  }, [projectId]);
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
                    : {}),
                },
                actionId: item.toolCall.id,
              }
            : {}),
        },
        createdAt: item.createdAt,
      }));
    return deduplicateReviewFeedbackMessages([
      ...messages,
      ...streamingMessages,
    ])
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
  // structures are mutated. `t` must stay in the deps: the labels come from
  // the global i18n singleton, so a runtime language switch has to recompute
  // them even when the agent state itself did not change.
  const liveStatus = useMemo(
    () =>
      deriveAgentLiveStatus({
        session,
        agentStatusBar,
        stopping,
        hasQueuedInput: queued.some((item) => item.state !== "failed"),
        messages,
        isReplaying,
        subagentActivities,
        toolCalls,
        tasks,
        project,
        rateLimitRetry,
        pendingReviewCount: pendingFileReviewCount,
      }),
    [
      session,
      agentStatusBar,
      stopping,
      queued,
      messages,
      isReplaying,
      subagentActivities,
      toolCalls,
      tasks,
      project,
      rateLimitRetry,
      pendingFileReviewCount,
      t,
    ],
  );

  // A throttled run stops with the full conversation still intact; the
  // continue control re-submits a resume request so the Agent picks the
  // same task back up on the previous messages.
  const resumeAfterRateLimit = async () => {
    if (rateLimitResuming) return;
    setRateLimitResuming(true);
    const resumeProject = projectId;
    const resumeVersion = projectLifecycleVersion.current;
    try {
      await sendMessage({ message: t("agent.rateLimitResumeMessage") });
    } catch (error) {
      if (
        currentProject.current === resumeProject &&
        projectLifecycleVersion.current === resumeVersion
      )
        message.error(t("agentActivity.failureHint"));
    } finally {
      if (
        currentProject.current === resumeProject &&
        projectLifecycleVersion.current === resumeVersion
      )
        setRateLimitResuming(false);
    }
  };

  const contextChips = useMemo(() => {
    const chips: RefSearchItem[] = [];
    const add = (item: RefSearchItem | null) => {
      if (
        item &&
        !removedContextRefs.includes(item.ref) &&
        !chips.some((candidate) => candidate.ref === item.ref)
      )
        chips.push({ ...item, name: creatorReferenceLabel(item, project) });
    };
    if (selectedRef) {
      let item: RefSearchItem | null = null;
      if (selectedRef.startsWith("element:")) {
        const elementId = selectedRef.slice("element:".length);
        const element = timeline?.elements_by_id[elementId];
        if (element)
          item = {
            ref: selectedRef,
            name: creatorTargetLabel(selectedRef, project),
            type: "element",
            uiLocator: { page: "element", elementId },
          };
      } else if (selectedRef.startsWith("timeline:")) {
        item = {
          ref: selectedRef,
          name: creatorTargetLabel(selectedRef, project),
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
    const stored = loadDockSize(sidebar);
    setSize(stored.width, stored.height);
  }, [setSize, sidebar]);

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
      const clamped = clampDockSize({ width, height }, sidebar);
      setSize(clamped.width, clamped.height);
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [height, setSize, width, sidebar]);

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
    if (open && feedSlot == null && scrollRef.current && stickBottom.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [open, feedSlot, orderedMessages, queued, toolCalls, subagentActivities]);

  // Apply a pending draft before inserting any selection pill: callers like
  // the blueprint "request changes" action set both, and the draft must land
  // while the input is still empty.
  useEffect(() => {
    if (!open || !draft || inputRef.current?.getContent().text) return;
    inputRef.current?.setText(draft);
    setCanSend(Boolean(draft.trim()));
  }, [draft, open]);

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
        const next = clampDockSize(
          {
            width:
              axis === "y"
                ? start.startW
                : start.startW +
                  (anchor === "left"
                    ? moveEvent.clientX - start.startX
                    : start.startX - moveEvent.clientX),
            height:
              axis === "x"
                ? start.startH
                : start.startH + (start.startY - moveEvent.clientY),
          },
          sidebar,
        );
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
  // Older-history loading: capture the scroll anchor before the request so
  // the prepended page cannot yank the viewport; the sentinel observer makes
  // scroll-to-top load history without hunting for the tiny button.
  const olderAnchor = useRef<{
    scrollHeight: number;
    scrollTop: number;
  } | null>(null);
  const topSentinelRef = useRef<HTMLDivElement>(null);
  const loadOlder = useCallback(() => {
    const element = scrollRef.current;
    const state = useCreatorSessionStore.getState();
    if (!element || state.loadingOlder || !state.hasMoreMessages) return;
    olderAnchor.current = {
      scrollHeight: element.scrollHeight,
      scrollTop: element.scrollTop,
    };
    void loadOlderMessages();
  }, [loadOlderMessages]);
  useLayoutEffect(() => {
    if (loadingOlder) return;
    const anchor = olderAnchor.current;
    const element = scrollRef.current;
    if (!anchor || !element) return;
    olderAnchor.current = null;
    const delta = element.scrollHeight - anchor.scrollHeight;
    if (delta > 0) element.scrollTop = anchor.scrollTop + delta;
  }, [loadingOlder, orderedMessages]);
  useEffect(() => {
    if (!open || !hasMoreMessages) return;
    if (typeof IntersectionObserver === "undefined") return;
    const sentinel = topSentinelRef.current;
    const root = scrollRef.current;
    if (!sentinel || !root) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) loadOlder();
      },
      { root, rootMargin: "160px 0px 0px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [open, hasMoreMessages, loadOlder]);
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
    setRemovedContextRefs((refs) => [...new Set([...refs, chip.ref])]);
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
    if (originalsGate) return;
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
    const version = ++submissionVersion.current;
    const submittedProject = projectId;
    const submittedExtraRefs = extraRefs;
    // Manual project.json edits accumulated since the previous message ride
    // along as context so the agent can re-evaluate dependent plan pieces.
    const userEdits = useCreatorEditBufferStore
      .getState()
      .consumeContext(projectId);
    try {
      const pending = sendMessage({
        message: text,
        context: {
          panel: interactionPanel,
          selected:
            selectedRef && allRefs.includes(selectedRef)
              ? { ref: selectedRef }
              : undefined,
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
          userEdits: userEdits ?? undefined,
        },
      });
      inputRef.current?.clear();
      setCanSend(false);
      setInlineRefs([]);
      setDraft("");
      setMentionQuery(null);
      useCreatorInteractionStore.getState().setExtraRefs([]);
      await pending;
      if (userEdits) {
        useCreatorEditBufferStore
          .getState()
          .markFlushed(projectId, userEdits.lastEntryAt);
      }
    } catch (error) {
      if (
        currentProject.current !== submittedProject ||
        submissionVersion.current !== version
      )
        return;
      if (!inputRef.current?.getContent().text.trim()) {
        inputRef.current?.setText(text);
        setCanSend(true);
        setDraft(text);
        useCreatorInteractionStore.getState().setExtraRefs(submittedExtraRefs);
      }
      message.error(t("agentActivity.failureHint"));
    }
  };

  return (
    <>
      {!open && (!sidebar || decisionCount > 0) && (
        <button
          type="button"
          onClick={() => setOpen(true)}
          data-agent-dock-handle
          data-state={liveStatus.state}
          className={`fixed top-20 z-40 flex ${
            anchor === "left"
              ? "left-0 rounded-r-xl border-l-0"
              : "right-0 rounded-l-xl border-r-0"
          } ${
            decisionCount > 0 ? "h-[96px]" : "h-[76px]"
          } w-7 flex-col items-center justify-center border border-[var(--color-border)] bg-[var(--color-bg-card)]/92 text-[var(--color-text-tertiary)] shadow-lg backdrop-blur-xl transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]`}
          aria-label={t("agent.assistant")}
          title={
            decisionCount > 0
              ? t("agent.expandForDecisions")
              : t("agent.expandPanel")
          }
        >
          {anchor === "left" ? (
            <PanelLeftOpen className="h-3.5 w-3.5 shrink-0" />
          ) : (
            <PanelRightOpen className="h-3.5 w-3.5 shrink-0" />
          )}
          {decisionCount > 0 && (
            <span
              className={`mt-1.5 text-[11px] font-semibold leading-none tracking-[3px] [writing-mode:vertical-rl] ${
                hasUrgentDecision
                  ? "text-[var(--color-warning)]"
                  : "text-[var(--color-text-secondary)]"
              }`}
            >
              {t("agent.decisionsPending")}
            </span>
          )}
          {decisionCount > 0 && (
            <span
              className={`absolute -top-2 flex h-[18px] min-w-[18px] items-center justify-center rounded-full px-1 text-[11px] font-bold text-white ${
                anchor === "left" ? "-right-2" : "-left-2"
              } ${
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
              className={`agent-dock-handle-toast pointer-events-none absolute top-1/2 -translate-y-1/2 whitespace-nowrap rounded-full bg-[var(--color-warning)] px-2.5 py-1 text-[11px] font-semibold text-white shadow-lg ${
                anchor === "left" ? "left-full ml-3" : "right-full mr-3"
              }`}
            >
              {t("agent.productionConfirmPending", {
                count: pendingAuthorizationCount,
              })}
              <span
                className={`absolute top-1/2 -translate-y-1/2 border-[5px] border-transparent ${
                  anchor === "left"
                    ? "right-full border-r-[var(--color-warning)]"
                    : "left-full border-l-[var(--color-warning)]"
                }`}
              />
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
              ? `relative flex min-h-0 flex-1 flex-col overflow-hidden ${
                  anchor === "left" ? "border-r" : "border-l"
                } border-[var(--color-border)] bg-[var(--color-bg-card)]`
              : "agent-dock-enter fixed bottom-5 right-5 z-40 flex max-h-[calc(100vh-40px)] max-w-[calc(100vw-40px)] flex-col overflow-hidden rounded-2xl border border-[var(--color-border)] bg-[var(--color-bg-card)]/92 shadow-2xl backdrop-blur-xl"
          }
        >
          <>
            {!sidebar && (
              <div
                onPointerDown={beginResize("y")}
                className="absolute inset-x-4 top-0 z-20 h-1.5 cursor-ns-resize"
                title={t("agent.dragHeight")}
              />
            )}
            <div
              onPointerDown={beginResize("x")}
              className={
                sidebar
                  ? `group absolute inset-y-0 z-20 flex w-1.5 cursor-ew-resize items-center justify-center hover:bg-[var(--color-accent)]/20 ${
                      anchor === "left" ? "right-0" : "left-0"
                    }`
                  : "absolute inset-y-4 left-0 z-20 w-1.5 cursor-ew-resize"
              }
              title={t("agent.dragWidth")}
            >
              {/* Always-visible grip so the resizable edge is discoverable. */}
              {sidebar && (
                <span className="pointer-events-none h-9 w-[3px] rounded-full bg-[var(--color-border-strong)] transition-colors group-hover:bg-[var(--color-accent)]" />
              )}
            </div>
            {!sidebar && (
              <div
                onPointerDown={beginResize("xy")}
                className="group absolute left-0 top-0 z-20 h-4 w-4 cursor-nwse-resize"
                title={t("agent.dragSize")}
              >
                <span className="pointer-events-none absolute left-1 top-1 h-1.5 w-1.5 rounded-tl-sm border-l-2 border-t-2 border-[var(--color-border-strong)] transition-colors group-hover:border-[var(--color-accent)]" />
              </div>
            )}
          </>

          <div className="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-[12px]">
            {headerSlot ?? (
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
                    {t("agent.assistant")}
                  </b>
                  {contextChips.length > 0 && (
                    <span className="block truncate text-[11px] text-[var(--color-text-tertiary)]">
                      {t("agent.relatedRefs", { count: contextChips.length })}
                    </span>
                  )}
                </div>
              </div>
            )}
            <div className="flex shrink-0 items-center gap-1.5">
              {!sidebar && (
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
                  title={t("agent.workspaceFacts")}
                  aria-label={t("agent.workspaceFacts")}
                />
              )}
              <Button
                type="text"
                size="small"
                icon={
                  sidebar ? (
                    <MenuFoldOutlined className="text-sm" />
                  ) : anchor === "left" ? (
                    <PanelLeftClose className="h-3.5 w-3.5" />
                  ) : (
                    <PanelRightClose className="h-3.5 w-3.5" />
                  )
                }
                onClick={() => setOpen(false)}
                title={t("agent.collapsePanel")}
                aria-label={t("agent.collapsePanel")}
              />
            </div>
          </div>

          <AgentProgressOverview projectId={projectId} />

          {showWorkspace && (
            <div className="max-h-56 overflow-y-auto border-b border-[var(--color-border)] bg-[var(--color-bg-secondary)]/40 px-4 py-3">
              <WorkspacePanel />
            </div>
          )}

          <>
            {feedSlot != null && (
              <div
                data-agent-feed-slot
                className="relative flex min-h-0 flex-1 flex-col overflow-hidden"
              >
                {feedSlot}
              </div>
            )}
            <div
              className={`relative min-h-0 flex-1 flex-col ${
                feedSlot != null ? "hidden" : "flex"
              }`}
            >
              <div
                ref={scrollRef}
                onScroll={handleScroll}
                className="agent-conversation-feed min-h-0 flex-1 space-y-5 overflow-y-auto px-4 py-4"
              >
                {hasMoreMessages && (
                  <div ref={topSentinelRef} data-agent-history-sentinel>
                    <button
                      type="button"
                      disabled={loadingOlder}
                      onClick={loadOlder}
                      className="flex w-full items-center justify-center gap-1 text-center text-[11px] text-[var(--color-text-tertiary)]"
                    >
                      {loadingOlder && (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      )}
                      {t("agent.loadMoreMessages")}
                    </button>
                  </div>
                )}
                {orderedMessages.length === 0 &&
                queued.length === 0 &&
                runs.length === 0 &&
                tasks.length === 0 &&
                toolCalls.length === 0 ? (
                  <p className="py-6 text-center text-[11px] leading-5 text-[var(--color-text-tertiary)]">
                    {t("agent.emptyHint")}
                    <br />
                    {t("agent.emptyHint2")}
                  </p>
                ) : (
                  <div data-agent-response-flow className="agent-response-flow">
                    {conversationFlow.orphanMessages.map((item) => (
                      <Fragment key={item.messageId}>
                        <ConversationMessage item={item} />
                        {(toolCallsByMessage.get(item.messageId) ?? []).map(
                          (call) => (
                            <ToolCallCard key={call.actionId} data={call} />
                          ),
                        )}
                      </Fragment>
                    ))}
                    {conversationFlow.turns.length === 0 &&
                      unanchoredToolCalls.map((call) => (
                        <ToolCallCard key={call.actionId} data={call} />
                      ))}
                  </div>
                )}
                {conversationFlow.turns.map((turn, turnIndex) => {
                  const latest =
                    turnIndex === conversationFlow.turns.length - 1;
                  return (
                    <div
                      key={turn.user.messageId}
                      data-agent-turn
                      className="space-y-4"
                    >
                      <ConversationMessage item={turn.user} />
                      <div
                        data-agent-response-flow
                        className="agent-response-flow"
                      >
                        {turn.responses.map((item) => (
                          <Fragment key={item.messageId}>
                            <ConversationMessage item={item} />
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
                {queued.map((item) => (
                  <div key={item.clientMessageId} className="space-y-2">
                    <div className="ml-auto w-fit agent-user-message">
                      {item.text}
                    </div>
                    {item.state === "failed" && (
                      <p className="text-right text-[11px] text-[var(--color-danger)]">
                        {t("agentActivity.sendFailed")}
                      </p>
                    )}
                  </div>
                ))}
                {session?.status === "ERROR" && session?.error?.message && (
                  <div className="mx-3 my-2 rounded-md bg-[var(--color-danger-soft)] px-3 py-2 text-[11px] leading-[1.5] text-[var(--color-danger)]">
                    {session.error.code === "MODEL_RATE_LIMITED" ? (
                      <div className="flex items-center justify-between gap-2">
                        <span>
                          {t("agent.rateLimitExhausted", {
                            retries: Number.isFinite(
                              Number(session.error.details?.retryCount),
                            )
                              ? Number(session.error.details?.retryCount)
                              : rateLimitRetry?.maxAttempts ?? 5,
                          })}
                        </span>
                        <Button
                          size="small"
                          type="primary"
                          danger
                          loading={rateLimitResuming}
                          onClick={() => void resumeAfterRateLimit()}
                        >
                          {t("agent.rateLimitContinue")}
                        </Button>
                      </div>
                    ) : (
                      t("agentActivity.failureHint")
                    )}
                  </div>
                )}
              </div>
              {showJump && (
                <button
                  type="button"
                  onClick={jumpToBottom}
                  className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-1 text-[11px] text-[var(--color-text-secondary)] shadow-md transition-colors hover:text-[var(--color-accent)]"
                >
                  {t("agent.scrollToBottom")}
                </button>
              )}
            </div>

            {/* Inline decision tray: pinned between the chat stream and the live
                status bar so reviews and production confirmations are handled in place. */}
            <DecisionTray projectId={projectId} />

            <div
              data-agent-composer
              className="relative shrink-0 border-t border-[var(--color-border)] bg-[var(--color-bg-primary)] p-3"
            >
              <div
                data-agent-live-status
                data-state={
                  connectionState === "reconnecting"
                    ? "reconnecting"
                    : liveStatus.state
                }
                className="mb-2 flex items-start gap-2 text-xs leading-5"
                role="status"
              >
                <AgentActivityIndicator
                  phase={
                    connectionState === "reconnecting"
                      ? "waiting"
                      : liveStatus.indicatorPhase
                  }
                />
                <span
                  className={`min-w-0 flex-1 break-words ${
                    liveStatus.state === "working"
                      ? "font-medium text-[var(--color-text-secondary)]"
                      : liveStatus.state === "stopping"
                      ? "font-medium text-[var(--color-danger)]"
                      : "text-[var(--color-text-tertiary)]"
                  }`}
                >
                  {connectionState === "reconnecting"
                    ? t("agentActivity.reconnecting")
                    : liveStatus.label}
                </span>
                {connectionState !== "reconnecting" &&
                  liveStatus.progressPercent != null && (
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
                      <span className="tabular-nums text-[11px] text-[var(--color-text-secondary)]">
                        {liveStatus.progressPercent}%
                      </span>
                    </span>
                  )}
              </div>
              <AgentWaitHint
                projectId={projectId}
                active={liveStatus.state === "working"}
                retrying={!isReplaying && !stopping && Boolean(rateLimitRetry)}
                retry={isReplaying || stopping ? null : rateLimitRetry}
                others={(isReplaying || stopping
                  ? []
                  : Object.values(subagentActivities)
                ).flatMap((activity) =>
                  !activity.completed && activity.modelRetry
                    ? [
                        {
                          ...activity.modelRetry,
                          label:
                            activity.roleDisplayName ||
                            creatorRoleLabel(activity.role),
                        },
                      ]
                    : [],
                )}
              />
              {pendingEditCount > 0 && (
                <div
                  data-agent-edit-buffer
                  title={t("timeline.editBufferTooltip")}
                  className="mb-2 flex items-center gap-1.5 rounded-md border border-dashed border-[var(--color-border)] bg-[var(--color-bg-secondary)]/60 px-2 py-1 text-[11px] text-[var(--color-text-secondary)]"
                >
                  <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--color-accent)]" />
                  {t("timeline.pendingEditCount", { count: pendingEditCount })}
                </div>
              )}
              {visibleChips.length > 0 && (
                <div
                  data-agent-reference-chips
                  className="mb-2 flex max-h-24 flex-wrap items-center gap-1 overflow-y-auto"
                >
                  {visibleChips.map((chip) => {
                    const manual = extraRefs.some(
                      (item) => item.ref === chip.ref,
                    );
                    const chipNode = (
                      <span
                        key={chip.ref}
                        className={`flex min-w-0 max-w-full items-center gap-1 rounded-md px-1.5 py-1 text-[11px] ${
                          manual
                            ? "border border-[var(--color-accent)]/40 bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                            : "bg-[var(--color-bg-secondary)] text-[var(--color-text-secondary)]"
                        }`}
                        title={
                          chip.thumbnailUrl
                            ? undefined
                            : manual
                            ? t("agent.manualRef")
                            : t("agent.autoContext")
                        }
                      >
                        {chip.thumbnailUrl && (
                          <img
                            src={chip.thumbnailUrl}
                            alt=""
                            className="h-5 w-5 shrink-0 rounded object-cover"
                          />
                        )}
                        <span className="min-w-0 truncate">{chip.name}</span>
                        <button
                          type="button"
                          onClick={() => removeChip(chip)}
                          className="text-[var(--color-text-tertiary)] hover:text-[var(--color-danger)]"
                          aria-label={t("agent.removeRef", { name: chip.name })}
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
                    className="flex items-center gap-0.5 rounded-md px-1.5 py-0.5 text-[11px] text-[var(--color-text-tertiary)] transition-colors hover:text-[var(--color-danger)]"
                    title={t("agent.clearAll")}
                  >
                    <Eraser className="h-3 w-3" />
                    {t("agent.clear")}
                  </button>
                </div>
              )}

              {mentionOptions.length > 0 && (
                <div
                  role="listbox"
                  aria-label={t("agent.inputPlaceholder")}
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
                          <span className="rounded bg-[var(--color-bg-secondary)] px-1 text-[11px] text-[var(--color-text-tertiary)]">
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
                {t("agent.mentionHint")}
              </OnboardingHint>
              {originalsGate && (
                <div className="mb-2">
                  <SourceCacheGate status={sourceCache} compact />
                </div>
              )}
              <div className="flex items-end gap-2">
                <MentionInput
                  ref={inputRef}
                  placeholder={t("agent.inputPlaceholder")}
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
                    aria-label={t("agent.stopAllAgents")}
                    icon={<Square className="h-3 w-3 fill-current" />}
                    disabled={stopping}
                    onClick={() => {
                      const stopProject = projectId;
                      const stopVersion = submissionVersion.current;
                      const isCurrent = () =>
                        currentProject.current === stopProject &&
                        submissionVersion.current === stopVersion;
                      void stopAllAgents()
                        .then(() => {
                          if (isCurrent())
                            message.success(t("agent.stopAllSuccess"));
                        })
                        .catch(() => {
                          if (isCurrent())
                            message.error(t("agentActivity.failureHint"));
                        });
                    }}
                    className="agent-dock-stop-glow !flex !h-8 !w-8 !items-center !justify-center !p-0"
                    title={
                      session?.status === "INTERRUPT_REQUESTED"
                        ? t("agent.stopRequested")
                        : t("agent.stopDescription")
                    }
                  />
                ) : (
                  <Button
                    type="primary"
                    aria-label={t("common.send")}
                    icon={<ArrowUpOutlined />}
                    disabled={!canSend || originalsGate}
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
