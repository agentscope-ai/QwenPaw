import type { RefSearchItem } from "@/contracts/creator";
import i18n from "@/i18n";
import { navigate } from "./navigation";
import { useNavigationStore } from "@/store/navigationStore";
import { flashCreatorReviewField } from "./reviewFocus";

export function pathForLocator(
  projectId: string,
  locator: Record<string, string>,
): string {
  switch (locator.page) {
    case "assets":
      return `/project/${projectId}/assets`;
    case "element":
      // Generated storyboard/video is produced in the Element workbench; jump
      // straight to it so the review "View" lands on the generation detail.
      return locator.elementId
        ? `/project/${projectId}/plan/element/${encodeURIComponent(
            locator.elementId,
          )}`
        : `/project/${projectId}/plan`;
    default:
      return `/project/${projectId}/plan`;
  }
}

function currentHashPath(): string {
  const value = window.location.hash.replace(/^#/, "");
  return value || "/";
}

export function navigateToLocator(
  projectId: string,
  locator: Record<string, string>,
  options: { description?: string; field?: string; review?: boolean } = {},
): void {
  const base = pathForLocator(projectId, locator);
  const params = new URLSearchParams();
  if (locator.elementId) params.set("element", locator.elementId);
  if (locator.assetId) params.set("asset", locator.assetId);
  const versionId = locator.versionId || locator.artifactVersionId;
  if (versionId) params.set("version", versionId);
  if (locator.focus) params.set("focus", locator.focus);
  if (options.review) params.set("review", "1");
  if (options.field) params.set("field", options.field);
  // Unique on every click, including repeated clicks on the current route.
  const reviewPulse = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  if (options.review) params.set("reviewPulse", reviewPulse);
  const target = params.size
    ? `${base}${base.includes("?") ? "&" : "?"}${params}`
    : base;
  const current = currentHashPath();
  useNavigationStore.getState().pushLocation({
    path: current,
    description: options.description || i18n.t("lib.reviewDecision"),
  });
  useNavigationStore.getState().setExpectedPath(base.split("?")[0]);
  useNavigationStore.getState().setReviewFocus({
    path: base.split("?")[0],
    ref: locator.assetId || locator.elementId || "",
    query: Object.fromEntries(params),
  });
  navigate(target);
  if (options.review && options.field) {
    const focusRequest = {
      path: base.split("?")[0],
      query: Object.fromEntries(params),
    };
    // Closing AgentDock and committing a same-route query can replace the Plan
    // detail node in several React frames. Replay across that short transition;
    // flashCreatorReviewField uses per-node tokens so an older click can never
    // clear the pulse created by a newer one.
    [0, 180, 420, 800].forEach((delay) =>
      window.setTimeout(() => {
        // A replay outlives the click that scheduled it, so the page may be
        // gone by the time it fires (a closed window, or a unit test whose
        // environment was torn down). Drop it instead of touching the global.
        if (typeof window === "undefined" || !window.document) return;
        const runtime = window as Window & {
          __creatorReviewFocus?: (request: {
            path: string;
            query: Record<string, string>;
          }) => void;
        };
        runtime.__creatorReviewFocus?.(focusRequest);
        const workspaceRoot = document.querySelector<HTMLElement>(
          "[data-creator-workspace-root]",
        );
        flashCreatorReviewField(options.field!, workspaceRoot ?? document);
      }, delay),
    );
  }
}

export function navigateToRefItem(
  projectId: string,
  item: RefSearchItem,
): void {
  navigateToLocator(projectId, item.uiLocator, {
    description: i18n.t("lib.reference", { name: item.name }),
  });
}

export function returnToSavedLocation(): void {
  const location = useNavigationStore.getState().popLocation();
  if (!location) return;
  const path = location.path.split("?")[0];
  useNavigationStore.getState().setExpectedPath(path);
  navigate(location.path);
}
