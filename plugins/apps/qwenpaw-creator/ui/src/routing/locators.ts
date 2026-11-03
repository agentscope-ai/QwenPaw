import type { RefSearchItem } from "@/contracts/creator";
import i18n from "@/i18n";
import { navigate } from "./navigation";
import { useNavigationStore } from "@/store/navigationStore";
import { flashCreatorReviewField } from "./reviewFocus";
import { resolveCreatorLocator } from "./locatorTargets";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";

export function pathForLocator(
  projectId: string,
  locator: Record<string, string>,
): string {
  // A production group or element can belong to any episode. Keep its
  // explicit timeline scope all the way to the parameterized editor route;
  // the legacy route selects the primary timeline when no scope is supplied.
  const planPath = locator.timelineId
    ? `/project/${projectId}/t/${encodeURIComponent(locator.timelineId)}/plan`
    : `/project/${projectId}/plan`;
  switch (locator.page) {
    case "blueprint":
      // Blueprint reviews deep-link to the project root; a timelineId selects
      // the corresponding narrative node once the page mounts.
      return locator.timelineId
        ? `/project/${projectId}?timeline=${encodeURIComponent(
            locator.timelineId,
          )}`
        : `/project/${projectId}`;
    case "assets":
      return `/project/${projectId}/assets`;
    case "element":
      // Generated storyboard/video is produced in the Element workbench; jump
      // straight to it so the review "View" lands on the generation detail.
      return locator.elementId
        ? `${planPath}/element/${encodeURIComponent(locator.elementId)}`
        : planPath;
    default:
      return planPath;
  }
}

function currentHashPath(): string {
  const value = window.location.hash.replace(/^#/, "");
  return value || "/";
}

export function navigateToLocator(
  projectId: string,
  locator: Record<string, string>,
  options: {
    description?: string;
    field?: string;
    review?: boolean;
    focusField?: boolean;
  } = {},
): void {
  const snapshot = useProjectSnapshotStore.getState();
  locator = resolveCreatorLocator(
    locator,
    snapshot.projectId === projectId ? snapshot.project : null,
    options.field ?? locator.field,
  );
  const base = pathForLocator(projectId, locator);
  const params = new URLSearchParams();
  if (locator.elementId) params.set("element", locator.elementId);
  if (locator.assetId) params.set("asset", locator.assetId);
  if (locator.variantId) params.set("variant", locator.variantId);
  const versionId = locator.versionId || locator.artifactVersionId;
  if (versionId) params.set("version", versionId);
  if (locator.focus) params.set("focus", locator.focus);
  if (options.review) params.set("review", "1");
  const field = options.field ?? locator.field;
  if (field) params.set("field", field);
  // Operation navigation can focus an authored field without entering review
  // mode (which would show review-specific content and controls).
  const focusField = Boolean(options.focusField && field);
  if (focusField) params.set("focusField", "1");
  // Unique on every click, including repeated clicks on the current route.
  const reviewPulse = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  if (options.review || focusField) params.set("reviewPulse", reviewPulse);
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
  if ((options.review || focusField) && field) {
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
        // A later navigation owns focus, even if an earlier click's delayed
        // replay would find a matching field in another episode or project.
        const currentFocus = useNavigationStore.getState().reviewFocus;
        if (
          currentFocus?.path !== focusRequest.path ||
          currentFocus.query.reviewPulse !== reviewPulse
        )
          return;
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
        flashCreatorReviewField(field, workspaceRoot ?? document);
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
