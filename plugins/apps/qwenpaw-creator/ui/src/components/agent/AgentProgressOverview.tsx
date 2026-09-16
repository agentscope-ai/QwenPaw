import { useEffect, useId, useMemo, useState } from "react";
import {
  ArrowUpRight,
  ChevronDown,
  Film,
  Layers3,
  ScanEye,
  AlertCircle,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { useWorkGraphStore } from "@/store/workGraphStore";
import { useCreatorTaskViewStore } from "@/store/creatorTaskViewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { navigateToLocator } from "@/routing/locators";
import {
  buildAgentProgressModel,
  type AgentProgressGroup,
  type AgentProgressItem,
  type AgentProgressPhase,
} from "@/lib/agentProgressModel";
import { reviewPendingUnits } from "./FileProjectReviewPanel";
import AgentActivityIndicator from "./AgentActivityIndicator";

type ProgressFilter = "all" | AgentProgressPhase;
const filters: ProgressFilter[] = [
  "all",
  "running",
  "attention",
  "preparing",
  "completed",
];

function OperationRow({
  item,
  groupLabel,
  projectId,
}: {
  item: AgentProgressItem;
  groupLabel: string;
  projectId: string;
}) {
  const { t } = useTranslation();
  const label = item.label.startsWith(`${groupLabel} · `)
    ? item.label.slice(groupLabel.length + 3)
    : item.label;
  const node = item.node;
  return (
    <li
      className="agent-overview-operation"
      data-phase={item.phase}
      data-node-id={node?.id}
    >
      <AgentActivityIndicator
        phase={item.phase === "preparing" ? "waiting" : item.phase}
      />
      <div className="agent-operation-copy">
        {item.locator ? (
          <button
            type="button"
            className="agent-operation-link"
            onClick={() => {
              navigateToLocator(projectId, item.locator!, {
                description: t("progressOverview.title"),
                ...(item.locator?.field ? { focusField: true } : {}),
              });
            }}
            title={t("progressOverview.viewObject", { name: label })}
          >
            {label}
            <ArrowUpRight aria-hidden />
          </button>
        ) : (
          <span className="agent-operation-label">{label}</span>
        )}
        <span className="agent-operation-status">
          {item.statusLabel}
          {item.progressPercent != null && item.progressPercent > 0
            ? ` · ${item.progressPercent}%`
            : ""}
        </span>
      </div>
    </li>
  );
}

function WorkGroupCard({
  group,
  filter,
  projectId,
}: {
  group: AgentProgressGroup;
  filter: ProgressFilter;
  projectId: string;
}) {
  const { t } = useTranslation();
  const matching = group.items.filter(
    (item) => filter === "all" || item.phase === filter,
  );
  if (!matching.length) return null;
  const phase = group.counts.running
    ? "running"
    : group.counts.attention
    ? "attention"
    : group.counts.preparing
    ? "preparing"
    : "completed";
  const Icon =
    group.kind === "timeline"
      ? Film
      : group.kind === "source"
      ? ScanEye
      : Layers3;
  return (
    <article className="agent-overview-group" data-phase={phase}>
      <div className="agent-work-group-heading">
        <span className="agent-work-group-icon" aria-hidden>
          <Icon />
        </span>
        {group.locator ? (
          <button
            className="agent-work-group-name"
            type="button"
            onClick={() => {
              navigateToLocator(projectId, group.locator!, {
                description: t("progressOverview.title"),
              });
            }}
            title={t("progressOverview.viewObject", { name: group.label })}
          >
            {group.label}
          </button>
        ) : (
          <span className="agent-work-group-name">{group.label}</span>
        )}
        <span className="agent-work-group-count">
          {group.counts.completed}
          <span> / {group.counts.total}</span>
        </span>
      </div>
      <div
        className="agent-work-completion"
        aria-label={t("progressOverview.completedOf", {
          done: group.counts.completed,
          total: group.counts.total,
        })}
      >
        {(["completed", "running", "attention", "preparing"] as const).map(
          (phase) =>
            group.counts[phase] > 0 && (
              <span
                key={phase}
                data-phase={phase}
                style={{ flexGrow: group.counts[phase] }}
              />
            ),
        )}
      </div>
      <ul className="agent-work-operations">
        {matching.map((item) => (
          <OperationRow
            key={item.id}
            item={item}
            groupLabel={group.label}
            projectId={projectId}
          />
        ))}
      </ul>
    </article>
  );
}

export default function AgentProgressOverview({
  projectId,
}: {
  projectId: string;
}) {
  const { t, i18n } = useTranslation();
  const [filter, setFilter] = useState<ProgressFilter>("all");
  const [expanded, setExpanded] = useState(true);
  const detailsId = useId();
  const graph = useWorkGraphStore((state) =>
    state.projectId === projectId ? state.graph : null,
  );
  const taskState = useCreatorTaskViewStore();
  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const projectGeneration = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.generation : null,
  );
  useEffect(() => {
    if (projectGeneration === null) return;
    const current = useWorkGraphStore.getState();
    if (
      current.projectId === projectId &&
      current.graph &&
      current.graph.generation >= projectGeneration
    )
      return;
    // Project edits can create the first production nodes without a Task
    // event. An empty graph cannot activate the existing work-graph poll,
    // so refresh once per observed Project publication to discover them.
    // The store fences overlapping requests and project switches; graph
    // responses themselves must not trigger another refresh loop.
    void current.refresh(projectId);
  }, [projectId, projectGeneration]);
  const pendingReviewUnits = useFileProjectReviewStore((state) =>
    state.projectId === projectId
      ? state.reviews.reduce(
          (count, review) =>
            count +
            (review.status === "PENDING" ? reviewPendingUnits(review) : 0),
          0,
        )
      : 0,
  );
  const pendingAuthorizations = useExecutionAuthorizationStore((state) =>
    state.projectId === projectId
      ? state.items.filter((item) => item.status === "PENDING").length
      : 0,
  );
  const model = useMemo(
    () =>
      buildAgentProgressModel({
        projectId,
        graph,
        project,
        runs: taskState.projectId === projectId ? taskState.runs : [],
        tasks: taskState.projectId === projectId ? taskState.tasks : [],
      }),
    [
      projectId,
      graph,
      project,
      taskState.projectId,
      taskState.runs,
      taskState.tasks,
      i18n.language,
    ],
  );
  useEffect(() => {
    setFilter("all");
  }, [projectId]);
  const reviewing = Math.max(
    graph?.counts?.waiting_review ?? 0,
    pendingReviewUnits,
  );
  const groups = model.groups.filter(
    (group) =>
      filter === "all" || group.items.some((item) => item.phase === filter),
  );
  const runningGroups = model.groups.filter(
    (group) => group.counts.running > 0,
  ).length;
  const subtitle = pendingAuthorizations
    ? t("agent.productionConfirmPending", { count: pendingAuthorizations })
    : runningGroups > 1
    ? t("progressOverview.parallelGroups", { count: runningGroups })
    : model.counts.running
    ? t("progressOverview.runningOperations", {
        count: model.counts.running,
      })
    : reviewing
    ? t("agentActivity.needsReview", { count: reviewing })
    : model.counts.attention
    ? t("agentActivity.needsAttention", {
        count: model.counts.attention,
      })
    : model.counts.completed
    ? t("progressOverview.retained", {
        count: model.counts.completed,
      })
    : model.counts.preparing
    ? t("progressOverview.upcoming", {
        count: model.counts.preparing,
      })
    : t("progressOverview.ready");
  const stats = () => (
    <div
      className="agent-progress-metrics"
      aria-label={t("progressOverview.filters")}
    >
      {filters.map((value) => (
        <button
          key={value}
          type="button"
          data-filter={value}
          aria-pressed={filter === value}
          aria-label={`${t(`progressOverview.${value}`)} ${
            value === "all" ? model.counts.total : model.counts[value]
          }`}
          onClick={() => setFilter(value)}
        >
          <strong>
            {value === "all" ? model.counts.total : model.counts[value]}
          </strong>
          <span>{t(`progressOverview.${value}`)}</span>
        </button>
      ))}
    </div>
  );
  const reviewNotice = reviewing > 0 && (
    <p className="agent-overview-review">
      <AlertCircle aria-hidden />
      {t("agentActivity.needsReview", { count: reviewing })}
      <span>{t("progressOverview.reviewBelow")}</span>
    </p>
  );
  return (
    <section
      data-agent-progress-overview
      data-expanded={expanded}
      className="agent-progress-overview"
      aria-label={t("progressOverview.title")}
    >
      <button
        type="button"
        className="agent-progress-header"
        aria-expanded={expanded}
        aria-controls={detailsId}
        aria-label={t(
          expanded ? "progressOverview.collapse" : "progressOverview.expand",
        )}
        onClick={() => setExpanded((value) => !value)}
      >
        <span className="agent-progress-emblem" aria-hidden>
          <AgentActivityIndicator
            phase={
              model.counts.running
                ? "running"
                : reviewing || pendingAuthorizations || model.counts.attention
                ? "attention"
                : model.counts.total &&
                  model.counts.completed === model.counts.total
                ? "completed"
                : "waiting"
            }
          />
        </span>
        <span className="agent-progress-heading">
          <span className="agent-progress-title">
            {t("progressOverview.title")}
          </span>
          <small>{subtitle}</small>
        </span>
        <ChevronDown className="agent-progress-chevron" aria-hidden />
      </button>
      {expanded && (
        <div id={detailsId} className="agent-progress-body">
          {stats()}
          <div className="agent-progress-details" tabIndex={0}>
            {pendingAuthorizations > 0 && (
              <p className="agent-overview-review">
                <AlertCircle aria-hidden />
                {t("agent.productionConfirmPending", {
                  count: pendingAuthorizations,
                })}
                <span>{t("progressOverview.confirmBelow")}</span>
              </p>
            )}
            {reviewNotice}
            <div className="agent-progress-groups">
              {groups.map((group) => (
                <WorkGroupCard
                  key={group.id}
                  group={group}
                  filter={filter}
                  projectId={projectId}
                />
              ))}
            </div>
            {!groups.length && (
              <p className="agent-progress-empty">
                {t(
                  model.counts.total
                    ? "progressOverview.emptyFilter"
                    : "progressOverview.empty",
                )}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
