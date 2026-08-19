import { useEffect, useMemo, useRef, useState } from "react";
import { message } from "antd";
import {
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Layers,
  List,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import type {
  ExecutionAuthorizationView,
  FileProjectReviewRecord,
  ProjectDocument,
} from "@/contracts/creator";
import { useAgentDockUiStore } from "@/store/agentDockUiStore";
import { useExecutionAuthorizationStore } from "@/store/executionAuthorizationStore";
import { useFileProjectReviewStore } from "@/store/fileProjectReviewStore";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { creatorTargetLabel } from "@/lib/creatorPresentation";
import ExecutionAuthorizationCard from "./ExecutionAuthorizationCard";
import FileProjectReviewPanel, {
  reviewPendingUnits,
  reviewTrayLabel,
} from "./FileProjectReviewPanel";
import i18n from "@/i18n";

/**
 * Inline decision tray: pins reviews and production confirmations between the
 * chat stream and the status bar. Tiered alerting — production confirmations
 * are blocking (always sorted first, force-expand and flash on arrival) while
 * reviews are ordinary (may collapse into a summary bar without interrupting
 * the conversation).
 */

type TrayItem =
  | {
      key: string;
      kind: "auth";
      label: string;
      authorization: ExecutionAuthorizationView;
    }
  | {
      key: string;
      kind: "review";
      label: string;
      review: FileProjectReviewRecord;
    };

function trayItemsOf(
  pendingAuths: ExecutionAuthorizationView[],
  pendingReviews: FileProjectReviewRecord[],
  project: ProjectDocument | null,
): TrayItem[] {
  return [
    // Blocking items always come first, then reviews (keeping backend order).
    ...pendingAuths.map<TrayItem>((authorization) => ({
      key: `auth:${authorization.id}`,
      kind: "auth",
      label: `${i18n.t("decisionTray.productionConfirm")}${creatorTargetLabel(
        authorization.targetRef,
        project,
      )}`,
      authorization,
    })),
    ...pendingReviews.map<TrayItem>((review) => ({
      key: `review:${review.review_id}`,
      kind: "review",
      label: reviewTrayLabel(review),
      review,
    })),
  ];
}

export default function DecisionTray({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const authorizations = useExecutionAuthorizationStore((state) => state.items);
  const authProjectId = useExecutionAuthorizationStore(
    (state) => state.projectId,
  );
  const authError = useExecutionAuthorizationStore((state) => state.error);
  const fileReviews =
    useFileProjectReviewStore((state) =>
      state.projectId === projectId ? state.reviews : null,
    ) ?? [];
  const decide = useFileProjectReviewStore((state) => state.decide);
  const project = useProjectSnapshotStore((state) =>
    state.projectId === projectId ? state.project : null,
  );
  const collapsed = useAgentDockUiStore((state) => state.decisionTrayCollapsed);
  const setCollapsed = useAgentDockUiStore(
    (state) => state.setDecisionTrayCollapsed,
  );

  const pendingAuths = useMemo(
    () =>
      authProjectId === projectId
        ? authorizations.filter((item) => item.status === "PENDING")
        : [],
    [authProjectId, authorizations, projectId],
  );
  const pendingReviews = useMemo(
    () =>
      fileReviews.filter(
        (review) =>
          review.status === "PENDING" && reviewPendingUnits(review) > 0,
      ),
    [fileReviews],
  );
  const items = useMemo(
    () => trayItemsOf(pendingAuths, pendingReviews, project),
    [pendingAuths, pendingReviews, project],
  );
  const urgent = pendingAuths.length > 0;

  const [filter, setFilter] = useState<"all" | "auth" | "review">("all");
  const [listMode, setListMode] = useState(false);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const previousAuthCount = useRef(0);
  const firstAuthKey = items.find((item) => item.kind === "auth")?.key ?? null;

  // Blocking item arrived: force-expand the tray, focus the newest production
  // confirmation and flash to draw attention.
  useEffect(() => {
    const previous = previousAuthCount.current;
    previousAuthCount.current = pendingAuths.length;
    if (pendingAuths.length <= previous) return;
    setCollapsed(false);
    setFilter("all");
    if (firstAuthKey) setFocusKey(firstAuthKey);
    setFlash(true);
    const timer = window.setTimeout(() => setFlash(false), 2200);
    return () => window.clearTimeout(timer);
  }, [firstAuthKey, pendingAuths.length, setCollapsed]);

  const visible = useMemo(
    () =>
      filter === "all"
        ? items
        : items.filter((item) =>
            filter === "auth" ? item.kind === "auth" : item.kind === "review",
          ),
    [filter, items],
  );

  // Fall back to "all" when the current filter empties out (e.g. the last
  // production confirmation was just handled).
  useEffect(() => {
    if (filter !== "all" && visible.length === 0 && items.length > 0) {
      setFilter("all");
    }
  }, [filter, items.length, visible.length]);

  if (items.length === 0) return null;

  const focusIndex = Math.max(
    0,
    visible.findIndex((item) => item.key === focusKey),
  );
  const focused = visible[focusIndex] ?? visible[0];
  const nextItems = visible.slice(focusIndex + 1, focusIndex + 3);
  const reviewUnitCount = pendingReviews.reduce(
    (total, review) => total + reviewPendingUnits(review),
    0,
  );

  const step = (delta: number) => {
    const next = Math.min(Math.max(focusIndex + delta, 0), visible.length - 1);
    setFocusKey(visible[next]?.key ?? null);
  };

  const acceptAllReviews = async () => {
    setBatchBusy(true);
    try {
      for (const review of pendingReviews) {
        const operations = review.operations.filter(
          (operation) => operation.decision === "PENDING",
        );
        if (operations.length === 0) continue;
        await decide(
          projectId,
          review.review_id,
          operations.map((operation) => ({
            operation_id: operation.operation_id,
            decision: "ACCEPT",
          })),
        );
      }
      message.success(t("decisionTray.allReviewChangesKept"));
    } catch (error) {
      message.error(error instanceof Error ? error.message : String(error));
    } finally {
      setBatchBusy(false);
    }
  };

  const renderCard = (item: TrayItem) =>
    item.kind === "auth" ? (
      <ExecutionAuthorizationCard
        authorization={item.authorization}
        project={project}
      />
    ) : (
      <FileProjectReviewPanel projectId={projectId} review={item.review} />
    );

  return (
    <section
      data-decision-tray
      data-decision-tray-urgent={urgent ? "true" : undefined}
      data-decision-tray-collapsed={collapsed ? "true" : undefined}
      className={`border-t border-[var(--color-border)] ${
        urgent && collapsed
          ? "bg-[var(--color-warning-soft)]"
          : "bg-[var(--color-bg-secondary)]/40"
      } ${flash ? "decision-tray-flash" : ""}`}
    >
      <button
        type="button"
        aria-expanded={!collapsed}
        aria-label={
          collapsed
            ? t("decisionTray.expandTray")
            : t("decisionTray.collapseTray")
        }
        onClick={() => setCollapsed(!collapsed)}
        className="flex w-full items-center gap-2 px-3.5 py-1.5 text-left"
      >
        <span
          className={`h-2 w-2 shrink-0 rounded-full ${
            urgent
              ? "decision-tray-dot-urgent bg-[var(--color-warning)]"
              : "decision-tray-dot bg-[var(--color-accent)]"
          }`}
        />
        <span
          className={`shrink-0 text-[11px] font-semibold ${
            urgent
              ? "text-[var(--color-warning)]"
              : "text-[var(--color-text-primary)]"
          }`}
        >
          {items.length} {t("decisionTray.itemsPending")}
          {urgent ? t("decisionTray.needConfirm") : ""}
        </span>
        <span
          className={`min-w-0 flex-1 truncate text-[10px] ${
            urgent && collapsed
              ? "text-[var(--color-warning)]/85"
              : "text-[var(--color-text-tertiary)]"
          }`}
        >
          {urgent
            ? `${t("decisionTray.productionConfirmBlock")} ${
                pendingAuths.length
              } ${t("decisionTray.itemsBlocking")}${
                reviewUnitCount > 0
                  ? ` · ${t("decisionTray.review")} ${reviewUnitCount}`
                  : ""
              }`
            : `${t("decisionTray.review")} ${reviewUnitCount}`}
        </span>
        <ChevronDown
          className={`h-3.5 w-3.5 shrink-0 text-[var(--color-text-tertiary)] transition-transform ${
            collapsed ? "" : "rotate-180"
          }`}
        />
      </button>

      {!collapsed && (
        <div className="px-3.5 pb-2.5">
          {authError && (
            <p
              role="alert"
              className="mb-2 rounded-md bg-[var(--color-warning-soft)] px-2 py-1 text-[10px] text-[var(--color-warning)]"
            >
              {t("decisionTray.loadFailed")}
              {authError}
            </p>
          )}
          {items.length > 1 && (
            <div className="mb-2 flex items-center gap-1.5">
              {(
                [
                  ["all", `${t("decisionTray.all")} ${items.length}`],
                  [
                    "auth",
                    `${t("decisionTray.productionConfirmTab")} ${
                      pendingAuths.length
                    }`,
                  ],
                  [
                    "review",
                    `${t("decisionTray.reviewTab")} ${pendingReviews.length}`,
                  ],
                ] as const
              )
                .filter(
                  ([key]) =>
                    key === "all" ||
                    (key === "auth"
                      ? pendingAuths.length > 0
                      : pendingReviews.length > 0),
                )
                .map(([key, label]) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => {
                      setFilter(key);
                      setFocusKey(null);
                    }}
                    className={`rounded-full border px-2 py-0.5 text-[10px] transition-colors ${
                      filter === key
                        ? "border-[var(--color-accent)] bg-[var(--color-accent-soft)] text-[var(--color-accent)]"
                        : "border-[var(--color-border)] bg-[var(--color-bg-card)] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              <span className="flex-1" />
              <button
                type="button"
                onClick={() => setListMode((mode) => !mode)}
                className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
                title={
                  listMode
                    ? t("decisionTray.switchToStack")
                    : t("decisionTray.switchToList")
                }
              >
                {listMode ? (
                  <Layers className="h-3 w-3" />
                ) : (
                  <List className="h-3 w-3" />
                )}
                {listMode ? t("decisionTray.stack") : t("decisionTray.list")}
              </button>
            </div>
          )}

          {listMode ? (
            <div className="max-h-[45vh] space-y-2 overflow-y-auto pr-0.5">
              {visible.map((item) => (
                <div key={item.key}>{renderCard(item)}</div>
              ))}
            </div>
          ) : (
            <>
              {/* Later cards show a stacked-paper top edge hinting at queue depth;
                  clicking one focuses it directly. */}
              {nextItems.length > 1 && (
                <div className="mx-5 h-1.5 rounded-t-lg border border-b-0 border-[var(--color-border)] bg-[var(--color-bg-card)]/70" />
              )}
              {nextItems.length > 0 && (
                <button
                  type="button"
                  onClick={() => setFocusKey(nextItems[0].key)}
                  title={`${t("decisionTray.next")}${nextItems[0].label}`}
                  className="mx-2.5 block w-[calc(100%-20px)] truncate rounded-t-lg border border-b-0 border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-0.5 text-left text-[9px] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
                >
                  {nextItems[0].label}
                </button>
              )}
              {focused && (
                <div
                  key={focused.key}
                  className="decision-tray-card-in max-h-[45vh] overflow-y-auto"
                >
                  {renderCard(focused)}
                </div>
              )}
              {visible.length > 1 && (
                <div className="mt-1.5 flex items-center gap-1.5">
                  <button
                    type="button"
                    aria-label={t("decisionTray.previousDecision")}
                    disabled={focusIndex === 0}
                    onClick={() => step(-1)}
                    className="flex h-5 w-5 items-center justify-center rounded border border-[var(--color-border)] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)] disabled:opacity-40"
                  >
                    <ChevronLeft className="h-3 w-3" />
                  </button>
                  <div className="flex flex-1 items-center justify-center gap-1">
                    {visible.map((item, index) => (
                      <button
                        key={item.key}
                        type="button"
                        aria-label={t("decisionTray.decisionIndex", {
                          index: index + 1,
                          label: item.label,
                        })}
                        onClick={() => setFocusKey(item.key)}
                        className={`h-1.5 rounded-full transition-all ${
                          index === focusIndex
                            ? "w-4 bg-[var(--color-accent)]"
                            : "w-1.5 bg-[var(--color-border-strong)] hover:bg-[var(--color-accent)]/50"
                        }`}
                      />
                    ))}
                  </div>
                  <button
                    type="button"
                    aria-label={t("decisionTray.nextDecision")}
                    disabled={focusIndex >= visible.length - 1}
                    onClick={() => step(1)}
                    className="flex h-5 w-5 items-center justify-center rounded border border-[var(--color-border)] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)] disabled:opacity-40"
                  >
                    <ChevronRight className="h-3 w-3" />
                  </button>
                  {pendingReviews.length > 0 && (
                    <button
                      type="button"
                      disabled={batchBusy}
                      onClick={() => void acceptAllReviews()}
                      title={t("decisionTray.keepAllReviewChanges")}
                      className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-text-tertiary)] hover:text-[var(--color-success)] disabled:opacity-50"
                    >
                      <Check className="h-3 w-3" />
                      {t("decisionTray.keepAll")}
                    </button>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
