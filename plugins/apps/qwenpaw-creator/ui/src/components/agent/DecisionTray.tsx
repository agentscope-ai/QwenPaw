import {
  memo,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
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
import { useDecisionFocusStore } from "@/store/decisionFocusStore";
import { creatorTargetLabel } from "@/lib/creatorPresentation";
import { showBackendFeedback } from "@/lib/creatorFeedback";
import { pendingUserReviewOperations } from "@/lib/fileProjectReviewDecisions";
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

// Review bodies (diffs, media previews) are hard to read at the default cap,
// so the tray edge is draggable. Mirrors the creation overview: the dragged
// height lives in the dock UI store and drives a flex-basis through a CSS var.
const TRAY_MIN_HEIGHT = 120;
const TRAY_KEYBOARD_STEP = 16;
const FEED_MIN_HEIGHT = 120;

function trayHeightBounds(section: HTMLElement) {
  const dock = section.closest<HTMLElement>("[data-agent-dock]");
  if (!dock || !dock.clientHeight) {
    return { min: TRAY_MIN_HEIGHT, max: Number.POSITIVE_INFINITY };
  }
  // Only the dock's flex-growing child (the conversation feed) can give up
  // space, so the ceiling is the tray's current height plus that slack.
  let slack = 0;
  for (const child of Array.from(dock.children)) {
    if (child === section) continue;
    if (Number.parseFloat(getComputedStyle(child).flexGrow) > 0) {
      slack += child.getBoundingClientRect().height;
    }
  }
  const max = section.getBoundingClientRect().height + slack - FEED_MIN_HEIGHT;
  return { min: TRAY_MIN_HEIGHT, max: Math.max(TRAY_MIN_HEIGHT, max) };
}

function clampTrayHeight(height: number, bounds: { min: number; max: number }) {
  return Math.round(Math.min(bounds.max, Math.max(bounds.min, height)));
}

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

function DecisionTray({ projectId }: { projectId: string }) {
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
  const pollOnce = useFileProjectReviewStore((state) => state.pollOnce);
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
  const blockingReviewIds = useDecisionFocusStore((state) => state.reviewIds);
  const focusNonce = useDecisionFocusStore((state) => state.nonce);
  const items = useMemo(() => {
    const all = trayItemsOf(pendingAuths, pendingReviews, project);
    if (blockingReviewIds.length === 0) return all;
    const priority = new Set(blockingReviewIds);
    const blocking = all.filter(
      (item) => item.kind === "review" && priority.has(item.review.review_id),
    );
    if (blocking.length === 0) return all;
    // A blocked authorization is only held up by these reviews; surface them
    // first so keeping them is one click away instead of two pages deep.
    return [
      ...blocking,
      ...all.filter(
        (item) =>
          !(item.kind === "review" && priority.has(item.review.review_id)),
      ),
    ];
  }, [blockingReviewIds, pendingAuths, pendingReviews, project]);
  const urgent = pendingAuths.length > 0;

  const sectionRef = useRef<HTMLElement | null>(null);
  const trayHeight = useAgentDockUiStore((state) => state.decisionTrayHeight);
  const setTrayHeight = useAgentDockUiStore(
    (state) => state.setDecisionTrayHeight,
  );
  const beginTrayResize = (event: ReactPointerEvent<HTMLDivElement>) => {
    const section = sectionRef.current;
    if (!section || event.button !== 0) return;
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = section.getBoundingClientRect().height;
    const bounds = trayHeightBounds(section);
    const onMove = (moveEvent: PointerEvent) => {
      // The tray is anchored to the dock bottom, so dragging UP grows it.
      setTrayHeight(
        clampTrayHeight(startHeight + (startY - moveEvent.clientY), bounds),
      );
    };
    const onUp = () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  };
  const nudgeTrayHeight = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    const section = sectionRef.current;
    if (!section) return;
    // ArrowUp grows the bottom-anchored tray; ArrowDown shrinks it.
    const direction =
      event.key === "ArrowUp" ? 1 : event.key === "ArrowDown" ? -1 : 0;
    if (!direction) return;
    event.preventDefault();
    setTrayHeight(
      clampTrayHeight(
        section.getBoundingClientRect().height + direction * TRAY_KEYBOARD_STEP,
        trayHeightBounds(section),
      ),
    );
  };
  // Mirrors the creation overview: a dragged height is exposed as a CSS var
  // and turned into flex-basis by globals.css — that is what actually resizes
  // a flex item inside the dock (an inline max-height never did).
  const resized = !collapsed && trayHeight != null;
  const traySectionStyle = resized
    ? ({ "--decision-tray-height": `${trayHeight}px` } as CSSProperties)
    : undefined;

  const [filter, setFilter] = useState<"all" | "auth" | "review">("all");
  const [listMode, setListMode] = useState(false);
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const [flash, setFlash] = useState(false);
  const [batchBusy, setBatchBusy] = useState(false);
  const previousAuthCount = useRef(0);
  const firstAuthKey = items.find((item) => item.kind === "auth")?.key ?? null;
  // One timer owns the flash state: effect cleanup must not cancel a running
  // flash while the same nonce keeps the effect from re-arming it.
  const flashTimer = useRef<number | null>(null);
  const triggerFlash = () => {
    setFlash(true);
    if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => {
      flashTimer.current = null;
      setFlash(false);
    }, 2200);
  };
  useEffect(
    () => () => {
      if (flashTimer.current !== null) window.clearTimeout(flashTimer.current);
    },
    [],
  );

  // Blocking item arrived: force-expand the tray, focus the newest production
  // confirmation and flash to draw attention.
  useEffect(() => {
    const previous = previousAuthCount.current;
    previousAuthCount.current = pendingAuths.length;
    if (pendingAuths.length <= previous) return;
    setCollapsed(false);
    setFilter("all");
    if (firstAuthKey) setFocusKey(firstAuthKey);
    triggerFlash();
  }, [firstAuthKey, pendingAuths.length, setCollapsed]);

  // The blocked authorization asked the tray to surface the reviews holding it
  // up: expand, focus the first blocking review and flash the tray. The nonce
  // guard keeps later snapshots from re-stealing focus.
  const handledFocusNonce = useRef(0);
  useEffect(() => {
    if (focusNonce === 0 || focusNonce === handledFocusNonce.current) return;
    handledFocusNonce.current = focusNonce;
    setCollapsed(false);
    setFilter("all");
    const priority = new Set(blockingReviewIds);
    const target =
      items.find(
        (item) => item.kind === "review" && priority.has(item.review.review_id),
      ) ??
      items.find((item) => item.kind === "review") ??
      items[0];
    if (target) setFocusKey(target.key);
    triggerFlash();
  }, [blockingReviewIds, focusNonce, items, setCollapsed]);

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
    let kept = 0;
    const failures: string[] = [];
    try {
      for (const review of pendingReviews) {
        const operations = pendingUserReviewOperations(review);
        if (operations.length === 0) continue;
        const reconciledBefore =
          useFileProjectReviewStore.getState().reconciledDecision?.at;
        try {
          await decide(
            projectId,
            review.review_id,
            operations.map((operation) => ({
              operation_id: operation.operation_id,
              decision: "ACCEPT",
            })),
          );
          kept += 1;
        } catch (error) {
          // Per-item isolation: earlier keeps already committed, so report
          // exactly what landed instead of a blanket failure toast. A review
          // leaving the pending list proves nothing about this decision —
          // another tab may have rejected it. Only the store's reconciliation
          // stamp (set after a poll shows this decision's operations are no
          // longer pending) may credit a failed submit as kept; ``decide``
          // awaits it before rejecting.
          await pollOnce(projectId).catch(() => undefined);
          const reconciled =
            useFileProjectReviewStore.getState().reconciledDecision;
          if (
            reconciled &&
            reconciled.reviewId === review.review_id &&
            reconciled.at !== reconciledBefore
          ) {
            kept += 1;
            continue;
          }
          failures.push(
            error instanceof Error
              ? error.message
              : t("fileReview.public.decisionFailed"),
          );
        }
      }
      if (failures.length === 0) {
        message.success(t("decisionTray.allReviewChangesKept"));
      } else {
        showBackendFeedback(
          "warning",
          t("decisionTray.batchPartialKept", {
            kept,
            failed: failures.length,
            reason: failures[0],
          }),
          t("decisionTray.batchPartialTitle"),
        );
      }
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
      ref={sectionRef}
      data-decision-tray
      data-resized={resized || undefined}
      style={traySectionStyle}
      data-decision-tray-urgent={urgent ? "true" : undefined}
      data-decision-tray-collapsed={collapsed ? "true" : undefined}
      data-decision-tray-focused={focused?.key}
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
          className={`min-w-0 flex-1 truncate text-[11px] ${
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
        <div
          data-decision-tray-resize
          role="separator"
          aria-orientation="horizontal"
          aria-label={t("decisionTray.dragToResize")}
          title={t("decisionTray.dragToResize")}
          tabIndex={0}
          className="decision-tray-resize group flex h-2 shrink-0 cursor-ns-resize touch-none items-center justify-center"
          onPointerDown={beginTrayResize}
          onKeyDown={nudgeTrayHeight}
          onDoubleClick={() => setTrayHeight(null)}
        >
          <span className="pointer-events-none h-0.5 w-8 rounded-full bg-[var(--color-border-strong)] transition-colors group-hover:bg-[var(--color-accent)]" />
        </div>
      )}
      {!collapsed && (
        <div className="px-3.5 pb-2.5">
          {authError && (
            <p
              role="alert"
              className="mb-2 rounded-md bg-[var(--color-warning-soft)] px-2 py-1 text-[11px] text-[var(--color-warning)]"
            >
              {t("decisionTray.loadFailed")}
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
                    className={`rounded-full border px-2 py-0.5 text-[11px] transition-colors ${
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
                className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
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
            <div
              data-decision-tray-body
              className="agent-decision-scroll max-h-[28vh] space-y-2 overflow-y-auto pr-0.5"
            >
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
                  className="mx-2.5 block w-[calc(100%-20px)] truncate rounded-t-lg border border-b-0 border-[var(--color-border)] bg-[var(--color-bg-card)] px-3 py-0.5 text-left text-[11px] text-[var(--color-text-tertiary)] hover:text-[var(--color-accent)]"
                >
                  {nextItems[0].label}
                </button>
              )}
              {focused && (
                <div
                  key={focused.key}
                  data-decision-tray-body
                  className="agent-decision-scroll decision-tray-card-in max-h-[28vh] overflow-y-auto"
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
                      className="btn-decision flex items-center gap-1"
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

export default memo(DecisionTray);
