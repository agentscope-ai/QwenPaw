import {
  Navigate,
  Outlet,
  createHashRouter,
  useLocation,
  type RouteObject,
} from "react-router-dom";
import { Suspense, lazy } from "react";
import { useTranslation } from "react-i18next";
import ProjectLayout from "@/components/layout/ProjectLayout";
import PageSkeleton from "@/components/PageSkeleton";
import { loadWithChunkRecovery } from "@/lib/lazyWithChunkRecovery";
import { useProjectSnapshotStore } from "@/store/projectSnapshotStore";
import { NavigationRuntime, navigate, useParams } from "@/routing/navigation";

const HomePage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/HomePage")),
);
const PlanPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/PlanPage")),
);
const AssetsPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/AssetsPage")),
);
const R2VWorkbenchPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/R2VWorkbenchPage")),
);
const BlueprintPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/BlueprintPage")),
);
const BlueprintDemoPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/BlueprintDemoPage")),
);
const BlueprintDemoPlanPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/BlueprintDemoPlanPage")),
);
const BlueprintDemoAssetsPage = lazy(() =>
  loadWithChunkRecovery(() => import("@/pages/BlueprintDemoAssetsPage")),
);

function suspended(
  element: React.ReactNode,
  type: "grid" | "list" | "editor" = "list",
) {
  return <Suspense fallback={<PageSkeleton type={type} />}>{element}</Suspense>;
}

export const FORMAL_CREATOR_ROUTES = [
  "/",
  "/project/:id",
  "/project/:id/t/:timelineId/plan",
  "/project/:id/t/:timelineId/plan/element/:elementId",
  "/project/:id/plan",
  "/project/:id/plan/element/:elementId",
  "/project/:id/assets",
] as const;

/**
 * Legacy /project/:id/plan entry: redirect to the primary timeline's
 * parameterized route once the snapshot is loaded (skeleton before that).
 */
function LegacyPlanRedirect() {
  const { id = "" } = useParams();
  const timelineId = useProjectSnapshotStore((state) =>
    state.projectId === id
      ? state.project?.timelines.order.find(
          (candidate) => state.project?.timelines.items[candidate],
        ) ?? null
      : null,
  );
  const location = useLocation();
  if (!timelineId) return <PageSkeleton type="editor" />;
  return (
    <Navigate
      to={`/project/${id}/t/${encodeURIComponent(timelineId)}/plan${
        location.search
      }`}
      replace
    />
  );
}

function RouteRuntime() {
  return (
    <>
      <NavigationRuntime />
      <Outlet />
    </>
  );
}

export function NotFoundPage({ projectId }: { projectId?: string }) {
  const { t } = useTranslation();
  return (
    <div className="flex h-full min-h-[60vh] items-center justify-center bg-[var(--color-bg-layout)] px-6">
      <div className="max-w-sm text-center">
        <p className="text-sm font-semibold text-[var(--color-text-primary)]">
          {t("router.notFound")}
        </p>
        <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
          {t("router.notFoundDesc")}
        </p>
        <button
          type="button"
          onClick={() =>
            navigate(projectId ? `/project/${projectId}` : "/", true)
          }
          className="mt-4 rounded border border-[var(--color-border)] bg-white px-3 py-1.5 text-sm font-medium text-[var(--color-text-primary)] hover:bg-[var(--color-bg-secondary)] dark:bg-[var(--color-bg-primary)]"
        >
          {t("router.back")}
        </button>
      </div>
    </div>
  );
}

function ProjectNotFoundPage() {
  const { id } = useParams();
  return <NotFoundPage projectId={id} />;
}

export const CREATOR_ROUTE_OBJECTS: RouteObject[] = [
  {
    id: "route-runtime",
    element: <RouteRuntime />,
    children: [
      { id: "home", path: "/", element: suspended(<HomePage />, "grid") },
      {
        id: "blueprint-demo",
        path: "/blueprint-demo",
        element: suspended(<BlueprintDemoPage />, "editor"),
      },
      {
        id: "blueprint-demo-plan",
        path: "/blueprint-demo/:id/plan",
        element: suspended(<BlueprintDemoPlanPage />, "editor"),
      },
      {
        id: "blueprint-demo-assets",
        path: "/blueprint-demo/:id/assets",
        element: suspended(<BlueprintDemoAssetsPage />, "grid"),
      },
      {
        id: "project",
        path: "/project/:id",
        element: <ProjectLayout />,
        children: [
          {
            id: "project-blueprint",
            index: true,
            element: suspended(<BlueprintPage />, "editor"),
          },
          {
            id: "project-timeline-plan",
            path: "t/:timelineId/plan",
            element: suspended(<PlanPage />),
          },
          {
            id: "project-timeline-element-workbench",
            path: "t/:timelineId/plan/element/:elementId",
            element: suspended(<R2VWorkbenchPage />, "editor"),
          },
          {
            // Legacy path: redirect to the primary timeline's parameterized
            // plan route once the snapshot store carries the timeline order.
            id: "project-plan",
            path: "plan",
            element: <LegacyPlanRedirect />,
          },
          {
            id: "project-element-workbench",
            path: "plan/element/:elementId",
            element: suspended(<R2VWorkbenchPage />, "editor"),
          },
          {
            id: "project-assets",
            path: "assets",
            element: suspended(<AssetsPage />, "grid"),
          },
          {
            id: "project-not-found",
            path: "*",
            element: <ProjectNotFoundPage />,
          },
        ],
      },
      { id: "not-found", path: "*", element: <NotFoundPage /> },
    ],
  },
];

export function createCreatorRouter() {
  return createHashRouter(CREATOR_ROUTE_OBJECTS);
}

export const creatorRouter = createCreatorRouter();
