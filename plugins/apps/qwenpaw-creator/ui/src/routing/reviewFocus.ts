import { useCallback, useEffect, useRef } from "react";
import { useNavigationStore } from "@/store/navigationStore";

type ReviewFocusRuntime = Window & {
  __creatorReviewFocus?: (request: {
    path: string;
    query: Record<string, string>;
  }) => void;
};

interface UseReviewFieldFocusOptions {
  /** Page path without query; requests for other pages are ignored. */
  path: string;
  /** The `field` URL param; lets focus restore after a refresh. */
  field: string | null;
  /** True when the URL has review=1. */
  enabled: boolean;
  /** Replays the animation when the same route/field is viewed repeatedly. */
  pulse: string | null;
}

const RETRY_INTERVAL_MS = 50;
const MAX_RETRIES = 40;
const FLASH_DURATION_MS = 2400;
const fallbackFlashTokens = new WeakMap<HTMLElement, number>();
let fallbackFlashSequence = 0;
// Every "View" click generates a unique reviewPulse. The focus/flash animation
// only fires the first time a pulse is consumed; leftover URL params, component
// remounts, and snapshot polling never replay it.
const consumedFocusPulses = new Set<string>();

function consumePulse(pulse: string | null | undefined): boolean {
  if (!pulse) return false;
  if (consumedFocusPulses.has(pulse)) return false;
  consumedFocusPulses.add(pulse);
  return true;
}

/** Attribute scan; field paths with `:` or `/` can't go into a CSS selector. */
export function findCreatorFieldElement(
  field: string,
  root: ParentNode = document,
): HTMLElement | null {
  // A review operation's locator field is the RFC 6901 JSON pointer of the
  // change.  DOM fields expose that pointer via data-creator-path, plus a
  // human data-creator-field/data-review-field alias.  Match any of them so a
  // backend-derived locator (which uses the pointer) can find the node.
  return (
    Array.from(
      root.querySelectorAll<HTMLElement>(
        "[data-review-field], [data-creator-field], [data-creator-path]",
      ),
    ).find(
      (element) =>
        element.getAttribute("data-review-field") === field ||
        element.getAttribute("data-creator-field") === field ||
        element.getAttribute("data-creator-path") === field,
    ) ?? null
  );
}

/** textarea/input can't host ::after; flash the enclosing block instead. */
export function reviewFlashElementForField(
  field: string,
  root: ParentNode = document,
): HTMLElement | null {
  const fieldElement = findCreatorFieldElement(field, root);
  if (!fieldElement) return null;
  if (fieldElement.matches("textarea, input")) {
    return (
      fieldElement.closest<HTMLElement>("section") ??
      fieldElement.parentElement ??
      fieldElement
    );
  }
  return fieldElement;
}

/** Immediate same-page fallback used after AgentDock closes on "View". */
export function flashCreatorReviewField(
  field: string,
  root: ParentNode = document,
): HTMLElement | null {
  const target = reviewFlashElementForField(field, root);
  if (!target) return null;
  const token = ++fallbackFlashSequence;
  fallbackFlashTokens.set(target, token);
  target.scrollIntoView({ behavior: "smooth", block: "center" });
  target.classList.remove("review-flash");
  void target.offsetWidth;
  target.classList.add("review-flash");
  window.setTimeout(() => {
    if (fallbackFlashTokens.get(target) !== token) return;
    target.classList.remove("review-flash");
    fallbackFlashTokens.delete(target);
  }, FLASH_DURATION_MS);
  return target;
}

/** Media-review "View" landing anchor: preview block by artifact version. */
export function findReviewMediaAnchor(
  versionId: string,
  root: ParentNode = document,
): HTMLElement | null {
  return (
    Array.from(
      root.querySelectorAll<HTMLElement>("[data-review-media-anchor]"),
    ).find(
      (element) =>
        element.getAttribute("data-review-media-anchor") === versionId,
    ) ?? null
  );
}

/**
 * Media-review focus emphasis: image/video "View" without a field pointer
 * flashes the block anchored by version.
 *
 * Shares the pulse consumption set with useReviewFieldFocus, so a single click
 * triggers only one kind of emphasis; the target preview may mount only after
 * the snapshot/media loads, so a short poll waits for the anchor as well.
 */
export function useReviewMediaFocus({
  versionId,
  enabled,
  pulse,
}: {
  /** The `version` URL param; points at the artifact version awaiting review. */
  versionId: string | null;
  /** True when URL has review=1 and no field (field focus takes over then). */
  enabled: boolean;
  pulse: string | null;
}): void {
  const retryTimerRef = useRef<number | null>(null);
  const sequenceRef = useRef(0);

  useEffect(() => {
    if (!enabled || !versionId || !consumePulse(pulse)) return;
    const sequence = ++sequenceRef.current;
    let retries = 0;
    const tryFlash = () => {
      if (sequence !== sequenceRef.current) return;
      const workspaceRoot = document.querySelector<HTMLElement>(
        "[data-creator-workspace-root]",
      );
      const target = findReviewMediaAnchor(
        versionId,
        workspaceRoot ?? document,
      );
      if (!target) {
        if (retries++ < MAX_RETRIES) {
          retryTimerRef.current = window.setTimeout(
            tryFlash,
            RETRY_INTERVAL_MS,
          );
        }
        return;
      }
      retryTimerRef.current = null;
      target.scrollIntoView({ behavior: "smooth", block: "center" });
      target.classList.remove("review-flash");
      void target.offsetWidth;
      target.classList.add("review-flash");
      window.setTimeout(() => {
        if (sequence === sequenceRef.current)
          target.classList.remove("review-flash");
      }, FLASH_DURATION_MS);
    };
    tryFlash();
  }, [enabled, pulse, versionId]);

  useEffect(
    () => () => {
      sequenceRef.current += 1;
      if (retryTimerRef.current != null)
        window.clearTimeout(retryTimerRef.current);
    },
    [],
  );
}

/**
 * Field-level review focus for the plan page.
 *
 * Consumes both URL and navigationStore requests, and registers the current
 * page's handler for refNavigation's immediate replay. The target detail may
 * mount only after a route switch/project load, so a short poll replaces a
 * fixed delay.
 */
export function useReviewFieldFocus({
  path,
  field,
  enabled,
  pulse,
}: UseReviewFieldFocusOptions): void {
  const reviewFocusRequest = useNavigationStore((state) => state.reviewFocus);
  const requestSequenceRef = useRef(0);
  const retryTimerRef = useRef<number | null>(null);
  const settleTimerRef = useRef<number | null>(null);
  const clearTimerRef = useRef<number | null>(null);
  const activeTargetRef = useRef<HTMLElement | null>(null);

  const clearTimers = useCallback(() => {
    if (retryTimerRef.current != null)
      window.clearTimeout(retryTimerRef.current);
    if (settleTimerRef.current != null)
      window.clearTimeout(settleTimerRef.current);
    if (clearTimerRef.current != null)
      window.clearTimeout(clearTimerRef.current);
    activeTargetRef.current?.classList.remove("review-flash");
    activeTargetRef.current = null;
    retryTimerRef.current = null;
    settleTimerRef.current = null;
    clearTimerRef.current = null;
  }, []);

  const trigger = useCallback(
    (targetField: string) => {
      clearTimers();
      const sequence = ++requestSequenceRef.current;
      let retries = 0;
      let settleChecks = 0;

      const applyFlash = (target: HTMLElement) => {
        if (clearTimerRef.current != null)
          window.clearTimeout(clearTimerRef.current);
        if (activeTargetRef.current && activeTargetRef.current !== target) {
          activeTargetRef.current.classList.remove("review-flash");
        }
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.classList.remove("review-flash");
        void target.offsetWidth;
        target.classList.add("review-flash");
        activeTargetRef.current = target;
        clearTimerRef.current = window.setTimeout(() => {
          if (sequence === requestSequenceRef.current) {
            target.classList.remove("review-flash");
            if (activeTargetRef.current === target)
              activeTargetRef.current = null;
          }
          clearTimerRef.current = null;
        }, FLASH_DURATION_MS);
      };

      // Closing AgentDock and opening a Plan detail can replace the matching DOM
      // node after the first successful lookup. Re-check through the transition
      // window and replay only when React mounted a new target (or stripped the
      // class), so a same-route repeated "View" remains visible.
      const verifyMountedTarget = () => {
        if (sequence !== requestSequenceRef.current) return;
        const workspaceRoot = document.querySelector<HTMLElement>(
          "[data-creator-workspace-root]",
        );
        const mountedTarget = reviewFlashElementForField(
          targetField,
          workspaceRoot ?? document,
        );
        if (
          mountedTarget &&
          (mountedTarget !== activeTargetRef.current ||
            !mountedTarget.classList.contains("review-flash"))
        ) {
          applyFlash(mountedTarget);
        }
        if (settleChecks++ < 12) {
          settleTimerRef.current = window.setTimeout(
            verifyMountedTarget,
            RETRY_INTERVAL_MS,
          );
        } else {
          settleTimerRef.current = null;
        }
      };

      const tryFocus = () => {
        if (sequence !== requestSequenceRef.current) return;
        const workspaceRoot = document.querySelector<HTMLElement>(
          "[data-creator-workspace-root]",
        );
        const target = reviewFlashElementForField(
          targetField,
          workspaceRoot ?? document,
        );
        if (!target) {
          if (retries++ < MAX_RETRIES) {
            retryTimerRef.current = window.setTimeout(
              tryFocus,
              RETRY_INTERVAL_MS,
            );
          }
          return;
        }

        retryTimerRef.current = null;
        applyFlash(target);
        settleTimerRef.current = window.setTimeout(
          verifyMountedTarget,
          RETRY_INTERVAL_MS,
        );
      };

      tryFocus();
    },
    [clearTimers],
  );

  // Focus/flash only when this click's pulse has not been consumed yet; with no
  // pulse (non-click entry) or an already-consumed pulse (remount/poll
  // re-render), keep the page quiet.
  useEffect(() => {
    if (enabled && field && consumePulse(pulse)) trigger(field);
  }, [enabled, field, pulse, trigger]);

  // Cross-page focus requests are consumed per pulse too, so stale store
  // requests never replay on remount.
  useEffect(() => {
    if (!enabled) return;
    if (!reviewFocusRequest || reviewFocusRequest.path !== path) return;
    if (
      reviewFocusRequest.query.review !== "1" ||
      !reviewFocusRequest.query.field
    )
      return;
    if (!consumePulse(reviewFocusRequest.query.reviewPulse)) return;
    trigger(reviewFocusRequest.query.field);
  }, [enabled, path, reviewFocusRequest, trigger]);

  // Consistent with the assets page/workbench: provide the current-page handler
  // for navigateToRef's immediate replay.
  useEffect(() => {
    const runtime = window as ReviewFocusRuntime;
    const handler = (request: {
      path: string;
      query: Record<string, string>;
    }) => {
      if (
        !enabled ||
        request.path !== path ||
        request.query.review !== "1" ||
        !request.query.field
      )
        return;
      trigger(request.query.field);
    };
    runtime.__creatorReviewFocus = handler;
    return () => {
      if (runtime.__creatorReviewFocus === handler)
        delete runtime.__creatorReviewFocus;
    };
  }, [enabled, path, trigger]);

  useEffect(
    () => () => {
      requestSequenceRef.current += 1;
      clearTimers();
    },
    [clearTimers],
  );
}
